"""Integration tests for Redis backend (skipped unless REDIS_URL is set)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio

from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.models import RateLimitConfig

pytestmark = pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="REDIS_URL not set")


@pytest_asyncio.fixture
async def backend(redis_url: str) -> AsyncGenerator[RedisBackend, None]:
    """Create and initialize a Redis backend for testing."""
    backend = RedisBackend(url=redis_url, key_prefix="test:")
    await backend.initialize()
    yield backend
    await backend.close()


@pytest.fixture
def config() -> RateLimitConfig:
    """Create a token bucket configuration for testing."""
    return RateLimitConfig(
        algorithm="token_bucket",
        limit=10,
        period=60,
        burst_size=10,
    )


@pytest.fixture
def sliding_window_config() -> RateLimitConfig:
    """Create a sliding window configuration for testing."""
    return RateLimitConfig(
        algorithm="sliding_window",
        limit=3,
        period=2,
    )


@pytest.fixture
def leaky_bucket_config() -> RateLimitConfig:
    """Create a leaky bucket configuration for testing."""
    return RateLimitConfig(
        algorithm="leaky_bucket",
        limit=2,
        period=2,
    )


@pytest.mark.asyncio
async def test_rate_limiting_works(backend: RedisBackend, config: RateLimitConfig) -> None:
    """Test that rate limiting works correctly with real Redis."""
    key = "test_user"

    # First request should be allowed
    result = await backend.check_and_increment(key, config)
    assert result.allowed is True
    assert result.remaining == config.limit - 1

    # Make more requests up to the limit
    for i in range(config.limit - 1):
        result = await backend.check_and_increment(key, config)
        assert result.allowed is True

    # Next request should be denied (rate limited)
    result = await backend.check_and_increment(key, config)
    assert result.allowed is False
    assert result.remaining == 0

    # Reset and verify we can make requests again
    await backend.reset(key)
    result = await backend.check_and_increment(key, config)
    assert result.allowed is True
    assert result.remaining == config.limit - 1


@pytest.mark.asyncio
async def test_lazy_initialize(redis_url: str, config: RateLimitConfig) -> None:
    """check_and_increment initializes scripts lazily."""
    backend = RedisBackend(url=redis_url, key_prefix="test:")
    try:
        result = await backend.check_and_increment("lazy_user", config)
        assert result.allowed is True
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_initialize_close_idempotent(redis_url: str) -> None:
    """initialize/close can be called multiple times safely."""
    backend = RedisBackend(url=redis_url, key_prefix="test:")
    await backend.initialize()
    await backend.initialize()
    await backend.close()
    await backend.initialize()
    await backend.close()


@pytest.mark.asyncio
async def test_shared_state_across_clients(redis_url: str, config: RateLimitConfig) -> None:
    """Test that state is shared across different Redis backend instances."""
    key = "shared_key"

    # Create two separate backend instances
    backend1 = RedisBackend(url=redis_url, key_prefix="test:")
    backend2 = RedisBackend(url=redis_url, key_prefix="test:")

    await backend1.initialize()
    await backend2.initialize()

    try:
        await backend1.reset(key)
        # Make a request with backend1
        result1 = await backend1.check_and_increment(key, config)
        assert result1.allowed is True
        assert result1.remaining == config.limit - 1

        # Check with backend2 - should see the same state
        result2 = await backend2.check_and_increment(key, config)
        assert result2.allowed is True
        assert result2.remaining == config.limit - 2

        # Use up all remaining tokens with backend1
        for _ in range(config.limit - 2):
            await backend1.check_and_increment(key, config)

        # Now backend2 should be rate limited
        result3 = await backend2.check_and_increment(key, config)
        assert result3.allowed is False
        assert result3.remaining == 0
    finally:
        await backend1.close()
        await backend2.close()


@pytest.mark.asyncio
async def test_sliding_window_limits(
    backend: RedisBackend, sliding_window_config: RateLimitConfig
) -> None:
    """Sliding window enforces limit and resets after window passes."""
    key = "sliding_user"

    for _ in range(sliding_window_config.limit):
        result = await backend.check_and_increment(key, sliding_window_config)
        assert result.allowed is True

    result = await backend.check_and_increment(key, sliding_window_config)
    assert result.allowed is False
    assert result.retry_after is not None
    assert result.reset_at is not None

    await asyncio.sleep(sliding_window_config.period + 0.2)

    result = await backend.check_and_increment(key, sliding_window_config)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_leaky_bucket_limits(
    backend: RedisBackend, leaky_bucket_config: RateLimitConfig
) -> None:
    """Leaky bucket enforces queue capacity and drains over time."""
    key = "leaky_user"

    result = await backend.check_and_increment(key, leaky_bucket_config)
    assert result.allowed is True

    result = await backend.check_and_increment(key, leaky_bucket_config)
    assert result.allowed is True

    result = await backend.check_and_increment(key, leaky_bucket_config)
    assert result.allowed is False
    assert result.retry_after is not None
    assert result.reset_at is not None

    await asyncio.sleep(leaky_bucket_config.period + 0.2)

    result = await backend.check_and_increment(key, leaky_bucket_config)
    assert result.allowed is True


@pytest.mark.asyncio
async def test_token_bucket_refill_over_time(backend: RedisBackend) -> None:
    """Token bucket refills based on Redis server time."""
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )
    key = "token_refill_user"

    result = await backend.check_and_increment(key, config)
    assert result.allowed is True

    result = await backend.check_and_increment(key, config)
    assert result.allowed is False
    assert result.retry_after is not None
    assert result.reset_at is not None

    await asyncio.sleep(config.period + 0.2)

    result = await backend.check_and_increment(key, config)
    assert result.allowed is True
