"""API error types for OpenCortex."""

from __future__ import annotations


class OpenCortexApiError(RuntimeError):
    """Base class for upstream API failures."""


class AuthenticationFailure(OpenCortexApiError):
    """Raised when the upstream service rejects the provided credentials."""


class RateLimitFailure(OpenCortexApiError):
    """Raised when the upstream service rejects the request due to rate limits."""


class RequestFailure(OpenCortexApiError):
    """Raised for generic request or transport failures."""
