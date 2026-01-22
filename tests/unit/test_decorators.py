"""Unit tests for rate_limit decorator."""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.decorators import rate_limit
from rate_limit_patterns.exceptions import RateLimitExceeded
from rate_limit_patterns.models import RateLimitResult


class TestRateLimitDecorator:
    """Tests for @rate_limit decorator."""

    @pytest_asyncio.fixture
    async def backend(self) -> AsyncGenerator[LocalBackend, None]:
        backend = LocalBackend()
        yield backend
        await backend.close()

    @pytest.mark.asyncio
    async def test_allows_calls_under_limit(self, backend: LocalBackend) -> None:
        """Decorated function works under limit."""

        @rate_limit(backend=backend, limit=5, period=60, key="test")
        async def my_function():
            return "success"

        for _ in range(5):
            result = await my_function()
            assert result == "success"

    @pytest.mark.asyncio
    async def test_raises_over_limit(self, backend: LocalBackend) -> None:
        """Decorated function raises RateLimitExceeded over limit."""

        @rate_limit(backend=backend, limit=2, period=60, key="test2")
        async def my_function():
            return "success"

        await my_function()
        await my_function()

        with pytest.raises(RateLimitExceeded) as exc_info:
            await my_function()

        assert exc_info.value.retry_after > 0

    @pytest.mark.asyncio
    async def test_key_from_argument(self, backend: LocalBackend) -> None:
        """Key extracted from function argument."""

        @rate_limit(backend=backend, limit=2, period=60, key="user_id")
        async def my_function(user_id: str):
            return f"hello {user_id}"

        # User 1: 2 calls allowed
        await my_function(user_id="user1")
        await my_function(user_id="user1")

        # User 2: independent limit
        result = await my_function(user_id="user2")
        assert result == "hello user2"

    @pytest.mark.asyncio
    async def test_key_func_overrides_key_lookup(self, backend: LocalBackend) -> None:
        """key_func is used to derive the effective key."""

        @rate_limit(
            backend=backend,
            limit=1,
            period=60,
            key="ignored",
            key_func=lambda user_id: f"user:{user_id}",
        )
        async def my_function(user_id: str):
            return f"hello {user_id}"

        result1 = await my_function("user1")
        result2 = await my_function("user2")

        assert result1 == "hello user1"
        assert result2 == "hello user2"

    @pytest.mark.asyncio
    async def test_algorithm_override_is_applied(self) -> None:
        """Custom algorithm selection is passed to the backend."""

        class CaptureBackend:
            def __init__(self) -> None:
                self.algorithms: list[str] = []

            async def check_and_increment(self, _key, config, *, now=None):
                self.algorithms.append(config.algorithm)
                return RateLimitResult(
                    allowed=True,
                    remaining=config.limit,
                    limit=config.limit,
                )

        backend = CaptureBackend()

        @rate_limit(
            backend=backend,
            limit=5,
            period=60,
            key="static",
            algorithm="leaky_bucket",
        )
        async def my_function():
            return "ok"

        result = await my_function()

        assert result == "ok"
        assert backend.algorithms == ["leaky_bucket"]

    @pytest.mark.asyncio
    async def test_defaults_preserve_previous_behavior(self) -> None:
        """Decorator defaults to token_bucket when not specified."""

        class CaptureBackend:
            def __init__(self) -> None:
                self.algorithms: list[str] = []

            async def check_and_increment(self, _key, config, *, now=None):
                self.algorithms.append(config.algorithm)
                return RateLimitResult(
                    allowed=True,
                    remaining=config.limit,
                    limit=config.limit,
                )

        backend = CaptureBackend()

        @rate_limit(backend=backend, limit=1, period=60, key="static")
        async def my_function():
            return "ok"

        await my_function()

        assert backend.algorithms == ["token_bucket"]
