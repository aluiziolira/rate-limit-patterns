"""Unit tests for Sliding Window Counter algorithm."""

import pytest

from rate_limit_patterns.algorithms.sliding_window import SlidingWindowAlgorithm
from rate_limit_patterns.models import RateLimitConfig


class TestSlidingWindowAlgorithm:
    """Tests for SlidingWindowAlgorithm."""

    @pytest.fixture
    def algorithm(self) -> SlidingWindowAlgorithm:
        return SlidingWindowAlgorithm()

    @pytest.fixture
    def config(self) -> RateLimitConfig:
        """100 requests per 60 seconds."""
        return RateLimitConfig(
            algorithm="sliding_window",
            limit=100,
            period=60,
        )

    def test_initial_state_is_empty(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Initial state has no requests."""
        state = algorithm.initial_state(config)
        assert state["requests"] == []
        assert state["count"] == 0

    def test_allows_first_request(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """First request is always allowed."""
        state = algorithm.initial_state(config)
        allowed, new_state, meta = algorithm.compute(state, config, 1000.0)

        assert allowed is True
        assert new_state["count"] == 1
        assert meta["remaining"] == 99
        assert meta["request_count"] == 1
        assert meta["reset_at"] == 1060.0

    def test_allows_requests_up_to_limit(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Allows exactly limit requests in window."""
        state = algorithm.initial_state(config)
        current_time = 1000.0

        for i in range(100):
            allowed, state, _ = algorithm.compute(state, config, current_time)
            assert allowed is True
            current_time += 0.1  # Small time increments

    def test_denies_request_over_limit(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Request #101 in same window is denied."""
        state = algorithm.initial_state(config)
        current_time = 1000.0

        # Make 100 requests
        for _ in range(100):
            allowed, state, _ = algorithm.compute(state, config, current_time)
            current_time += 0.1

        # 101st should be denied
        allowed, state, meta = algorithm.compute(state, config, current_time)
        assert allowed is False
        assert meta["retry_after"] > 0
        assert meta["request_count"] == config.limit
        assert meta["reset_at"] >= current_time

    def test_old_requests_expire(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Requests older than period are evicted."""
        state = algorithm.initial_state(config)

        # Make 100 requests at time 1000
        for _ in range(100):
            _, state, _ = algorithm.compute(state, config, 1000.0)

        # At time 1061 (61 seconds later), all old requests expired
        allowed, new_state, meta = algorithm.compute(state, config, 1061.0)

        assert allowed is True
        assert new_state["count"] == 1  # Only the new request
        assert meta["request_count"] == 1

    def test_window_slides_correctly(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Window slides, allowing new requests as old ones expire."""
        state = algorithm.initial_state(config)

        # Make 100 requests spread over 60 seconds
        for i in range(100):
            _, state, _ = algorithm.compute(state, config, 1000.0 + i * 0.6)

        # At 1060 (window start), first request expired
        allowed, _, meta = algorithm.compute(state, config, 1060.0)
        assert allowed is True

    def test_boundary_excludes_exact_cutoff(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Requests at the exact cutoff are excluded."""
        state = {"requests": [940.0], "count": 1}

        allowed, new_state, meta = algorithm.compute(state, config, 1000.0)

        assert allowed is True
        assert new_state["count"] == 1
        assert meta["request_count"] == 1

    def test_denied_contract_invariants(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Denied results include retry_after and monotonic reset_at."""
        state = algorithm.initial_state(config)
        current_time = 1000.0

        for _ in range(config.limit):
            _, state, _ = algorithm.compute(state, config, current_time)

        allowed, new_state, meta1 = algorithm.compute(state, config, current_time)
        allowed2, _, meta2 = algorithm.compute(new_state, config, current_time)

        assert allowed is False
        assert allowed2 is False
        assert meta1["remaining"] == 0
        assert meta1["retry_after"] is not None
        assert meta2["reset_at"] >= meta1["reset_at"]

    def test_no_burst_allowed(
        self, algorithm: SlidingWindowAlgorithm, config: RateLimitConfig
    ) -> None:
        """Sliding window doesn't allow burst above limit."""
        state = algorithm.initial_state(config)
        current_time = 1000.0

        allowed_count = 0
        for _ in range(150):
            allowed, state, _ = algorithm.compute(state, config, current_time)
            if allowed:
                allowed_count += 1

        # Should allow exactly 100 (no burst)
        assert allowed_count == 100
