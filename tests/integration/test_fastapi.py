"""Integration tests for FastAPI dependency."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.exceptions import RateLimitBackendUnavailableError
from rate_limit_patterns.middleware.fastapi import RateLimitDependency
from rate_limit_patterns.models import RateLimitConfig


class TestFastAPIDependency:
    """Tests for FastAPI rate limit dependency."""

    class _FailingBackend:
        async def check_and_increment(self, *_args, **_kwargs):
            raise RateLimitBackendUnavailableError("down")

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
            cleanup_interval=0,
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
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_standard_header_style_for_200_and_429(self) -> None:
        """Standard RateLimit headers are emitted when configured."""
        app = FastAPI()
        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=60,
            burst_size=1,
            cleanup_interval=0,
        )

        rate_limit = RateLimitDependency(
            backend=backend,
            config=config,
            header_style="standard",
        )

        @app.get("/limited")
        async def limited_endpoint(rate_limit_result=Depends(rate_limit)):
            return {"status": "ok", "remaining": rate_limit_result.remaining}

        client = TestClient(app)

        ok_response = client.get("/limited")
        assert ok_response.status_code == 200
        assert "RateLimit-Limit" in ok_response.headers
        assert "RateLimit-Remaining" in ok_response.headers
        assert "RateLimit-Reset" in ok_response.headers
        assert "X-RateLimit-Limit" not in ok_response.headers

        denied_response = client.get("/limited")
        assert denied_response.status_code == 429
        assert "RateLimit-Limit" in denied_response.headers
        assert "RateLimit-Remaining" in denied_response.headers
        assert "RateLimit-Reset" in denied_response.headers
        assert "X-RateLimit-Limit" not in denied_response.headers

    def test_returns_429_when_exceeded(self, app: FastAPI) -> None:
        """Returns 429 when limit exceeded."""
        client = TestClient(app)

        for _ in range(3):
            client.get("/limited")

        response = client.get("/limited")
        assert response.status_code == 429
        assert "Retry-After" in response.headers
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        assert "X-RateLimit-Reset" in response.headers

    def test_event_hook_emits_allowed_and_denied(self) -> None:
        """Event hook fires for allowed and denied checks."""
        app = FastAPI()
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

        rate_limit = RateLimitDependency(
            backend=backend,
            config=config,
            event_hook=hook,
        )

        @app.get("/limited")
        async def limited_endpoint(rate_limit_result=Depends(rate_limit)):
            return {"status": "ok", "remaining": rate_limit_result.remaining}

        client = TestClient(app)
        client.get("/limited")
        client.get("/limited")

        assert len(events) == 2
        assert events[0].allowed is True
        assert events[1].allowed is False
        assert events[0].backend_type == "LocalBackend"

    def test_event_hook_failure_logged(self) -> None:
        """Event hook failures can be logged without breaking requests."""
        app = FastAPI()
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

        rate_limit = RateLimitDependency(
            backend=backend,
            config=config,
            event_hook=failing_hook,
            event_hook_failure="log",
        )

        @app.get("/limited")
        async def limited_endpoint(rate_limit_result=Depends(rate_limit)):
            return {"status": "ok", "remaining": rate_limit_result.remaining}

        client = TestClient(app)
        response = client.get("/limited")

        assert response.status_code == 200

    def test_event_hook_failure_raise_bubbles(self) -> None:
        """Event hook failures propagate when configured to raise."""
        app = FastAPI()
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

        rate_limit = RateLimitDependency(
            backend=backend,
            config=config,
            event_hook=failing_hook,
            event_hook_failure="raise",
        )

        @app.get("/limited")
        async def limited_endpoint(rate_limit_result=Depends(rate_limit)):
            return {"status": "ok", "remaining": rate_limit_result.remaining}

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/limited")

        assert response.status_code == 500

    def test_fail_closed_returns_503(self) -> None:
        """fail_closed returns 503 on backend errors."""
        app = FastAPI()
        backend = self._FailingBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=3,
            period=60,
            burst_size=3,
        )

        rate_limit = RateLimitDependency(
            backend=backend,
            config=config,
            failure_mode="fail_closed",
        )

        @app.get("/limited")
        async def limited_endpoint(rate_limit_result=Depends(rate_limit)):
            return {"status": "ok", "remaining": rate_limit_result.remaining}

        client = TestClient(app)
        response = client.get("/limited")

        assert response.status_code == 503

    def test_fail_open_allows_request(self) -> None:
        """fail_open allows requests when backend is unavailable."""
        app = FastAPI()
        backend = self._FailingBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=3,
            period=60,
            burst_size=3,
        )

        rate_limit = RateLimitDependency(
            backend=backend,
            config=config,
            failure_mode="fail_open",
        )

        @app.get("/limited")
        async def limited_endpoint(rate_limit_result=Depends(rate_limit)):
            return {"status": "ok", "remaining": rate_limit_result.remaining}

        client = TestClient(app)
        response = client.get("/limited")

        assert response.status_code == 200
        assert response.json()["remaining"] == 3
        assert "X-RateLimit-Limit" not in response.headers
