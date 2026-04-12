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
    """Thread-safe (async) pool of API credentials with cooldown management."""

    def __init__(self) -> None:
        self._credentials: List[Credential] = []
        self._rr_index: int = 0
        self._lock = asyncio.Lock()

    def add(self, credential: Credential) -> None:
        """Add a credential to the pool."""
        self._credentials.append(credential)

    @property
    def available_count(self) -> int:
        """Number of credentials not in cooldown or exhausted."""
        now = time.monotonic()
        return sum(
            1 for c in self._credentials
            if c.status == CredentialStatus.OK
            and (c.cooldown_until is None or c.cooldown_until <= now)
        )

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
                return available[0]

            elif strategy == SelectionStrategy.ROUND_ROBIN:
                # Round-robin among available only
                self._rr_index = self._rr_index % len(available)
                selected = available[self._rr_index]
                self._rr_index = (self._rr_index + 1) % len(available)
                return selected

            elif strategy == SelectionStrategy.LEAST_USED:
                return min(available, key=lambda c: c.usage_count)

            raise ValueError(f"Unknown strategy: {strategy}")

    async def report_error(self, credential: Credential, error: Exception) -> None:
        """Report an error. Handles 429 (rate limit) and 402 (payment required)."""
        async with self._lock:
            status_code = getattr(error, "status_code", None)
            if hasattr(error, "response") and hasattr(error.response, "status_code"):
                status_code = error.response.status_code

            # Try to extract status code from error message
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
            # Reset status if it was cooling
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
