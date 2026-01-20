"""Tests for the RateLimitAlgorithm protocol."""

from rate_limit_patterns.algorithms.base import RateLimitAlgorithm


class FakeAlgorithm(RateLimitAlgorithm):
    """Fake algorithm for protocol testing."""

    def compute(
        self,
        key: str,
        limit: int,
        window: int,
    ) -> tuple[int, int]:
        """Return a valid tuple of (current, remaining)."""
        return (0, limit)


def test_algorithm_protocol() -> None:
    """Verify FakeAlgorithm satisfies RateLimitAlgorithm protocol."""
    assert isinstance(FakeAlgorithm(), RateLimitAlgorithm)
