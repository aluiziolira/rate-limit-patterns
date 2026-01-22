"""Unit tests for RateLimiter facade."""

from typing import Any

import pytest

from rate_limit_patterns import RateLimitConfig, RateLimiter, RateLimitResult
from rate_limit_patterns.backend.local import LocalBackend


class PrefixedBackend:
    """Backend stub exposing a key prefix to validate guardrails."""

    key_prefix = "api:"

    async def check_and_increment(
        self, key: str, config: RateLimitConfig, *, now: float | None = None
    ) -> RateLimitResult:
        raise NotImplementedError

    async def reset(self, key: str) -> None:
        raise NotImplementedError

    async def get_metrics(self, key: str) -> dict[str, Any]:
        raise NotImplementedError


class LifecycleBackend:
    """Backend stub exposing lifecycle hooks."""

    def __init__(self) -> None:
        self.initialized = False
        self.closed = False

    async def initialize(self) -> None:
        self.initialized = True

    async def close(self) -> None:
        self.closed = True

    async def check_and_increment(
        self, key: str, config: RateLimitConfig, *, now: float | None = None
    ) -> RateLimitResult:
        return RateLimitResult(
            allowed=True,
            remaining=1,
            limit=config.limit,
            reset_at=0.0,
            request_count=0,
        )

    async def reset(self, key: str) -> None:
        raise NotImplementedError

    async def get_metrics(self, key: str) -> dict[str, Any]:
        raise NotImplementedError


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
            cleanup_interval=0,
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

    def test_rejects_double_prefix_configuration(self, config: RateLimitConfig) -> None:
        """RateLimiter rejects key_prefix when backend already prefixes."""
        backend = PrefixedBackend()

        with pytest.raises(ValueError, match="key_prefix"):
            RateLimiter(backend=backend, config=config, key_prefix="api:")

    @pytest.mark.asyncio
    async def test_allow_convenience_method(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """allow() returns simple bool."""
        limiter = RateLimiter(backend=backend, config=config)

        allowed = await limiter.allow("user:123")

        assert allowed is True

    @pytest.mark.asyncio
    async def test_reset_clears_state(self, backend: LocalBackend, config: RateLimitConfig) -> None:
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

    @pytest.mark.asyncio
    async def test_context_manager_calls_lifecycle(self, config: RateLimitConfig) -> None:
        """Context manager triggers backend lifecycle hooks."""
        backend = LifecycleBackend()
        limiter = RateLimiter(backend=backend, config=config)

        async with limiter:
            assert backend.initialized is True

        assert backend.closed is True
