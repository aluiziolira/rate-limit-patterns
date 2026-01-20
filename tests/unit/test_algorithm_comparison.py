"""Comparative tests across all algorithms."""

import pytest

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.models import RateLimitConfig


class TestAlgorithmComparison:
    """Compare behavior across algorithms."""

    @pytest.fixture
    def backend(self) -> LocalBackend:
        return LocalBackend()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "algorithm", ["token_bucket", "sliding_window", "leaky_bucket"]
    )
    async def test_all_algorithms_respect_limit(
        self, backend: LocalBackend, algorithm: str
    ) -> None:
        """All algorithms enforce configured limit."""
        config = RateLimitConfig(
            algorithm=algorithm,
            limit=10,
            period=60,
            burst_size=10,
        )

        allowed_count = 0
        for _ in range(20):
            result = await backend.check_and_increment(f"test:{algorithm}", config)
            if result.allowed:
                allowed_count += 1

        # All should allow at most 10 (limit/burst)
        assert allowed_count <= 10

    @pytest.mark.asyncio
    async def test_token_bucket_allows_burst(self, backend: LocalBackend) -> None:
        """Token bucket allows burst up to burst_size."""
        config = RateLimitConfig(
            algorithm="token_bucket",
            limit=10,
            period=60,
            burst_size=50,  # High burst
        )

        allowed_count = 0
        for _ in range(100):
            result = await backend.check_and_increment("burst_test", config)
            if result.allowed:
                allowed_count += 1

        assert allowed_count == 50  # burst_size

    @pytest.mark.asyncio
    async def test_sliding_window_no_burst(self, backend: LocalBackend) -> None:
        """Sliding window doesn't allow burst."""
        config = RateLimitConfig(
            algorithm="sliding_window",
            limit=10,
            period=60,
            # burst_size ignored for sliding window
        )

        allowed_count = 0
        for _ in range(20):
            result = await backend.check_and_increment("no_burst_test", config)
            if result.allowed:
                allowed_count += 1

        assert allowed_count == 10  # Exactly limit
