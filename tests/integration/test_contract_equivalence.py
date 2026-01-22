"""Contract equivalence tests between local and Redis backends."""

from __future__ import annotations

import os

import pytest
import pytest_asyncio

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

pytestmark = pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="REDIS_URL not set")


@pytest_asyncio.fixture
async def redis_backend(redis_url: str) -> RedisBackend:
    backend = RedisBackend(url=redis_url, key_prefix="contract:")
    await backend.initialize()
    yield backend
    await backend.close()


def _assert_equivalent(local: RateLimitResult, redis: RateLimitResult) -> None:
    assert local.allowed == redis.allowed
    assert local.remaining == redis.remaining
    assert local.retry_after == redis.retry_after
    assert local.request_count == redis.request_count
    assert local.reset_at == pytest.approx(redis.reset_at, rel=0.001)


@pytest.mark.asyncio
async def test_token_bucket_equivalence(redis_backend: RedisBackend) -> None:
    local = LocalBackend()
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=2,
        period=10,
        burst_size=2,
        cleanup_interval=0,
    )
    now = 1000.0
    key = "token:equivalence"

    try:
        for _ in range(3):
            local_result = await local.check_and_increment(key, config, now=now)
            redis_result = await redis_backend.check_and_increment(key, config, now=now)
            _assert_equivalent(local_result, redis_result)
    finally:
        await redis_backend.reset(key)


@pytest.mark.asyncio
async def test_epoch_zero_override_equivalence(redis_backend: RedisBackend) -> None:
    local = LocalBackend()
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=10,
        burst_size=1,
        cleanup_interval=0,
    )
    key = "token:epoch-zero"
    now = 0.0

    try:
        local_result = await local.check_and_increment(key, config, now=now)
        redis_result = await redis_backend.check_and_increment(key, config, now=now)
        _assert_equivalent(local_result, redis_result)
    finally:
        await redis_backend.reset(key)


@pytest.mark.asyncio
async def test_sliding_window_equivalence(redis_backend: RedisBackend) -> None:
    local = LocalBackend()
    config = RateLimitConfig(
        algorithm="sliding_window",
        limit=2,
        period=5,
        cleanup_interval=0,
    )
    key = "sliding:equivalence"
    times = [1000.0, 1001.0, 1002.0]

    try:
        for now in times:
            local_result = await local.check_and_increment(key, config, now=now)
            redis_result = await redis_backend.check_and_increment(key, config, now=now)
            _assert_equivalent(local_result, redis_result)
    finally:
        await redis_backend.reset(key)


@pytest.mark.asyncio
async def test_leaky_bucket_equivalence(redis_backend: RedisBackend) -> None:
    local = LocalBackend()
    config = RateLimitConfig(
        algorithm="leaky_bucket",
        limit=2,
        period=4,
        burst_size=2,
        cleanup_interval=0,
    )
    key = "leaky:equivalence"
    now = 1000.0

    try:
        for _ in range(3):
            local_result = await local.check_and_increment(key, config, now=now)
            redis_result = await redis_backend.check_and_increment(key, config, now=now)
            _assert_equivalent(local_result, redis_result)
    finally:
        await redis_backend.reset(key)
