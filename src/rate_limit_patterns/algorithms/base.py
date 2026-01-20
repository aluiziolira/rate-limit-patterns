"""Rate limit algorithm protocol and base types."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from rate_limit_patterns.models import RateLimitConfig


@runtime_checkable
class RateLimitAlgorithm(Protocol):
    """Protocol for rate limiting algorithms.

    Implementations must provide methods to compute rate limit decisions
    and initialize algorithm state.
    """

    def compute(
        self,
        state: dict[str, Any],
        config: RateLimitConfig,
        current_time: float,
    ) -> tuple[bool, dict[str, Any], dict[str, Any]]:
        """Compute whether a request is allowed and update state.

        Args:
            state: Current algorithm state dictionary.
            config: Rate limit configuration.
            current_time: Current Unix timestamp in seconds.

        Returns:
            Tuple of (allowed: bool, new_state: dict[str, Any], metadata: dict[str, Any]).
        """
        ...

    def initial_state(self, config: RateLimitConfig) -> dict[str, Any]:
        """Return initial state for the algorithm.

        Args:
            config: Rate limit configuration.

        Returns:
            Initial state dictionary for the algorithm.
        """
        ...
