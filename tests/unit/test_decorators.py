"""Unit tests for rate_limit decorator."""

import pytest

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.decorators import rate_limit
from rate_limit_patterns.exceptions import RateLimitExceeded


class TestRateLimitDecorator:
    """Tests for @rate_limit decorator."""

    @pytest.fixture
    def backend(self) -> LocalBackend:
        return LocalBackend()

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
