"""Rate limiting decorators."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.exceptions import RateLimitExceeded
from rate_limit_patterns.models import RateLimitConfig

T = TypeVar("T")


def rate_limit(
    *,
    backend: RateLimitBackend,
    limit: int,
    period: int,
    key: str,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator to apply rate limiting to an async function.

    Args:
        backend: The rate limit backend to use for checking limits.
        limit: Maximum number of calls allowed within the period.
        period: Time window in seconds for the rate limit.
        key: Either a kwarg name to extract from the function call,
             or a static key string if the kwarg is not present.

    Returns:
        A decorator that enforces rate limiting on the decorated function.
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            effective_key = str(kwargs[key]) if key in kwargs else key

            # Build rate limit config with token_bucket algorithm
            config = RateLimitConfig(
                algorithm="token_bucket",
                limit=limit,
                period=period,
                burst_size=limit,
            )

            # Check and increment the rate limit
            result = await backend.check_and_increment(effective_key, config)

            if result.allowed:
                # Call the wrapped function and return its result
                return await func(*args, **kwargs)
            else:
                # Rate limit exceeded - raise exception
                retry_after = result.retry_after if result.retry_after is not None else 1
                raise RateLimitExceeded(
                    retry_after=retry_after,
                    result=result,
                )

        return wrapper

    return decorator
