"""Unit tests for Local (in-memory) backend."""

import asyncio
import time
from unittest.mock import MagicMock

import pytest

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.models import RateLimitConfig


class TestLocalBackend:
    """Tests for LocalBackend."""

    @pytest.fixture
    def backend(self) -> LocalBackend:
        """Create fresh backend instance."""
        return LocalBackend()

    @pytest.fixture
    def token_bucket_config(self) -> RateLimitConfig:
        """Token bucket config for tests."""
        return RateLimitConfig(
            algorithm="token_bucket",
            limit=100,
            period=60,
            burst_size=200,
            cleanup_interval=0,
        )

    @pytest.mark.asyncio
    async def test_first_request_allowed(
        self, backend: LocalBackend, token_bucket_config: RateLimitConfig
    ) -> None:
        """First request to new key is always allowed."""
        result = await backend.check_and_increment("user:123", token_bucket_config)

        assert result.allowed is True
        assert result.remaining == 199  # burst - 1

    @pytest.mark.asyncio
    async def test_requests_under_limit_allowed(
        self, backend: LocalBackend, token_bucket_config: RateLimitConfig
    ) -> None:
        """Multiple requests under limit are allowed."""
        for i in range(100):
            result = await backend.check_and_increment("user:123", token_bucket_config)
            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_requests_over_burst_denied(
        self, backend: LocalBackend, token_bucket_config: RateLimitConfig
    ) -> None:
        """Requests exceeding burst are denied."""
        # Exhaust burst capacity
        for _ in range(200):
            await backend.check_and_increment("user:123", token_bucket_config)

        # Next request should be denied
        result = await backend.check_and_increment("user:123", token_bucket_config)
        assert result.allowed is False
        assert result.retry_after is not None
        assert result.retry_after > 0

    @pytest.mark.asyncio
    async def test_different_keys_independent(
        self, backend: LocalBackend, token_bucket_config: RateLimitConfig
    ) -> None:
        """Different keys have independent limits."""
        # Exhaust user:1
        for _ in range(200):
            await backend.check_and_increment("user:1", token_bucket_config)

        # user:2 should still be allowed
        result = await backend.check_and_increment("user:2", token_bucket_config)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_reset_clears_state(
        self, backend: LocalBackend, token_bucket_config: RateLimitConfig
    ) -> None:
        """Reset clears all state for a key."""
        # Use some capacity
        for _ in range(100):
            await backend.check_and_increment("user:123", token_bucket_config)

        # Reset
        await backend.reset("user:123")

        # Should have full capacity again
        result = await backend.check_and_increment("user:123", token_bucket_config)
        assert result.remaining == 199  # Full burst - 1

    @pytest.mark.asyncio
    async def test_get_metrics_returns_state(
        self, backend: LocalBackend, token_bucket_config: RateLimitConfig
    ) -> None:
        """get_metrics returns current state."""
        await backend.check_and_increment("user:123", token_bucket_config)

        metrics = await backend.get_metrics("user:123")

        assert "tokens" in metrics
        assert "last_refill" in metrics

    @pytest.mark.asyncio
    async def test_get_metrics_empty_for_unknown_key(self, backend: LocalBackend) -> None:
        """get_metrics returns empty dict for unknown key."""
        metrics = await backend.get_metrics("unknown:key")
        assert metrics == {}

    @pytest.mark.asyncio
    async def test_result_contains_all_fields(
        self, backend: LocalBackend, token_bucket_config: RateLimitConfig
    ) -> None:
        """Result contains all required fields."""
        result = await backend.check_and_increment("user:123", token_bucket_config)

        assert hasattr(result, "allowed")
        assert hasattr(result, "remaining")
        assert hasattr(result, "retry_after")
        assert hasattr(result, "reset_at")
        assert hasattr(result, "request_count")
        assert hasattr(result, "limit")
        assert result.limit == 100

    @pytest.mark.asyncio
    async def test_expired_state_reinitializes(self, backend: LocalBackend) -> None:
        """Expired state resets to initial capacity on next check."""
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=1,
            burst_size=1,
            cleanup_interval=0.1,
        )

        await backend.check_and_increment("user:123", config, now=1000.0)
        result = await backend.check_and_increment("user:123", config, now=1002.0)

        assert result.allowed is True
        assert result.remaining == 0

    @pytest.mark.asyncio
    async def test_cleanup_removes_expired_keys(self) -> None:
        """Cleanup evicts expired keys under churn."""
        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=1,
            burst_size=1,
            cleanup_interval=0.1,
        )

        await backend.check_and_increment("user:1", config, now=time.time() - 3600)
        assert "user:1" in backend._state
        await backend.check_and_increment("user:2", config)
        assert backend._cleanup_task is not None

        await asyncio.sleep(0.2)
        assert "user:1" not in backend._state
        await backend.close()

    @pytest.mark.asyncio
    async def test_background_cleanup_lifecycle(self) -> None:
        """Background cleanup task removes expired keys and stops on close."""
        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=1,
            burst_size=1,
            cleanup_interval=0.05,
        )

        await backend.check_and_increment("user:expired", config, now=time.time() - 3600)
        assert "user:expired" in backend._state

        await asyncio.sleep(0.15)
        assert "user:expired" not in backend._state

        await backend.close()
        assert backend._cleanup_task is None or backend._cleanup_task.done()

    @pytest.mark.asyncio
    async def test_cleanup_logs_exceptions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Cleanup loop logs exceptions instead of swallowing silently."""
        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=1,
            burst_size=1,
            cleanup_interval=0.01,
        )
        logger = MagicMock()
        monkeypatch.setattr("rate_limit_patterns.backend.local.logger", logger)
        seen = asyncio.Event()

        async def boom(_now: float) -> None:
            seen.set()
            raise RuntimeError("boom")

        monkeypatch.setattr(backend, "_cleanup_expired", boom)

        try:
            await backend.check_and_increment("user:log", config)
            await asyncio.wait_for(seen.wait(), timeout=1.0)
            assert logger.debug.called
        finally:
            await backend.close()

    @pytest.mark.asyncio
    async def test_monotonic_clock_is_stable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Monotonic clock protects against wall-clock regressions."""
        monotonic_values = iter([100.0, 101.0, 102.0])
        wall_values = iter([1000.0, 900.0, 800.0])

        monkeypatch.setattr(time, "monotonic", lambda: next(monotonic_values, 102.0))
        monkeypatch.setattr(time, "time", lambda: next(wall_values, 800.0))

        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=1,
            period=10,
            burst_size=1,
            cleanup_interval=0,
        )

        result1 = await backend.check_and_increment("user:clock", config)
        result2 = await backend.check_and_increment("user:clock", config)

        assert result2.reset_at is not None
        assert result1.reset_at is not None
        assert result2.reset_at >= result1.reset_at


class TestLocalBackendConcurrency:
    """Concurrency tests for LocalBackend."""

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
    async def test_concurrent_requests_respect_limit(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """Concurrent requests don't exceed burst limit."""

        async def make_request() -> bool:
            result = await backend.check_and_increment("user:123", config)
            return result.allowed

        # Fire 200 concurrent requests (burst is 100)
        tasks = [make_request() for _ in range(200)]
        results = await asyncio.gather(*tasks)

        allowed_count = sum(1 for r in results if r)

        # Should allow exactly 100 (burst_size)
        assert allowed_count == 100

    @pytest.mark.asyncio
    async def test_concurrent_different_keys(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """Concurrent requests to different keys are independent."""

        async def make_requests_for_user(user_id: int) -> int:
            count = 0
            for _ in range(50):
                result = await backend.check_and_increment(f"user:{user_id}", config)
                if result.allowed:
                    count += 1
            return count

        # 10 users, each making 50 requests (burst is 100)
        tasks = [make_requests_for_user(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Each user should get 50 allowed (under their burst)
        for count in results:
            assert count == 50

    @pytest.mark.asyncio
    async def test_concurrent_many_keys(
        self, backend: LocalBackend, config: RateLimitConfig
    ) -> None:
        """Many keys can be processed concurrently without violating limits."""
        keys = [f"user:{i}" for i in range(50)]
        allowed_counts = dict.fromkeys(keys, 0)
        semaphore = asyncio.Semaphore(25)
        counter_lock = asyncio.Lock()

        async def hit(key: str) -> None:
            async with semaphore:
                result = await backend.check_and_increment(key, config)
                if result.allowed:
                    async with counter_lock:
                        allowed_counts[key] += 1

        tasks = [hit(key) for key in keys for _ in range(20)]
        await asyncio.gather(*tasks)

        for key in keys:
            assert allowed_counts[key] == 20
