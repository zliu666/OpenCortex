"""Multi-key credential pool with rotation and cooldown."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class CredentialStatus(str, Enum):
    OK = "ok"
    EXHAUSTED = "exhausted"
    COOLING = "cooling"


class SelectionStrategy(str, Enum):
    FILL_FIRST = "fill_first"       # Use first available until it fails
    ROUND_ROBIN = "round_robin"     # Cycle through available keys
    LEAST_USED = "least_used"       # Pick the key with lowest usage_count


@dataclass
class Credential:
    api_key: str
    provider: str
    status: CredentialStatus = CredentialStatus.OK
    cooldown_until: Optional[float] = None
    usage_count: int = 0


class CredentialExhaustedError(Exception):
    """All credentials are exhausted or in cooldown."""


class CredentialPool:
    """Thread-safe (async) pool of API credentials with cooldown management.

    Integrates with RecoveryChain: when an AUTH/BILLING error is classified,
    the recovery loop calls rotate() to switch to the next available key.
    """

    def __init__(self) -> None:
        self._credentials: List[Credential] = []
        self._rr_index: int = 0
        self._lock = asyncio.Lock()
        self._current: Optional[Credential] = None

    def add(self, credential: Credential) -> None:
        """Add a credential to the pool."""
        self._credentials.append(credential)
        if self._current is None:
            self._current = self._credentials[0]

    @property
    def available_count(self) -> int:
        """Number of credentials not in cooldown or exhausted."""
        now = time.monotonic()
        return sum(
            1 for c in self._credentials
            if c.status == CredentialStatus.OK
            and (c.cooldown_until is None or c.cooldown_until <= now)
        )

    @property
    def current_key(self) -> Optional[str]:
        """Return the current active API key, or None if pool is empty."""
        return self._current.api_key if self._current else None

    @property
    def size(self) -> int:
        return len(self._credentials)

    def _is_available(self, cred: Credential) -> bool:
        now = time.monotonic()
        return (
            cred.status == CredentialStatus.OK
            and (cred.cooldown_until is None or cred.cooldown_until <= now)
        )

    async def select(self, strategy: SelectionStrategy = SelectionStrategy.ROUND_ROBIN) -> Credential:
        """Select an available credential using the given strategy."""
        async with self._lock:
            self.cleanup()
            available = [c for c in self._credentials if self._is_available(c)]

            if not available:
                raise CredentialExhaustedError("No available credentials")

            if strategy == SelectionStrategy.FILL_FIRST:
                selected = available[0]

            elif strategy == SelectionStrategy.ROUND_ROBIN:
                self._rr_index = self._rr_index % len(available)
                selected = available[self._rr_index]
                self._rr_index = (self._rr_index + 1) % len(available)

            elif strategy == SelectionStrategy.LEAST_USED:
                selected = min(available, key=lambda c: c.usage_count)

            else:
                raise ValueError(f"Unknown strategy: {strategy}")

            self._current = selected
            return selected

    async def rotate(self) -> Credential:
        """Rotate to the next available credential (used after AUTH/BILLING errors).

        Marks the current credential as COOLING and selects the next one.
        Raises CredentialExhaustedError if no alternatives are available.
        """
        async with self._lock:
            if self._current is not None:
                self._current.status = CredentialStatus.COOLING
                self._current.cooldown_until = time.monotonic() + 3600  # 1 hour cooldown

            self.cleanup()
            available = [c for c in self._credentials if self._is_available(c)]
            if not available:
                raise CredentialExhaustedError("No alternative credentials after rotation")

            # Pick next after current
            if self._current in available:
                idx = available.index(self._current)
                selected = available[(idx + 1) % len(available)]
            else:
                selected = available[0]

            self._current = selected
            return selected

    async def report_error(self, credential: Credential, error: Exception) -> None:
        """Report an error. Handles 429 (rate limit) and 402 (payment required)."""
        async with self._lock:
            status_code = getattr(error, "status_code", None)
            if hasattr(error, "response") and hasattr(error.response, "status_code"):
                status_code = error.response.status_code

            if status_code is None:
                msg = str(error).lower()
                if "429" in msg:
                    status_code = 429
                elif "402" in msg:
                    status_code = 402

            if status_code == 429:
                credential.status = CredentialStatus.COOLING
                credential.cooldown_until = time.monotonic() + 3600  # 1 hour
            elif status_code == 402:
                credential.status = CredentialStatus.EXHAUSTED
                credential.cooldown_until = None  # permanent

    async def report_success(self, credential: Credential) -> None:
        """Report successful use of a credential."""
        async with self._lock:
            credential.usage_count += 1
            if credential.status == CredentialStatus.COOLING:
                credential.status = CredentialStatus.OK
                credential.cooldown_until = None

    def cleanup(self) -> None:
        """Clear expired cooldowns."""
        now = time.monotonic()
        for c in self._credentials:
            if c.status == CredentialStatus.COOLING and c.cooldown_until and c.cooldown_until <= now:
                c.status = CredentialStatus.OK
                c.cooldown_until = None


# ── Global singleton ──────────────────────────────────────────────────

_global_pool: Optional[CredentialPool] = None


def get_credential_pool() -> Optional[CredentialPool]:
    """Return the global credential pool singleton, or None if not initialized."""
    return _global_pool


def init_credential_pool_from_config() -> Optional[CredentialPool]:
    """Initialize the global credential pool from OpenCortex settings.

    Reads extra API keys from config and populates the pool.
    Returns the pool if keys were found, None otherwise.
    """
    global _global_pool

    try:
        from opencortex.config import settings
        keys: list[str] = []

        # Primary key
        if settings.api_key:
            keys.append(settings.api_key)

        # Extra keys from config (comma-separated or list)
        extra = getattr(settings, 'extra_api_keys', None)
        if extra:
            if isinstance(extra, str):
                keys.extend(k.strip() for k in extra.split(',') if k.strip())
            elif isinstance(extra, list):
                keys.extend(k.strip() for k in extra if k.strip())

        if len(keys) < 2:
            # No point in a pool with < 2 keys
            return None

        pool = CredentialPool()
        provider = getattr(settings, 'provider', 'openai')
        for key in keys:
            pool.add(Credential(api_key=key, provider=provider))

        _global_pool = pool
        return pool

    except Exception:
        return None
