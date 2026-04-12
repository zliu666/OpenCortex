"""Error classification and recovery chain for resilient API calls."""

import enum
import asyncio
import re
from dataclasses import dataclass, field


class FailoverReason(enum.Enum):
    AUTH = "auth"
    AUTH_PERMANENT = "auth_permanent"
    BILLING = "billing"
    RATE_LIMIT = "rate_limit"
    OVERLOADED = "overloaded"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CONTEXT_OVERFLOW = "context_overflow"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    MODEL_NOT_FOUND = "model_not_found"
    FORMAT_ERROR = "format_error"
    UNKNOWN = "unknown"


class RecoveryAction(enum.Enum):
    RETRY = "retry"                         # 退避重试
    ROTATE_CREDENTIAL = "rotate_credential" # 换凭证
    COMPRESS = "compress"                   # 压缩上下文
    DOWNGRADE = "downgrade"                 # 降级模型
    ABORT = "abort"                         # 无法恢复


@dataclass
class ClassifiedError:
    reason: FailoverReason
    retryable: bool = False
    recovery_action: RecoveryAction = RecoveryAction.ABORT
    cooldown_seconds: float = 0.0
    message: str = ""


# Provider-specific error patterns: (regex, FailoverReason)
_OPENAI_PATTERNS: list[tuple[re.Pattern, FailoverReason]] = [
    (re.compile(r"rate[_\s.]limit", re.I), FailoverReason.RATE_LIMIT),
    (re.compile(r"maximum[_\s.]context[_\s.]length", re.I), FailoverReason.CONTEXT_OVERFLOW),
    (re.compile(r"context[_\s.]length[_\s.]exceeded", re.I), FailoverReason.CONTEXT_OVERFLOW),
    (re.compile(r"model[_\s.]not[_\s.]found", re.I), FailoverReason.MODEL_NOT_FOUND),
    (re.compile(r"invalid[_\s.]api[_\s.]key", re.I), FailoverReason.AUTH_PERMANENT),
    (re.compile(r"incorrect[_\s.]api[_\s.]key", re.I), FailoverReason.AUTH_PERMANENT),
    (re.compile(r"insufficient[_\s.]quota", re.I), FailoverReason.BILLING),
    (re.compile(r"billing[_\s.]hard", re.I), FailoverReason.BILLING),
    (re.compile(r"server[_\s.]error", re.I), FailoverReason.SERVER_ERROR),
    (re.compile(r"payload[_\s.]too[_\s.]large", re.I), FailoverReason.PAYLOAD_TOO_LARGE),
    (re.compile(r"request[_\s.]too[_\s.]large", re.I), FailoverReason.PAYLOAD_TOO_LARGE),
    (re.compile(r"overloaded", re.I), FailoverReason.OVERLOADED),
]

_ANTHROPIC_PATTERNS: list[tuple[re.Pattern, FailoverReason]] = [
    (re.compile(r"thinking.*signature", re.I), FailoverReason.FORMAT_ERROR),
    (re.compile(r"long[_\s.]context.*tier", re.I), FailoverReason.RATE_LIMIT),
    (re.compile(r"rate[_\s.]limit", re.I), FailoverReason.RATE_LIMIT),
    (re.compile(r"overloaded", re.I), FailoverReason.OVERLOADED),
    (re.compile(r"invalid[_\s.]x[_\s.]api[_\s.]key", re.I), FailoverReason.AUTH_PERMANENT),
    (re.compile(r"authentication[_\s.]error", re.I), FailoverReason.AUTH),
    (re.compile(r"max[_\s.]tokens.*context", re.I), FailoverReason.CONTEXT_OVERFLOW),
    (re.compile(r"prompt.*too.*long", re.I), FailoverReason.CONTEXT_OVERFLOW),
    (re.compile(r"not[_\s.]found[_\s.]error", re.I), FailoverReason.MODEL_NOT_FOUND),
    (re.compile(r"server[_\s.]error", re.I), FailoverReason.SERVER_ERROR),
    (re.compile(r"billing", re.I), FailoverReason.BILLING),
    (re.compile(r"api[_\s.]error", re.I), FailoverReason.SERVER_ERROR),
]

_ZHIPU_PATTERNS: list[tuple[re.Pattern, FailoverReason]] = [
    (re.compile(r"rate[_\s.]limit", re.I), FailoverReason.RATE_LIMIT),
    (re.compile(r"频率限制", re.I), FailoverReason.RATE_LIMIT),
    (re.compile(r"token[_\s.]exceed|超出.*长度|上下文.*溢出", re.I), FailoverReason.CONTEXT_OVERFLOW),
    (re.compile(r"invalid[_\s.]api[_\s.]key|api[_\s.]key.*invalid", re.I), FailoverReason.AUTH_PERMANENT),
    (re.compile(r"authentication[_\s.]fail", re.I), FailoverReason.AUTH),
    (re.compile(r"model[_\s.]not[_\s.]exist|模型不存在", re.I), FailoverReason.MODEL_NOT_FOUND),
    (re.compile(r"余额不足|insufficient.*balance", re.I), FailoverReason.BILLING),
    (re.compile(r"server[_\s.]error|服务.*异常", re.I), FailoverReason.SERVER_ERROR),
    (re.compile(r"overloaded|过载", re.I), FailoverReason.OVERLOADED),
    (re.compile(r"request[_\s.]too[_\s.]large|请求过大", re.I), FailoverReason.PAYLOAD_TOO_LARGE),
]

# Status code → default reason mapping
_STATUS_CODE_MAP: dict[int, FailoverReason] = {
    401: FailoverReason.AUTH,
    402: FailoverReason.BILLING,
    403: FailoverReason.AUTH_PERMANENT,
    404: FailoverReason.MODEL_NOT_FOUND,
    413: FailoverReason.PAYLOAD_TOO_LARGE,
    429: FailoverReason.RATE_LIMIT,
    500: FailoverReason.SERVER_ERROR,
    502: FailoverReason.SERVER_ERROR,
    503: FailoverReason.OVERLOADED,
    504: FailoverReason.TIMEOUT,
}

# Reason → (retryable, action, cooldown_seconds)
_REASON_POLICY: dict[FailoverReason, tuple[bool, RecoveryAction, float]] = {
    FailoverReason.AUTH: (False, RecoveryAction.ROTATE_CREDENTIAL, 0),
    FailoverReason.AUTH_PERMANENT: (False, RecoveryAction.ROTATE_CREDENTIAL, 0),
    FailoverReason.BILLING: (False, RecoveryAction.ROTATE_CREDENTIAL, 0),
    FailoverReason.RATE_LIMIT: (True, RecoveryAction.RETRY, 5.0),
    FailoverReason.OVERLOADED: (True, RecoveryAction.RETRY, 10.0),
    FailoverReason.SERVER_ERROR: (True, RecoveryAction.RETRY, 3.0),
    FailoverReason.TIMEOUT: (True, RecoveryAction.RETRY, 2.0),
    FailoverReason.CONTEXT_OVERFLOW: (True, RecoveryAction.COMPRESS, 0),
    FailoverReason.PAYLOAD_TOO_LARGE: (True, RecoveryAction.COMPRESS, 0),
    FailoverReason.MODEL_NOT_FOUND: (False, RecoveryAction.DOWNGRADE, 0),
    FailoverReason.FORMAT_ERROR: (True, RecoveryAction.DOWNGRADE, 0),
    FailoverReason.UNKNOWN: (False, RecoveryAction.ABORT, 0),
}


def classify_api_error(error: Exception) -> ClassifiedError:
    """根据异常信息分类错误，返回对应的恢复策略。

    支持 OpenAI / Anthropic / 智谱 三种 API 的错误格式。
    """
    error_msg = str(error)
    error_msg_lower = error_msg.lower()
    status_code = getattr(error, 'status_code', None) or getattr(error, 'code', None)

    # 1. Try pattern matching against provider-specific patterns
    for patterns in (_OPENAI_PATTERNS, _ANTHROPIC_PATTERNS, _ZHIPU_PATTERNS):
        for pat, reason in patterns:
            if pat.search(error_msg):
                retryable, action, cooldown = _REASON_POLICY[reason]
                return ClassifiedError(
                    reason=reason,
                    retryable=retryable,
                    recovery_action=action,
                    cooldown_seconds=cooldown,
                    message=error_msg,
                )

    # 2. Fallback to status code mapping
    if isinstance(status_code, int):
        reason = _STATUS_CODE_MAP.get(status_code, FailoverReason.UNKNOWN)
        retryable, action, cooldown = _REASON_POLICY[reason]
        return ClassifiedError(
            reason=reason,
            retryable=retryable,
            recovery_action=action,
            cooldown_seconds=cooldown,
            message=error_msg,
        )

    # 3. Generic timeout detection
    if "timeout" in error_msg_lower or isinstance(error, (asyncio.TimeoutError, TimeoutError)):
        retryable, action, cooldown = _REASON_POLICY[FailoverReason.TIMEOUT]
        return ClassifiedError(
            reason=FailoverReason.TIMEOUT,
            retryable=retryable,
            recovery_action=action,
            cooldown_seconds=cooldown,
            message=error_msg,
        )

    # 4. Unknown
    return ClassifiedError(
        reason=FailoverReason.UNKNOWN,
        retryable=False,
        recovery_action=RecoveryAction.ABORT,
        cooldown_seconds=0,
        message=error_msg,
    )


class RecoveryChain:
    """错误恢复链：管理重试、退避、凭证轮转。"""

    def __init__(self, max_attempts: int = 3):
        self._max_attempts = max_attempts
        self._attempts = 0
        self._base_delay = 1.0

    @property
    def attempts_remaining(self) -> int:
        return self._max_attempts - self._attempts

    async def handle(self, classified: ClassifiedError) -> RecoveryAction:
        """处理分类后的错误，返回恢复动作。"""
        self._attempts += 1

        if not classified.retryable or self._attempts >= self._max_attempts:
            return RecoveryAction.ABORT

        if classified.cooldown_seconds > 0:
            jitter = classified.cooldown_seconds * 0.1 * (hash(str(self._attempts)) % 10 / 10)
            await asyncio.sleep(classified.cooldown_seconds + jitter)

        return classified.recovery_action

    def reset(self):
        self._attempts = 0
