"""Tests for the RateLimitAlgorithm protocol."""

from typing import Any

from rate_limit_patterns.algorithms.base import RateLimitAlgorithm
from rate_limit_patterns.models import RateLimitConfig


class FakeAlgorithm(RateLimitAlgorithm):
    """Fake algorithm for protocol testing."""

    def compute(
        self,
        state: dict[str, Any],
        config: RateLimitConfig,
        current_time: float,
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        """Return a valid tuple of (allowed, new_state, metadata)."""
        return (True, state, {})

    def initial_state(self, config: RateLimitConfig) -> dict[str, Any]:
        """Return initial state for the algorithm."""
        return {}


def test_algorithm_protocol() -> None:
    """Verify FakeAlgorithm satisfies RateLimitAlgorithm protocol."""
    assert isinstance(FakeAlgorithm(), RateLimitAlgorithm)
