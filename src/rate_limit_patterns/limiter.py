"""Rate limiter facade providing a simple interface for rate limiting."""

from __future__ import annotations

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult


class RateLimiter:
    """Facade providing a simple interface for rate limiting operations.

    This class wraps a backend implementation and provides a clean API
    for checking, allowing, and resetting rate limits with optional key prefixing.

    Args:
        backend: The rate limit backend to use for storage and computation.
        config: The rate limit configuration to apply.
        key_prefix: Optional prefix to prepend to all keys for namespacing.
    """

    def __init__(
        self,
        *,
        backend: RateLimitBackend,
        config: RateLimitConfig,
        key_prefix: str = "",
    ) -> None:
        """Initialize the rate limiter.

        Args:
            backend: The rate limit backend to use.
            config: The rate limit configuration.
            key_prefix: Optional prefix for all keys.
        """
        self._backend = backend
        self._config = config
        self._key_prefix = key_prefix

    def _build_key(self, key: str) -> str:
        """Build the full key by prepending the key prefix if set.

        Args:
            key: The base key to build from.

        Returns:
            The full key with prefix applied if key_prefix is non-empty.
        """
        if self._key_prefix:
            return f"{self._key_prefix}{key}"
        return key

    async def check(self, key: str) -> RateLimitResult:
        """Check the rate limit for a key and increment the counter.

        Args:
            key: The unique identifier to check the rate limit for.

        Returns:
            A RateLimitResult indicating if the request is allowed and state.
        """
        full_key = self._build_key(key)
        return await self._backend.check_and_increment(full_key, self._config)

    async def allow(self, key: str) -> bool:
        """Check if a key is allowed without consuming resources.

        This is a convenience method that returns a simple boolean.

        Args:
            key: The unique identifier to check.

        Returns:
            True if the request is allowed, False otherwise.
        """
        result = await self.check(key)
        return result.allowed

    async def reset(self, key: str) -> None:
        """Reset the rate limit state for a key.

        Args:
            key: The unique identifier to reset.
        """
        full_key = self._build_key(key)
        await self._backend.reset(full_key)
