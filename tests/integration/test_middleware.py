"""Integration tests for ASGI middleware."""

import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.middleware.asgi import RateLimitMiddleware
from rate_limit_patterns.models import RateLimitConfig


class TestASGIMiddleware:
    """Tests for ASGI middleware."""

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
