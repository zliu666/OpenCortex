"""Tests for credential_pool."""

import asyncio
import time

import pytest

from opencortex.auth.credential_pool import (
    Credential,
    CredentialExhaustedError,
    CredentialPool,
    CredentialStatus,
    SelectionStrategy,
)


def _make_pool(*keys: str, provider: str = "openai") -> CredentialPool:
    pool = CredentialPool()
    for k in keys:
        pool.add(Credential(api_key=k, provider=provider))
    return pool


# --- Selection Strategies ---


class TestFillFirst:
    @pytest.mark.asyncio
    async def test_always_first(self):
        pool = _make_pool("key1", "key2", "key3")
        for _ in range(5):
            c = await pool.select(SelectionStrategy.FILL_FIRST)
            assert c.api_key == "key1"


class TestRoundRobin:
    @pytest.mark.asyncio
    async def test_cycles(self):
        pool = _make_pool("key1", "key2", "key3")
        result = [await pool.select(SelectionStrategy.ROUND_ROBIN) for _ in range(6)]
        assert [c.api_key for c in result] == ["key1", "key2", "key3", "key1", "key2", "key3"]


class TestLeastUsed:
    @pytest.mark.asyncio
    async def test_picks_least(self):
        pool = _make_pool("key1", "key2", "key3")
        # Manually bump usage
        pool._credentials[0].usage_count = 10
        pool._credentials[1].usage_count = 3
        c = await pool.select(SelectionStrategy.LEAST_USED)
        assert c.api_key == "key3"


# --- Cooldown ---


class TestCooldown:
    @pytest.mark.asyncio
    async def test_429_cools_for_1_hour(self):
        pool = _make_pool("key1")
        cred = pool._credentials[0]

        class Err429(Exception):
            pass

        await pool.report_error(cred, Err429("rate limit 429"))
        assert cred.status == CredentialStatus.COOLING
        assert cred.cooldown_until is not None
        assert cred.cooldown_until > time.monotonic() + 3500

    @pytest.mark.asyncio
    async def test_402_permanent_exhaust(self):
        pool = _make_pool("key1")
        cred = pool._credentials[0]

        await pool.report_error(cred, Exception("402 payment required"))
        assert cred.status == CredentialStatus.EXHAUSTED
        assert cred.cooldown_until is None

    @pytest.mark.asyncio
    async def test_report_success_resets_cooling(self):
        pool = _make_pool("key1")
        cred = pool._credentials[0]
        cred.status = CredentialStatus.COOLING
        cred.cooldown_until = time.monotonic() + 9999
        cred.usage_count = 5

        await pool.report_success(cred)
        assert cred.status == CredentialStatus.OK
        assert cred.cooldown_until is None
        assert cred.usage_count == 6


class TestExhausted:
    @pytest.mark.asyncio
    async def test_all_exhausted_raises(self):
        pool = _make_pool("key1", "key2")
        for c in pool._credentials:
            c.status = CredentialStatus.EXHAUSTED

        with pytest.raises(CredentialExhaustedError):
            await pool.select()

    @pytest.mark.asyncio
    async def test_available_count(self):
        pool = _make_pool("key1", "key2", "key3")
        assert pool.available_count == 3

        pool._credentials[0].status = CredentialStatus.EXHAUSTED
        assert pool.available_count == 2

        pool._credentials[1].status = CredentialStatus.COOLING
        pool._credentials[1].cooldown_until = time.monotonic() + 9999
        assert pool.available_count == 1


# --- Concurrency ---


class TestConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_selects(self):
        pool = _make_pool("key1", "key2")

        async def select_and_report():
            c = await pool.select()
            await pool.report_success(c)

        # 20 concurrent selections should not crash
        await asyncio.gather(*[select_and_report() for _ in range(20)])
        total = sum(c.usage_count for c in pool._credentials)
        assert total == 20


# --- Cleanup ---


class TestCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_clears_expired(self):
        pool = _make_pool("key1")
        cred = pool._credentials[0]
        cred.status = CredentialStatus.COOLING
        cred.cooldown_until = time.monotonic() - 1  # expired

        pool.cleanup()
        assert cred.status == CredentialStatus.OK
        assert cred.cooldown_until is None
