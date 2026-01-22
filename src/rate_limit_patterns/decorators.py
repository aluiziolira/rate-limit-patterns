"""Rate limiting decorators."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.exceptions import RateLimitExceeded
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig

T = TypeVar("T")


def rate_limit(
    *,
    backend: RateLimitBackend,
    limit: int,
    period: int,
    key: str,
    key_func: Callable[..., str] | None = None,
    algorithm: AlgorithmType = "token_bucket",
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorator to apply rate limiting to an async function.

    Args:
        backend: The rate limit backend to use for checking limits.
        limit: Maximum number of calls allowed within the period.
        period: Time window in seconds for the rate limit.
        key: Either a kwarg name to extract from the function call,
             or a static key string if the kwarg is not present.
        key_func: Optional function to derive the rate-limit key from args/kwargs.
        algorithm: Algorithm name to use for the rate limit.

    Returns:
        A decorator that enforces rate limiting on the decorated function.

    Examples:
        Use a key extractor for composite arguments:

        @rate_limit(
            backend=backend,
            limit=10,
            period=60,
            key="unused",
            key_func=lambda user_id, *_: f"user:{user_id}",
        )
        async def handler(user_id: str, payload: dict[str, Any]) -> None:
            ...

        Override the algorithm explicitly:

        @rate_limit(
            backend=backend,
            limit=5,
            period=60,
            key="user_id",
            algorithm="leaky_bucket",
        )
        async def handler(user_id: str) -> None:
            ...
    """

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            if key_func is not None:
                effective_key = key_func(*args, **kwargs)
            else:
                effective_key = str(kwargs[key]) if key in kwargs else key

            # Build rate limit config
            config = RateLimitConfig(
                algorithm=algorithm,
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
