"""Unit tests for Leaky Bucket algorithm."""

import pytest

from rate_limit_patterns.algorithms.leaky_bucket import LeakyBucketAlgorithm
from rate_limit_patterns.models import RateLimitConfig


class TestLeakyBucketAlgorithm:
    """Tests for LeakyBucketAlgorithm."""

    @pytest.fixture
    def algorithm(self) -> LeakyBucketAlgorithm:
        return LeakyBucketAlgorithm()

    @pytest.fixture
    def config(self) -> RateLimitConfig:
        """100 req/min, queue capacity 200."""
        return RateLimitConfig(
            algorithm="leaky_bucket",
            limit=100,
            period=60,
            burst_size=200,  # Queue capacity
        )

    def test_initial_state_empty_queue(
        self, algorithm: LeakyBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Initial state has empty queue."""
        state = algorithm.initial_state(config)
        assert state["queue_size"] == 0
        assert "last_leak" in state

    def test_allows_request_when_queue_not_full(
        self, algorithm: LeakyBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Request allowed when queue has capacity."""
        state = algorithm.initial_state(config)
        allowed, new_state, meta = algorithm.compute(state, config, 1000.0)

        assert allowed is True
        assert new_state["queue_size"] == 1
        assert meta["request_count"] == 1
        assert meta["reset_at"] == pytest.approx(1000.6, rel=0.01)

    def test_denies_when_queue_full(
        self, algorithm: LeakyBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Request denied when queue at capacity."""
        state = {"queue_size": 200, "last_leak": 1000.0}  # Full queue
        allowed, new_state, meta = algorithm.compute(state, config, 1000.0)

        assert allowed is False
        assert meta["retry_after"] > 0
        assert meta["request_count"] == 200

    def test_queue_leaks_over_time(
        self, algorithm: LeakyBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Queue drains at rate = limit/period per second."""
        # Queue with 100 items
        state = {"queue_size": 100, "last_leak": 1000.0}

        # After 60 seconds, 100 items should have leaked
        allowed, new_state, meta = algorithm.compute(state, config, 1060.0)

        assert allowed is True
        assert new_state["queue_size"] == 1  # Queue drained + new request
        assert meta["request_count"] == 1

    def test_smooth_output_rate(
        self, algorithm: LeakyBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Output rate is constant regardless of input burst."""
        state = algorithm.initial_state(config)

        # Add 200 requests instantly (fills queue)
        for _ in range(200):
            allowed, state, _ = algorithm.compute(state, config, 1000.0)
            if not allowed:
                break

        # Queue should be at capacity
        assert state["queue_size"] == 200

    def test_queue_size_never_negative(
        self, algorithm: LeakyBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Queue size stays at 0 minimum after leaking."""
        state = {"queue_size": 10, "last_leak": 0.0}

        # After very long time, queue should be 0, not negative
        allowed, new_state, _ = algorithm.compute(state, config, 10000.0)

        assert new_state["queue_size"] >= 0

    def test_denied_contract_invariants(
        self, algorithm: LeakyBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Denied results include retry_after and monotonic reset_at."""
        state = {"queue_size": 200.0, "last_leak": 1000.0}

        allowed, new_state, meta1 = algorithm.compute(state, config, 1000.0)
        allowed2, _, meta2 = algorithm.compute(new_state, config, 1000.0)

        assert allowed is False
        assert allowed2 is False
        assert meta1["remaining"] >= 0
        assert meta1["retry_after"] is not None
        assert meta2["reset_at"] >= meta1["reset_at"]
