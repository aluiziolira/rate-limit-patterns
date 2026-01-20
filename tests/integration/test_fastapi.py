"""Integration tests for FastAPI dependency."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.middleware.fastapi import RateLimitDependency
from rate_limit_patterns.models import RateLimitConfig


class TestFastAPIDependency:
    """Tests for FastAPI rate limit dependency."""

    @pytest.fixture
    def app(self) -> FastAPI:
        """Create test FastAPI app."""
        app = FastAPI()
        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=3,
            period=60,
            burst_size=3,
        )

        rate_limit = RateLimitDependency(
            backend=backend,
            config=config,
        )

        @app.get("/limited")
        async def limited_endpoint(rate_limit_result=Depends(rate_limit)):
            return {"status": "ok", "remaining": rate_limit_result.remaining}

        return app

    def test_dependency_injection_works(self, app: FastAPI) -> None:
        """Dependency injects rate limit result."""
        client = TestClient(app)

        response = client.get("/limited")
        assert response.status_code == 200
        assert "remaining" in response.json()

    def test_returns_429_when_exceeded(self, app: FastAPI) -> None:
        """Returns 429 when limit exceeded."""
        client = TestClient(app)

        for _ in range(3):
            client.get("/limited")

        response = client.get("/limited")
        assert response.status_code == 429
