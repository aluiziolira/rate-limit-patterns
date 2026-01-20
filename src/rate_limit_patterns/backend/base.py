"""Backend protocol for rate limit implementations."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rate_limit_patterns.models import RateLimitConfig, RateLimitResult


@runtime_checkable
class RateLimitBackend(Protocol):
    """Protocol for rate limit backend implementations.

    Implementations must provide async methods for checking rate limits,
    resetting state, and exposing metrics.
    """

    async def check_and_increment(
        self, key: str, config: RateLimitConfig
    ) -> RateLimitResult:
        """Check and increment the rate limit counter for a key.

        Args:
            key: Unique identifier for the rate limit (e.g., user ID, IP).
            config: Rate limit configuration to apply.

        Returns:
            RateLimitResult indicating if the request is allowed and state.
        """
        ...

    async def reset(self, key: str) -> None:
        """Reset the rate limit state for a key.

        Args:
            key: Unique identifier for the rate limit to reset.
        """
        ...

    async def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key.

        Args:
            key: Unique identifier to get metrics for.

        Returns:
            Dictionary containing metrics for the key.
        """
        ...
