"""Contract equivalence tests between local and Redis backends.

Temporal edge cases use injected ``now`` where both backends honor it (decision
math and state updates). Redis key TTL/EXPIRE is wall-clock and is not driven by
``now`` overrides; those cases are covered separately with a short real sleep.

Per-request cost is fixed at 1 in both Python and Lua. There is no caller-supplied
cost parameter, so "cost > capacity" is not applicable; capacity-1 covers deny
when the bucket/window/queue is empty.
"""

from __future__ import annotations

import asyncio
import os

import pytest
import pytest_asyncio

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

requires_redis = pytest.mark.skipif(not os.getenv("REDIS_URL"), reason="REDIS_URL not set")


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
    assert local.reset_at == pytest.approx(redis.reset_at, rel=0.001, abs=1e-3)


async def _run_sequence(
    redis_backend: RedisBackend,
    *,
    algorithm: str,
    key: str,
    times: list[float],
    limit: int,
    period: int,
    burst_size: int | None = None,
) -> None:
    local = LocalBackend()
    config = RateLimitConfig(
        algorithm=algorithm,  # type: ignore[arg-type]
        limit=limit,
        period=period,
        burst_size=burst_size,
        cleanup_interval=0,
        suppress_warnings=True,
    )
    try:
        for now in times:
            local_result = await local.check_and_increment(key, config, now=now)
            redis_result = await redis_backend.check_and_increment(key, config, now=now)
            _assert_equivalent(local_result, redis_result)
    finally:
        await redis_backend.reset(key)
        if algorithm == "sliding_window":
            await redis_backend.reset(f"{key}:seq")


@requires_redis
@pytest.mark.asyncio
async def test_token_bucket_equivalence(redis_backend: RedisBackend) -> None:
    await _run_sequence(
        redis_backend,
        algorithm="token_bucket",
        key="token:equivalence",
        times=[1000.0, 1000.0, 1000.0],
        limit=2,
        period=10,
        burst_size=2,
    )


@requires_redis
@pytest.mark.asyncio
async def test_epoch_zero_override_equivalence(redis_backend: RedisBackend) -> None:
    await _run_sequence(
        redis_backend,
        algorithm="token_bucket",
        key="token:epoch-zero",
        times=[0.0],
        limit=1,
        period=10,
        burst_size=1,
    )


@requires_redis
@pytest.mark.asyncio
async def test_sliding_window_equivalence(redis_backend: RedisBackend) -> None:
    await _run_sequence(
        redis_backend,
        algorithm="sliding_window",
        key="sliding:equivalence",
        times=[1000.0, 1001.0, 1002.0],
        limit=2,
        period=5,
    )


@requires_redis
@pytest.mark.asyncio
async def test_sliding_window_out_of_order_equivalence(redis_backend: RedisBackend) -> None:
    """Backward accepted timestamps still select the chronological oldest request."""
    await _run_sequence(
        redis_backend,
        algorithm="sliding_window",
        key="sliding:out-of-order",
        times=[1000.0, 999.0, 1000.0],
        limit=2,
        period=5,
    )


@requires_redis
@pytest.mark.asyncio
async def test_leaky_bucket_equivalence(redis_backend: RedisBackend) -> None:
    await _run_sequence(
        redis_backend,
        algorithm="leaky_bucket",
        key="leaky:equivalence",
        times=[1000.0, 1000.0, 1000.0],
        limit=2,
        period=4,
        burst_size=2,
    )


@requires_redis
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("algorithm", "burst_size", "times"),
    [
        ("token_bucket", 1, [1000.0, 1000.0, 1010.0, 1010.0]),
        ("leaky_bucket", 1, [1000.0, 1000.0, 1010.0, 1010.0]),
        ("sliding_window", None, [1000.0, 1005.0, 1005.0, 1010.0]),
    ],
    ids=["token_bucket", "leaky_bucket", "sliding_window"],
)
async def test_exact_window_or_refill_boundary_equivalence(
    redis_backend: RedisBackend,
    algorithm: str,
    burst_size: int | None,
    times: list[float],
) -> None:
    """Decisions match when ``now`` lands exactly on a window/refill boundary."""
    await _run_sequence(
        redis_backend,
        algorithm=algorithm,
        key=f"edge:boundary:{algorithm}",
        times=times,
        limit=1,
        period=10 if algorithm != "sliding_window" else 5,
        burst_size=burst_size,
    )


@requires_redis
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "algorithm",
    ["token_bucket", "leaky_bucket", "sliding_window"],
)
async def test_zero_and_negative_elapsed_equivalence(
    redis_backend: RedisBackend,
    algorithm: str,
) -> None:
    """Zero elapsed and clock-going-backwards both clamp refill/leak/window math."""
    burst = None if algorithm == "sliding_window" else 2
    await _run_sequence(
        redis_backend,
        algorithm=algorithm,
        key=f"edge:elapsed:{algorithm}",
        times=[1000.0, 1000.0, 999.0, 1000.0, 1005.0],
        limit=2,
        period=10 if algorithm != "sliding_window" else 5,
        burst_size=burst,
    )


@requires_redis
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "algorithm",
    ["token_bucket", "leaky_bucket"],
)
async def test_fractional_refill_equivalence(
    redis_backend: RedisBackend,
    algorithm: str,
) -> None:
    """Half-period elapsed yields a single fractional token/slot on both backends."""
    await _run_sequence(
        redis_backend,
        algorithm=algorithm,
        key=f"edge:fractional:{algorithm}",
        times=[1000.0, 1000.0, 1005.0, 1005.0],
        limit=2,
        period=10,
        burst_size=2,
    )


@requires_redis
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "algorithm",
    ["token_bucket", "leaky_bucket", "sliding_window"],
)
async def test_capacity_one_equivalence(
    redis_backend: RedisBackend,
    algorithm: str,
) -> None:
    """Capacity/limit of 1 denies the second same-timestamp request on both backends."""
    burst = None if algorithm == "sliding_window" else 1
    await _run_sequence(
        redis_backend,
        algorithm=algorithm,
        key=f"edge:cap1:{algorithm}",
        times=[50.0, 50.0, 60.0],
        limit=1,
        period=10,
        burst_size=burst,
    )


@requires_redis
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "algorithm",
    ["token_bucket", "leaky_bucket", "sliding_window"],
)
async def test_idle_long_gap_equivalence(
    redis_backend: RedisBackend,
    algorithm: str,
) -> None:
    """Long idle gaps refill/drain/evict to a fresh decision without overshoot."""
    burst = None if algorithm == "sliding_window" else 2
    await _run_sequence(
        redis_backend,
        algorithm=algorithm,
        key=f"edge:idle:{algorithm}",
        times=[1000.0, 1000.0, 1000.0, 5000.0, 5000.0],
        limit=2,
        period=10 if algorithm != "sliding_window" else 5,
        burst_size=burst,
    )


@requires_redis
@pytest.mark.asyncio
async def test_sliding_window_fractional_second_boundary(
    redis_backend: RedisBackend,
) -> None:
    """Fractional timestamps stay equivalent across Python floats and Redis ms scores."""
    await _run_sequence(
        redis_backend,
        algorithm="sliding_window",
        key="edge:sw:fractional",
        times=[1000.0, 1000.5, 1000.999, 1001.0, 1001.0],
        limit=1,
        period=1,
    )


@pytest.mark.asyncio
async def test_local_ttl_expiry_with_injected_time() -> None:
    """Local entries expire on injected time at expires_at and reinitialize."""
    local = LocalBackend()
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=10,
        burst_size=1,
        cleanup_interval=0,
    )
    first = await local.check_and_increment("local:ttl", config, now=1000.0)
    denied = await local.check_and_increment("local:ttl", config, now=1009.0)
    renewed = await local.check_and_increment("local:ttl", config, now=1010.0)

    assert first.allowed is True
    assert denied.allowed is False
    assert renewed.allowed is True
    assert renewed.remaining == 0


@requires_redis
@pytest.mark.asyncio
async def test_redis_ttl_expiry_wall_clock(redis_backend: RedisBackend) -> None:
    """Redis EXPIRE is wall-clock; after TTL elapses the key reinits even with old ``now``.

    Injected timestamps drive Lua decision math only; they do not advance key TTL.
    """
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=100,
        period=1,
        burst_size=1,
        cleanup_interval=0,
    )
    key = "edge:redis:ttl"
    try:
        first = await redis_backend.check_and_increment(key, config, now=1.0)
        second = await redis_backend.check_and_increment(key, config, now=1.0)
        assert first.allowed is True
        assert second.allowed is False

        await asyncio.sleep(1.2)

        renewed = await redis_backend.check_and_increment(key, config, now=1.0)
        assert renewed.allowed is True
        assert renewed.remaining == 0
    finally:
        await redis_backend.reset(key)
