"""Local (in-memory) rate limit backend implementation."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from rate_limit_patterns.algorithms.base import RateLimitAlgorithm
from rate_limit_patterns.algorithms.leaky_bucket import LeakyBucketAlgorithm
from rate_limit_patterns.algorithms.sliding_window import SlidingWindowAlgorithm
from rate_limit_patterns.algorithms.token_bucket import TokenBucketAlgorithm
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig, RateLimitResult


class LocalBackend:
    """In-memory rate limit backend using asyncio.Lock for thread safety."""

    def __init__(self) -> None:
        """Initialize the local backend."""
        self._lock = asyncio.Lock()
        self._state: dict[str, dict[str, Any]] = {}
        self._algorithms: dict[AlgorithmType, RateLimitAlgorithm] = {
            "token_bucket": TokenBucketAlgorithm(),
            "sliding_window": SlidingWindowAlgorithm(),
            "leaky_bucket": LeakyBucketAlgorithm(),
        }

    async def check_and_increment(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Check and increment the rate limit counter for a key.

        Args:
            key: Unique identifier for the rate limit (e.g., user ID, IP).
            config: Rate limit configuration to apply.

        Returns:
            RateLimitResult indicating if the request is allowed and state.
        """
        async with self._lock:
            algorithm = self._algorithms.get(config.algorithm)
            if algorithm is None:
                msg = f"Unknown algorithm: {config.algorithm}. Supported algorithms: {list(self._algorithms.keys())}"
                raise ValueError(msg)
            return self._check_algorithm(key, config, algorithm)

    def _check_algorithm(
        self, key: str, config: RateLimitConfig, algorithm: RateLimitAlgorithm
    ) -> RateLimitResult:
        """Check and increment using the specified algorithm.

        Args:
            key: Unique identifier for the rate limit.
            config: Rate limit configuration.
            algorithm: The algorithm to use for rate limiting.

        Returns:
            RateLimitResult for the rate limit check.
        """
        current_time = time.time()

        # Get or initialize state
        state = self._state[key] if key in self._state else algorithm.initial_state(config)

        # Compute new state (pure function, does not mutate state)
        allowed, new_state, metadata = algorithm.compute(state, config, current_time)

        # Replace state with new state (do not mutate in-place)
        self._state[key] = new_state

        # Map metadata to RateLimitResult
        return RateLimitResult(
            allowed=allowed,
            remaining=metadata["remaining"],
            limit=config.limit,
            retry_after=metadata.get("retry_after"),
            reset_at=metadata.get("reset_at"),
            request_count=metadata.get("request_count", 0),
        )

    async def reset(self, key: str) -> None:
        """Reset the rate limit state for a key.

        Args:
            key: Unique identifier for the rate limit to reset.
        """
        async with self._lock:
            self._state.pop(key, None)

    async def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key.

        Args:
            key: Unique identifier to get metrics for.

        Returns:
            Dictionary containing metrics for the key.
        """
        async with self._lock:
            if key not in self._state:
                return {}
            # Return shallow copy to prevent external mutation
            return dict(self._state[key])
