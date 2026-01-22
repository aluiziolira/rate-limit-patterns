"""Unit tests for RateLimitConfig."""

from __future__ import annotations

import warnings

import pytest

from rate_limit_patterns.models import RateLimitConfig


class TestRateLimitConfig:
    """Tests for RateLimitConfig dataclass."""

    def test_config_with_required_fields_only(self) -> None:
        """Config can be created with just algorithm, limit, period."""
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=100,
            period=60,
        )
        assert config.algorithm == "token_bucket"
        assert config.limit == 100
        assert config.period == 60
        assert config.burst_size is None
        assert config.cleanup_interval == 300.0

    def test_config_with_burst_size(self) -> None:
        """Token bucket config accepts burst_size."""
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=100,
            period=60,
            burst_size=500,
        )
        assert config.burst_size == 500

    def test_config_algorithm_literal_types(self) -> None:
        """Algorithm must be one of the valid literals."""
        # Valid algorithms
        for algo in ["token_bucket", "sliding_window", "leaky_bucket"]:
            config = RateLimitConfig(algorithm=algo, limit=100, period=60)
            assert config.algorithm == algo

    def test_config_validates_positive_limit(self) -> None:
        """Limit must be positive."""
        with pytest.raises(ValueError, match="limit must be positive"):
            RateLimitConfig(algorithm="token_bucket", limit=0, period=60)

    def test_config_validates_positive_period(self) -> None:
        """Period must be positive."""
        with pytest.raises(ValueError, match="period must be positive"):
            RateLimitConfig(algorithm="token_bucket", limit=100, period=0)

    def test_config_tokens_per_second_property(self) -> None:
        """Config calculates tokens per second."""
        config = RateLimitConfig(algorithm="token_bucket", limit=100, period=60)
        assert config.tokens_per_second == pytest.approx(100 / 60)

    def test_sliding_window_warns_above_threshold(self) -> None:
        """Sliding window config warns when limit exceeds threshold."""
        threshold = RateLimitConfig.SLIDING_WINDOW_LIMIT_WARNING_THRESHOLD
        with pytest.warns(RuntimeWarning, match="Sliding window log limits"):
            RateLimitConfig(algorithm="sliding_window", limit=threshold + 1, period=60)

    def test_sliding_window_no_warning_below_threshold(self) -> None:
        """Sliding window config does not warn below threshold."""
        threshold = RateLimitConfig.SLIDING_WINDOW_LIMIT_WARNING_THRESHOLD
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            RateLimitConfig(algorithm="sliding_window", limit=threshold, period=60)
        assert not caught

    def test_sliding_window_warning_can_be_suppressed(self) -> None:
        """Sliding window warning can be suppressed explicitly."""
        threshold = RateLimitConfig.SLIDING_WINDOW_LIMIT_WARNING_THRESHOLD
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            RateLimitConfig(
                algorithm="sliding_window",
                limit=threshold + 1,
                period=60,
                suppress_warnings=True,
            )
        assert not caught
