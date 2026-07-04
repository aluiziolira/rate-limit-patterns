"""FastAPI dependency for rate limiting."""

import time
from collections.abc import Callable

from fastapi import HTTPException, Response
from starlette.requests import Request

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.exceptions import RateLimitBackendUnavailableError
from rate_limit_patterns.middleware._shared import (
    EventHookFailure,
    FailureMode,
    emit_rate_limit_event,
)
from rate_limit_patterns.middleware.headers import HeaderStyle, build_rate_limit_headers
from rate_limit_patterns.models import RateLimitConfig, RateLimitEvent, RateLimitResult


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
        failure_mode: FailureMode = "fail_closed",
        event_hook: Callable[[RateLimitEvent], None] | None = None,
        event_hook_failure: EventHookFailure = "raise",
        header_style: HeaderStyle = "x",
    ) -> None:
        """Initialize the rate limit dependency."""
        self._backend = backend
        self._config = config
        self._key_extractor = key_extractor or _default_key_extractor
        self._failure_mode = failure_mode
        self._event_hook = event_hook
        self._event_hook_failure = event_hook_failure
        self._header_style = header_style

    async def __call__(
        self,
        request: Request,
        response: Response,
    ) -> RateLimitResult:
        """Check the rate limit for the incoming request."""
        key = self._key_extractor(request)
        start = time.perf_counter()
        try:
            result = await self._backend.check_and_increment(key, self._config)
        except RateLimitBackendUnavailableError:
            if self._failure_mode == "fail_open":
                return RateLimitResult(
                    allowed=True,
                    remaining=self._config.limit,
                    limit=self._config.limit,
                )
            raise HTTPException(
                status_code=503,
                detail="Rate limit backend unavailable",
            ) from None
        latency_ms = (time.perf_counter() - start) * 1000
        self._emit_event(result, latency_ms)

        headers = build_rate_limit_headers(result, header_style=self._header_style)
        if not result.allowed:
            raise HTTPException(
                status_code=429,
                detail="Rate limit exceeded",
                headers=headers,
            )

        response.headers.update(headers)

        return result

    def _emit_event(self, result: RateLimitResult, latency_ms: float) -> None:
        emit_rate_limit_event(
            self._event_hook,
            self._event_hook_failure,
            algorithm=self._config.algorithm,
            result=result,
            backend_type=type(self._backend).__name__,
            latency_ms=latency_ms,
        )


def create_rate_limit_dependency(
    *,
    backend: RateLimitBackend,
    config: RateLimitConfig,
    key_extractor: Callable[[Request], str] | None = None,
    failure_mode: FailureMode = "fail_closed",
    event_hook: Callable[[RateLimitEvent], None] | None = None,
    event_hook_failure: EventHookFailure = "raise",
    header_style: HeaderStyle = "x",
) -> RateLimitDependency:
    """Factory function to create a rate limit dependency."""
    return RateLimitDependency(
        backend=backend,
        config=config,
        key_extractor=key_extractor,
        failure_mode=failure_mode,
        event_hook=event_hook,
        event_hook_failure=event_hook_failure,
        header_style=header_style,
    )
