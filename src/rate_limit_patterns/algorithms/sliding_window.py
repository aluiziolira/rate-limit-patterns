"""Sliding Window Counter rate limiting algorithm."""

from __future__ import annotations

import math
from typing import Any

from rate_limit_patterns.models import RateLimitConfig


class SlidingWindowAlgorithm:
    """Sliding Window Counter algorithm implementation.

    A sliding window counter algorithm where requests are tracked by timestamp
    within a fixed time window. Requests older than the window are evicted.
    """

    def initial_state(self, config: RateLimitConfig) -> dict[str, Any]:
        """Return initial empty state.

        Args:
            config: Rate limit configuration.

        Returns:
            Initial state with empty requests list and count 0.
        """
        return {
            "requests": [],
            "count": 0,
        }

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
        # Ensure pure function - do not mutate incoming state
        requests = list(state["requests"])  # Create a copy of the list

        # Evict timestamps older than the sliding window
        # Keep only t where t > current_time - config.period (strict inequality)
        cutoff = current_time - config.period
        valid_requests = [t for t in requests if t > cutoff]

        # Check if request is allowed
        if len(valid_requests) < config.limit:
            # Allow: append current_time to the window
            valid_requests.append(current_time)

            new_state: dict[str, Any] = {
                "requests": valid_requests,
                "count": len(valid_requests),
            }
            remaining = config.limit - len(valid_requests)
            meta: dict[str, Any] = {"remaining": remaining}
            return True, new_state, meta
        else:
            # Deny: calculate retry_after based on oldest request
            oldest_request = valid_requests[0]
            retry_after = math.ceil(oldest_request + config.period - current_time)

            new_state = {
                "requests": valid_requests,
                "count": len(valid_requests),
            }
            meta = {"remaining": 0, "retry_after": retry_after}
            return False, new_state, meta
