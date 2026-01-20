"""FastAPI dependency for rate limiting."""

from collections.abc import Callable

from fastapi import HTTPException
from starlette.requests import Request

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult


def _default_key_extractor(request: Request) -> str:
    """Default key extractor using client host."""
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


class RateLimitDependency:
    """FastAPI dependency for enforcing rate limits on endpoints."""

    def __init__(
        self,
        *,
        backend: RateLimitBackend,
        config: RateLimitConfig,
        key_extractor: Callable[[Request], str] | None = None,
    ) -> None:
        """Initialize the rate limit dependency."""
        self._backend = backend
        self._config = config
        self._key_extractor = key_extractor or _default_key_extractor

    async def __call__(self, request: Request) -> RateLimitResult:
        """Check the rate limit for the incoming request."""
        key = self._key_extractor(request)
        result = await self._backend.check_and_increment(key, self._config)

        if not result.allowed:
            headers: dict[str, str] = {
                "X-RateLimit-Limit": str(result.limit),
                "X-RateLimit-Remaining": "0",
            }
            if result.retry_after is not None:
                headers["Retry-After"] = str(result.retry_after)

            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers=headers,
            )

        return result


def create_rate_limit_dependency(
    *,
    backend: RateLimitBackend,
    config: RateLimitConfig,
    key_extractor: Callable[[Request], str] | None = None,
) -> RateLimitDependency:
    """Factory function to create a rate limit dependency."""
    return RateLimitDependency(
        backend=backend,
        config=config,
        key_extractor=key_extractor,
    )
