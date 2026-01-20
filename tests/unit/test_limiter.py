"""Unit tests for RateLimiter facade."""

import pytest

from rate_limit_patterns import RateLimitConfig, RateLimiter
from rate_limit_patterns.backend.local import LocalBackend


class TestRateLimiter:
    """Tests for RateLimiter facade."""

    @pytest.fixture
    def backend(self) -> LocalBackend:
        return LocalBackend()

    @pytest.fixture
    def config(self) -> RateLimitConfig:
        return RateLimitConfig(
            algorithm="token_bucket",
            limit=100,
            period=60,
            burst_size=100,
        )

    @pytest.mark.asyncio
    async def test_check_returns_result(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """check() returns RateLimitResult."""
        limiter = RateLimiter(backend=backend, config=config)

        result = await limiter.check("user:123")

        assert result.allowed is True
        assert result.remaining == 99

    @pytest.mark.asyncio
    async def test_check_with_custom_key_builder(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """RateLimiter supports custom key builders."""
        limiter = RateLimiter(
            backend=backend,
            config=config,
            key_prefix="api:",
        )

        result = await limiter.check("user:123")

        # Should use prefixed key internally
        metrics = await backend.get_metrics("api:user:123")
        assert "tokens" in metrics

    @pytest.mark.asyncio
    async def test_allow_convenience_method(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """allow() returns simple bool."""
        limiter = RateLimiter(backend=backend, config=config)

        allowed = await limiter.allow("user:123")

        assert allowed is True

    @pytest.mark.asyncio
    async def test_reset_clears_state(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """reset() clears limiter state."""
        limiter = RateLimiter(backend=backend, config=config)

        # Use some capacity
        for _ in range(50):
            await limiter.check("user:123")

        # Reset
        await limiter.reset("user:123")

        # Should have full capacity
        result = await limiter.check("user:123")
        assert result.remaining == 99
