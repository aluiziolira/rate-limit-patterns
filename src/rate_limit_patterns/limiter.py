"""Rate limiter facade providing a simple interface for rate limiting."""

from __future__ import annotations

import inspect
from types import TracebackType

from rate_limit_patterns.backend.base import RateLimitBackend, SyncRateLimitBackend
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult


def _validate_key_prefix(backend: object, key_prefix: str) -> None:
    """Reject prefixing on both the limiter and its backend at once."""
    backend_prefix = getattr(backend, "key_prefix", "")
    if isinstance(backend_prefix, str) and backend_prefix and key_prefix:
        raise ValueError("Configure key_prefix on either RateLimiter or backend, not both.")


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
            key_prefix: Optional prefix for all keys (do not set if backend prefixes).
        """
        _validate_key_prefix(backend, key_prefix)
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

    async def __aenter__(self) -> RateLimiter:
        initializer = getattr(self._backend, "initialize", None)
        if initializer is not None:
            result = initializer()
            if inspect.isawaitable(result):
                await result
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        closer = getattr(self._backend, "close", None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                await result

    async def allow(self, key: str) -> bool:
        """Check if a key is allowed and consume capacity.

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


class SyncRateLimiter:
    """Facade providing a synchronous interface for rate limiting operations."""

    def __init__(
        self,
        *,
        backend: SyncRateLimitBackend,
        config: RateLimitConfig,
        key_prefix: str = "",
    ) -> None:
        """Initialize the synchronous rate limiter."""
        _validate_key_prefix(backend, key_prefix)
        self._backend = backend
        self._config = config
        self._key_prefix = key_prefix

    def _build_key(self, key: str) -> str:
        if self._key_prefix:
            return f"{self._key_prefix}{key}"
        return key

    def check(self, key: str) -> RateLimitResult:
        """Check the rate limit for a key and increment the counter."""
        full_key = self._build_key(key)
        return self._backend.check_and_increment(full_key, self._config)

    def allow(self, key: str) -> bool:
        """Check if a key is allowed and consume capacity."""
        result = self.check(key)
        return result.allowed

    def reset(self, key: str) -> None:
        """Reset the rate limit state for a key."""
        full_key = self._build_key(key)
        self._backend.reset(full_key)

    def __enter__(self) -> SyncRateLimiter:
        initializer = getattr(self._backend, "initialize", None)
        if initializer is not None:
            result = initializer()
            if inspect.isawaitable(result):
                raise RuntimeError(
                    "SyncRateLimiter backend initialize() returned awaitable; "
                    "use RateLimiter instead."
                )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        closer = getattr(self._backend, "close", None)
        if closer is not None:
            result = closer()
            if inspect.isawaitable(result):
                raise RuntimeError(
                    "SyncRateLimiter backend close() returned awaitable; use RateLimiter instead."
                )
