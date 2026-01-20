"""ASGI middleware for rate limiting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from starlette.requests import Request
from starlette.responses import Response

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

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
    ) -> None:
        """Initialize the rate limit middleware.

        Args:
            app: The downstream ASGI application.
            backend: Rate limit backend for checking limits.
            config: Rate limit configuration.
            key_extractor: Callable that extracts a rate limit key from a request.
        """
        self.app = app
        self.backend = backend
        self.config = config
        self.key_extractor = key_extractor

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
        result = await self.backend.check_and_increment(key, self.config)

        if not result.allowed:
            await self._send_rate_limit_response(result, send)
            return

        await self._send_through_request(scope, receive, send, result)

    async def _send_rate_limit_response(self, result: RateLimitResult, send: Send) -> None:
        """Send a 429 rate limit exceeded response.

        Args:
            result: The rate limit check result.
            send: ASGI send callable.
        """
        headers: list[tuple[str, str]] = [
            ("X-RateLimit-Limit", str(result.limit)),
            ("X-RateLimit-Remaining", str(result.remaining)),
        ]
        if result.retry_after is not None:
            headers.append(("Retry-After", str(result.retry_after)))

        response = Response(
            content="Rate limit exceeded",
            status_code=429,
            headers=dict(headers),
        )

        async def receive() -> dict[str, Any]:
            return {"type": "http.request", "body": b"", "more_body": False}

        await response(
            scope={"type": "http", "method": "GET", "path": "/"}, receive=receive, send=send
        )

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
                    [
                        (b"X-RateLimit-Limit", str(result.limit).encode()),
                        (b"X-RateLimit-Remaining", str(result.remaining).encode()),
                    ]
                )
                message = {**message, "headers": headers}
                headers_sent = True
            await send(message)

        await self.app(scope, receive, wrapped_send)
