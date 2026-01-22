"""Unit tests for Token Bucket algorithm."""

import pytest

from rate_limit_patterns.algorithms.token_bucket import TokenBucketAlgorithm
from rate_limit_patterns.models import RateLimitConfig


class TestTokenBucketAlgorithm:
    """Tests for TokenBucketAlgorithm."""

    @pytest.fixture
    def algorithm(self) -> TokenBucketAlgorithm:
        """Create algorithm instance."""
        return TokenBucketAlgorithm()

    @pytest.fixture
    def config(self) -> RateLimitConfig:
        """Standard test config: 100 req/min, burst 200."""
        return RateLimitConfig(
            algorithm="token_bucket",
            limit=100,
            period=60,
            burst_size=200,
        )

    def test_initial_state_has_full_burst(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Initial state starts with burst_size tokens."""
        state = algorithm.initial_state(config)
        assert state["tokens"] == 200  # burst_size
        assert "last_refill" in state

    def test_initial_state_defaults_to_limit_if_no_burst(
        self, algorithm: TokenBucketAlgorithm
    ) -> None:
        """Without burst_size, defaults to limit."""
        config = RateLimitConfig(algorithm="token_bucket", limit=100, period=60)
        state = algorithm.initial_state(config)
        assert state["tokens"] == 100

    def test_allows_request_when_tokens_available(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Request allowed when tokens > 0."""
        state = {"tokens": 100.0, "last_refill": 1000.0}
        allowed, new_state, meta = algorithm.compute(state, config, 1000.0)

        assert allowed is True
        assert new_state["tokens"] == 99.0
        assert meta["remaining"] == 99
        assert meta["request_count"] == 101
        assert meta["reset_at"] == pytest.approx(1060.6, rel=0.01)

    def test_denies_request_when_no_tokens(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Request denied when tokens = 0."""
        state = {"tokens": 0.0, "last_refill": 1000.0}
        allowed, new_state, meta = algorithm.compute(state, config, 1000.0)

        assert allowed is False
        assert meta["retry_after"] > 0
        assert meta["reset_at"] is not None

    def test_tokens_refill_over_time(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Tokens regenerate at rate = limit/period per second."""
        state = {"tokens": 0.0, "last_refill": 1000.0}
        # After 60 seconds, should have 100 tokens (100/60 * 60)
        allowed, new_state, meta = algorithm.compute(state, config, 1060.0)

        assert allowed is True
        assert new_state["tokens"] == pytest.approx(99.0, rel=0.01)

    def test_tokens_capped_at_burst_size(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Tokens never exceed burst_size even after long time."""
        state = {"tokens": 0.0, "last_refill": 0.0}
        # After 1000 seconds, should still cap at 200
        allowed, new_state, meta = algorithm.compute(state, config, 1000.0)

        assert new_state["tokens"] <= 200  # burst_size cap

    def test_burst_allows_rapid_requests(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Can burst up to burst_size requests instantly."""
        state = algorithm.initial_state(config)
        current_time = 1000.0

        allowed_count = 0
        for _ in range(250):
            allowed, state, _ = algorithm.compute(state, config, current_time)
            if allowed:
                allowed_count += 1

        # Should allow exactly 200 (burst_size)
        assert allowed_count == 200

    def test_concurrent_safety_deterministic(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Same inputs always produce same outputs (pure function)."""
        state = {"tokens": 50.0, "last_refill": 1000.0}

        result1 = algorithm.compute(state, config, 1001.0)
        result2 = algorithm.compute(state, config, 1001.0)

        assert result1 == result2

    def test_retry_after_accounts_for_fractional_tokens(
        self, algorithm: TokenBucketAlgorithm
    ) -> None:
        """Retry-after accounts for fractional tokens needed."""
        config = RateLimitConfig(algorithm="token_bucket", limit=1, period=2)
        state = {"tokens": 0.75, "last_refill": 1000.0}

        allowed, _, meta = algorithm.compute(state, config, 1000.0)

        assert allowed is False
        assert meta["retry_after"] == 1

        slow_config = RateLimitConfig(algorithm="token_bucket", limit=1, period=4)
        slow_state = {"tokens": 0.6, "last_refill": 1000.0}

        allowed, _, meta = algorithm.compute(slow_state, slow_config, 1000.0)

        assert allowed is False
        assert meta["retry_after"] == 2

    def test_denied_contract_invariants(
        self, algorithm: TokenBucketAlgorithm, config: RateLimitConfig
    ) -> None:
        """Denied results include retry_after and monotonic reset_at."""
        state = {"tokens": 0.0, "last_refill": 1000.0}
        allowed, new_state, meta1 = algorithm.compute(state, config, 1000.0)
        allowed2, _, meta2 = algorithm.compute(new_state, config, 1000.0)

        assert allowed is False
        assert allowed2 is False
        assert meta1["remaining"] >= 0
        assert meta1["retry_after"] is not None
        assert meta2["reset_at"] >= meta1["reset_at"]
