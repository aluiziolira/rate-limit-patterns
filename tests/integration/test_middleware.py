"""Integration tests for ASGI middleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.exceptions import RateLimitBackendUnavailableError
from rate_limit_patterns.middleware.asgi import RateLimitMiddleware
from rate_limit_patterns.models import RateLimitConfig


class TestASGIMiddleware:
    """Tests for ASGI middleware."""

    class _FailingBackend:
        async def check_and_increment(self, *_args, **_kwargs):
            raise RateLimitBackendUnavailableError("down")

    @pytest.fixture
    def app(self) -> Starlette:
        """Create test app with middleware."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=5,
            period=60,
            burst_size=5,
            cleanup_interval=0,
        )

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=lambda req: req.client.host if req.client else "unknown",
        )
        return app

    def test_allows_requests_under_limit(self, app: Starlette) -> None:
        """Requests under limit return 200."""
        client = TestClient(app)

        for _ in range(5):
            response = client.get("/")
            assert response.status_code == 200

    def test_returns_429_over_limit(self, app: Starlette) -> None:
        """Requests over limit return 429."""
        client = TestClient(app)

        # Exhaust limit
        for _ in range(5):
            client.get("/")

        # Next should be 429
        response = client.get("/")
        assert response.status_code == 429
        assert "X-RateLimit-Reset" in response.headers

    def test_includes_retry_after_header(self, app: Starlette) -> None:
        """429 response includes Retry-After header."""
        client = TestClient(app)

        for _ in range(5):
            client.get("/")

        response = client.get("/")
        assert "Retry-After" in response.headers

    def test_includes_rate_limit_headers(self, app: Starlette) -> None:
        """Response includes X-RateLimit-* headers."""
        client = TestClient(app)

        response = client.get("/")

        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_standard_header_style_for_200_and_429(self) -> None:
        """Standard RateLimit headers are emitted when configured."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
            cleanup_interval=0,
        )

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=lambda req: "user",
            header_style="standard",
        )

        client = TestClient(app)

        ok_response = client.get("/")
        assert ok_response.status_code == 200
        assert "RateLimit-Limit" in ok_response.headers
        assert "RateLimit-Remaining" in ok_response.headers
        assert "RateLimit-Reset" in ok_response.headers
        assert "X-RateLimit-Limit" not in ok_response.headers

        denied_response = client.get("/")
        assert denied_response.status_code == 429
        assert "RateLimit-Limit" in denied_response.headers
        assert "RateLimit-Remaining" in denied_response.headers
        assert "RateLimit-Reset" in denied_response.headers
        assert "X-RateLimit-Limit" not in denied_response.headers

    def test_custom_key_extractor_isolates_clients(self) -> None:
        """Custom key extractors isolate different callers."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
            cleanup_interval=0,
        )

        def key_extractor(request):
            return request.headers.get("X-Client-Id", "unknown")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=key_extractor,
        )

        client = TestClient(app)

        response_a = client.get("/", headers={"X-Client-Id": "a"})
        response_b = client.get("/", headers={"X-Client-Id": "b"})

        assert response_a.status_code == 200
        assert response_b.status_code == 200

    def test_event_hook_emits_allowed_and_denied(self) -> None:
        """Event hook fires for allowed and denied checks."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
            cleanup_interval=0,
        )
        events = []

        def hook(event):
            events.append(event)

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=lambda req: "user",
            event_hook=hook,
        )

        client = TestClient(app)
        client.get("/")
        client.get("/")

        assert len(events) == 2
        assert events[0].allowed is True
        assert events[1].allowed is False
        assert events[0].backend_type == "LocalBackend"
        assert events[0].latency_ms >= 0

    def test_event_hook_failure_logged(self) -> None:
        """Event hook failures can be logged without breaking requests."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
            cleanup_interval=0,
        )

        def failing_hook(_event):
            raise RuntimeError("boom")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=lambda req: "user",
            event_hook=failing_hook,
            event_hook_failure="log",
        )

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200

    def test_event_hook_failure_raise_bubbles(self) -> None:
        """Event hook failures propagate when configured to raise."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
            cleanup_interval=0,
        )

        def failing_hook(_event):
            raise RuntimeError("boom")

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=lambda req: "user",
            event_hook=failing_hook,
            event_hook_failure="raise",
        )

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/")

        assert response.status_code == 500

    def test_fail_closed_returns_503(self) -> None:
        """fail_closed returns 503 on backend errors."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = self._FailingBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
        )

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=lambda req: "user",
            failure_mode="fail_closed",
        )

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 503

    def test_fail_open_allows_request(self) -> None:
        """fail_open allows requests when backend is unavailable."""

        async def homepage(request):
            return JSONResponse({"status": "ok"})

        backend = self._FailingBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
        )

        app = Starlette(routes=[Route("/", homepage)])
        app.add_middleware(
            RateLimitMiddleware,
            backend=backend,
            config=config,
            key_extractor=lambda req: "user",
            failure_mode="fail_open",
        )

        client = TestClient(app)
        response = client.get("/")

        assert response.status_code == 200
        assert "X-RateLimit-Limit" not in response.headers
