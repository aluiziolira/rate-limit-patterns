"""Custom exceptions for rate limiting."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rate_limit_patterns.models import RateLimitResult


class RateLimitExceeded(Exception):  # noqa: N818
    """Exception raised when a rate limit is exceeded.

    Attributes:
        retry_after: Seconds until the client can retry.
        result: The RateLimitResult that caused this exception, if available.
    """

    def __init__(
        self,
        retry_after: int,
        message: str | None = None,
        *,
        result: RateLimitResult | None = None,
    ) -> None:
        """Initialize the RateLimitExceeded exception.

        Args:
            retry_after: Seconds until the client can retry.
            message: Optional custom error message.
            result: Optional RateLimitResult that caused this exception.
        """
        self.retry_after = retry_after
        self.result = result
        if message is None:
            message = f"Rate limit exceeded. Retry after {retry_after} seconds."
        super().__init__(message)


class RateLimitBackendError(Exception):
    """Base class for backend errors."""


class RateLimitBackendUnavailableError(RateLimitBackendError):
    """Raised when a backend cannot be reached or times out."""


class RateLimitBackendConfigurationError(RateLimitBackendError):
    """Raised when backend configuration or initialization is invalid."""
