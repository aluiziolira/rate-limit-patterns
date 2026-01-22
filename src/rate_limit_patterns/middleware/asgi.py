"""ASGI middleware for rate limiting."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, Literal

from starlette.requests import Request
from starlette.responses import Response

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.exceptions import RateLimitBackendUnavailableError
from rate_limit_patterns.middleware.headers import (
    HeaderStyle,
    build_rate_limit_header_bytes,
    build_rate_limit_headers,
)
from rate_limit_patterns.models import RateLimitConfig, RateLimitEvent, RateLimitResult

FailureMode = Literal["fail_closed", "fail_open"]
EventHookFailure = Literal["raise", "log"]

logger = logging.getLogger(__name__)

ASGIApp = Callable[[dict[str, Any], Any, Any], Any]
Scope = dict[str, Any]
Receive = Callable[[], Any]
Send = Callable[[Any], Any]


class RateLimitMiddleware:
    """ASGI middleware for rate limiting requests.

    This middleware implements ASGI3 and wraps Starlette applications to enforce
    rate limiting based on a configurable backend and key extraction strategy.

    Attributes:
        app: The downstream ASGI application to wrap.
        backend: The rate limit backend to use for checking limits.
        config: The rate limit configuration to apply.
        key_extractor: Callable to extract rate limit key from a request.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        backend: RateLimitBackend,
        config: RateLimitConfig,
        key_extractor: Callable[[Request], str],
        failure_mode: FailureMode = "fail_closed",
        event_hook: Callable[[RateLimitEvent], None] | None = None,
        event_hook_failure: EventHookFailure = "raise",
        header_style: HeaderStyle = "x",
    ) -> None:
        """Initialize the rate limit middleware.

        Args:
            app: The downstream ASGI application.
            backend: Rate limit backend for checking limits.
            config: Rate limit configuration.
            key_extractor: Callable that extracts a rate limit key from a request.
            failure_mode: Behavior when backend is unavailable.
            event_hook: Optional callback for observability events.
            event_hook_failure: Behavior when event_hook raises.
            header_style: Which rate-limit header style to emit.
        """
        self.app = app
        self.backend = backend
        self.config = config
        self.key_extractor = key_extractor
        self.failure_mode = failure_mode
        self._event_hook = event_hook
        self._event_hook_failure = event_hook_failure
        self._header_style = header_style

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle an ASGI request.

        For non-HTTP scopes, the downstream app is called directly.
        For HTTP scopes, rate limiting is applied before passing to the app.

        Args:
            scope: ASGI scope dictionary.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        key = self.key_extractor(request)
        start = time.perf_counter()
        try:
            result = await self.backend.check_and_increment(key, self.config)
        except RateLimitBackendUnavailableError:
            if self.failure_mode == "fail_open":
                await self.app(scope, receive, send)
                return
            await self._send_backend_unavailable_response(scope, receive, send)
            return
        latency_ms = (time.perf_counter() - start) * 1000
        self._emit_event(result, latency_ms)

        if not result.allowed:
            await self._send_rate_limit_response(scope, receive, send, result)
            return

        await self._send_through_request(scope, receive, send, result)

    async def _send_rate_limit_response(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        result: RateLimitResult,
    ) -> None:
        """Send a 429 rate limit exceeded response.

        Args:
            scope: ASGI scope dictionary.
            receive: ASGI receive callable.
            result: The rate limit check result.
            send: ASGI send callable.
        """
        response = Response(
            content="Rate limit exceeded",
            status_code=429,
            headers=build_rate_limit_headers(result, header_style=self._header_style),
        )
        await response(scope=scope, receive=receive, send=send)

    async def _send_backend_unavailable_response(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        response = Response(
            content="Rate limit backend unavailable",
            status_code=503,
        )
        await response(scope=scope, receive=receive, send=send)

    def _emit_event(self, result: RateLimitResult, latency_ms: float) -> None:
        if self._event_hook is None:
            return
        event = RateLimitEvent(
            algorithm=self.config.algorithm,
            allowed=result.allowed,
            remaining=result.remaining,
            retry_after=result.retry_after,
            backend_type=type(self.backend).__name__,
            latency_ms=latency_ms,
        )
        if self._event_hook_failure == "raise":
            self._event_hook(event)
            return
        try:
            self._event_hook(event)
        except Exception:
            logger.exception("Rate limit event hook failed")

    async def _send_through_request(
        self, scope: Scope, receive: Receive, send: Send, result: RateLimitResult
    ) -> None:
        """Send request through to app with wrapped send for headers.

        Args:
            scope: ASGI scope dictionary.
            receive: ASGI receive callable.
            send: ASGI send callable.
            result: The rate limit check result.
        """
        headers_sent = False

        async def wrapped_send(message: dict[str, Any]) -> None:
            nonlocal headers_sent
            if message["type"] == "http.response.start" and not headers_sent:
                headers = list(message.get("headers", []))
                headers.extend(
                    build_rate_limit_header_bytes(result, header_style=self._header_style)
                )
                message = {**message, "headers": headers}
                headers_sent = True
            await send(message)

        await self.app(scope, receive, wrapped_send)
