"""Tests for error classification and recovery chain."""

import asyncio
import pytest
from unittest.mock import patch

from opencortex.engine.recovery import (
    FailoverReason,
    RecoveryAction,
    ClassifiedError,
    classify_api_error,
    RecoveryChain,
)


# --- Helpers ---

class _FakeHttpError(Exception):
    """Simulates an HTTP error with status_code attribute."""
    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.status_code = status_code


# --- classify_api_error tests ---

class TestClassifyOpenAI:
    def test_rate_limit(self):
        ce = classify_api_error(_FakeHttpError("Rate limit reached"))
        assert ce.reason == FailoverReason.RATE_LIMIT
        assert ce.retryable is True
        assert ce.recovery_action == RecoveryAction.RETRY
        assert ce.cooldown_seconds > 0

    def test_context_length(self):
        ce = classify_api_error(_FakeHttpError("maximum context length exceeded"))
        assert ce.reason == FailoverReason.CONTEXT_OVERFLOW
        assert ce.recovery_action == RecoveryAction.COMPRESS

    def test_invalid_api_key(self):
        ce = classify_api_error(_FakeHttpError("Incorrect API key provided"))
        assert ce.reason == FailoverReason.AUTH_PERMANENT
        assert ce.retryable is False
        assert ce.recovery_action == RecoveryAction.ROTATE_CREDENTIAL

    def test_model_not_found(self):
        ce = classify_api_error(_FakeHttpError("Model not found: gpt-99"))
        assert ce.reason == FailoverReason.MODEL_NOT_FOUND
        assert ce.recovery_action == RecoveryAction.DOWNGRADE

    def test_billing(self):
        ce = classify_api_error(_FakeHttpError("Insufficient quota"))
        assert ce.reason == FailoverReason.BILLING
        assert ce.recovery_action == RecoveryAction.ROTATE_CREDENTIAL

    def test_server_error(self):
        ce = classify_api_error(_FakeHttpError("Server error 500"))
        assert ce.reason == FailoverReason.SERVER_ERROR
        assert ce.retryable is True

    def test_overloaded(self):
        ce = classify_api_error(_FakeHttpError("The server is overloaded"))
        assert ce.reason == FailoverReason.OVERLOADED

    def test_payload_too_large(self):
        ce = classify_api_error(_FakeHttpError("payload too large"))
        assert ce.reason == FailoverReason.PAYLOAD_TOO_LARGE


class TestClassifyAnthropic:
    def test_thinking_signature(self):
        ce = classify_api_error(_FakeHttpError("thinking block signature mismatch"))
        assert ce.reason == FailoverReason.FORMAT_ERROR
        assert ce.recovery_action == RecoveryAction.DOWNGRADE

    def test_long_context_tier(self):
        ce = classify_api_error(_FakeHttpError("long context tier rate limit"))
        assert ce.reason == FailoverReason.RATE_LIMIT

    def test_auth_error(self):
        ce = classify_api_error(_FakeHttpError("authentication error: invalid key"))
        assert ce.reason == FailoverReason.AUTH

    def test_prompt_too_long(self):
        ce = classify_api_error(_FakeHttpError("prompt is too long: 250000 tokens"))
        assert ce.reason == FailoverReason.CONTEXT_OVERFLOW

    def test_overloaded(self):
        ce = classify_api_error(_FakeHttpError("Overloaded: API is temporarily overloaded"))
        assert ce.reason == FailoverReason.OVERLOADED


class TestClassifyZhipu:
    def test_rate_limit_chinese(self):
        ce = classify_api_error(_FakeHttpError("频率限制，请稍后再试"))
        assert ce.reason == FailoverReason.RATE_LIMIT

    def test_context_overflow_chinese(self):
        ce = classify_api_error(_FakeHttpError("超出最大长度限制"))
        assert ce.reason == FailoverReason.CONTEXT_OVERFLOW

    def test_model_not_exist_chinese(self):
        ce = classify_api_error(_FakeHttpError("模型不存在"))
        assert ce.reason == FailoverReason.MODEL_NOT_FOUND

    def test_balance_insufficient_chinese(self):
        ce = classify_api_error(_FakeHttpError("余额不足，请充值"))
        assert ce.reason == FailoverReason.BILLING


class TestClassifyByStatusCode:
    def test_401(self):
        ce = classify_api_error(_FakeHttpError("Unauthorized", status_code=401))
        assert ce.reason == FailoverReason.AUTH

    def test_403(self):
        ce = classify_api_error(_FakeHttpError("Forbidden", status_code=403))
        assert ce.reason == FailoverReason.AUTH_PERMANENT

    def test_429(self):
        ce = classify_api_error(_FakeHttpError("Too Many Requests", status_code=429))
        assert ce.reason == FailoverReason.RATE_LIMIT

    def test_404(self):
        ce = classify_api_error(_FakeHttpError("Not Found", status_code=404))
        assert ce.reason == FailoverReason.MODEL_NOT_FOUND

    def test_500(self):
        ce = classify_api_error(_FakeHttpError("Internal Server Error", status_code=500))
        assert ce.reason == FailoverReason.SERVER_ERROR

    def test_503(self):
        ce = classify_api_error(_FakeHttpError("Service Unavailable", status_code=503))
        assert ce.reason == FailoverReason.OVERLOADED

    def test_504(self):
        ce = classify_api_error(_FakeHttpError("Gateway Timeout", status_code=504))
        assert ce.reason == FailoverReason.TIMEOUT

    def test_413(self):
        ce = classify_api_error(_FakeHttpError("Payload Too Large", status_code=413))
        assert ce.reason == FailoverReason.PAYLOAD_TOO_LARGE

    def test_unknown_status_code(self):
        ce = classify_api_error(_FakeHttpError("Weird", status_code=418))
        assert ce.reason == FailoverReason.UNKNOWN


class TestClassifyTimeout:
    def test_asyncio_timeout(self):
        ce = classify_api_error(asyncio.TimeoutError())
        assert ce.reason == FailoverReason.TIMEOUT
        assert ce.retryable is True

    def test_timeout_error(self):
        ce = classify_api_error(TimeoutError("connection timed out"))
        assert ce.reason == FailoverReason.TIMEOUT

    def test_timeout_in_message(self):
        ce = classify_api_error(Exception("Request timeout after 30s"))
        assert ce.reason == FailoverReason.TIMEOUT


class TestClassifyUnknown:
    def test_unknown_error(self):
        ce = classify_api_error(RuntimeError("something weird happened"))
        assert ce.reason == FailoverReason.UNKNOWN
        assert ce.retryable is False
        assert ce.recovery_action == RecoveryAction.ABORT


# --- RecoveryChain tests ---

class TestRecoveryChain:
    def test_initial_state(self):
        chain = RecoveryChain(max_attempts=3)
        assert chain.attempts_remaining == 3

    @pytest.mark.asyncio
    async def test_retryable_returns_action(self):
        chain = RecoveryChain(max_attempts=3)
        classified = ClassifiedError(
            reason=FailoverReason.RATE_LIMIT,
            retryable=True,
            recovery_action=RecoveryAction.RETRY,
            cooldown_seconds=0,
        )
        action = await chain.handle(classified)
        assert action == RecoveryAction.RETRY
        assert chain.attempts_remaining == 2

    @pytest.mark.asyncio
    async def test_non_retryable_aborts(self):
        chain = RecoveryChain(max_attempts=3)
        classified = ClassifiedError(
            reason=FailoverReason.AUTH_PERMANENT,
            retryable=False,
            recovery_action=RecoveryAction.ROTATE_CREDENTIAL,
            cooldown_seconds=0,
        )
        action = await chain.handle(classified)
        assert action == RecoveryAction.ABORT

    @pytest.mark.asyncio
    async def test_exhausts_attempts(self):
        chain = RecoveryChain(max_attempts=2)
        classified = ClassifiedError(
            reason=FailoverReason.SERVER_ERROR,
            retryable=True,
            recovery_action=RecoveryAction.RETRY,
            cooldown_seconds=0,
        )
        # First attempt → RETRY
        assert await chain.handle(classified) == RecoveryAction.RETRY
        # Second attempt → ABORT (attempts == max_attempts)
        assert await chain.handle(classified) == RecoveryAction.ABORT
        assert chain.attempts_remaining == 0

    @pytest.mark.asyncio
    async def test_sleep_with_cooldown(self):
        chain = RecoveryChain(max_attempts=3)
        classified = ClassifiedError(
            reason=FailoverReason.RATE_LIMIT,
            retryable=True,
            recovery_action=RecoveryAction.RETRY,
            cooldown_seconds=5.0,
        )
        with patch("opencortex.engine.recovery.asyncio.sleep") as mock_sleep:
            action = await chain.handle(classified)
            assert action == RecoveryAction.RETRY
            mock_sleep.assert_called_once()
            # cooldown is 5.0 + jitter (0 to 0.5)
            call_args = mock_sleep.call_args[0][0]
            assert 5.0 <= call_args <= 5.5

    @pytest.mark.asyncio
    async def test_no_sleep_when_zero_cooldown(self):
        chain = RecoveryChain(max_attempts=3)
        classified = ClassifiedError(
            reason=FailoverReason.CONTEXT_OVERFLOW,
            retryable=True,
            recovery_action=RecoveryAction.COMPRESS,
            cooldown_seconds=0,
        )
        with patch("opencortex.engine.recovery.asyncio.sleep") as mock_sleep:
            action = await chain.handle(classified)
            assert action == RecoveryAction.COMPRESS
            mock_sleep.assert_not_called()

    def test_reset(self):
        chain = RecoveryChain(max_attempts=3)
        chain._attempts = 2
        chain.reset()
        assert chain.attempts_remaining == 3

    @pytest.mark.asyncio
    async def test_single_attempt_chain(self):
        """max_attempts=1 means first call immediately aborts."""
        chain = RecoveryChain(max_attempts=1)
        classified = ClassifiedError(
            reason=FailoverReason.SERVER_ERROR,
            retryable=True,
            recovery_action=RecoveryAction.RETRY,
            cooldown_seconds=0,
        )
        action = await chain.handle(classified)
        assert action == RecoveryAction.ABORT
