"""Leaky Bucket rate limiting algorithm."""

from __future__ import annotations

import math
from typing import Any

from rate_limit_patterns.models import RateLimitConfig


class LeakyBucketAlgorithm:
    """Leaky Bucket algorithm implementation.

    A leaky bucket algorithm where requests enter a queue and are processed
    at a fixed rate. Requests are denied when the queue is at capacity.
    """

    def initial_state(self, config: RateLimitConfig) -> dict[str, Any]:
        """Return initial state with empty queue.

        Args:
            config: Rate limit configuration.

        Returns:
            Initial state with empty queue.
        """
        return {
            "queue_size": 0.0,
            "last_leak": 0.0,
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
        queue_size = state["queue_size"]
        last_leak = state["last_leak"]

        # Calculate capacity and leak rate
        capacity = config.burst_size if config.burst_size is not None else config.limit
        rate = config.tokens_per_second

        # Calculate elapsed time and drain the queue
        elapsed = max(0.0, current_time - last_leak)
        drained = elapsed * rate
        queue_after_leak = max(0.0, queue_size - drained)

        # Check if we can enqueue the new request
        if queue_after_leak + 1.0 <= capacity:
            # Allow request and enqueue it
            new_queue_size = queue_after_leak + 1.0
            allowed = True
            remaining = max(0, int(math.floor(capacity - new_queue_size)))
            metadata: dict[str, Any] = {"remaining": remaining}
        else:
            # Deny request - do not enqueue
            new_queue_size = queue_after_leak
            allowed = False

            # Calculate retry_after (guard against rate <= 0)
            if rate > 0:
                retry_after = math.ceil(
                    ((queue_after_leak + 1.0) - capacity) / rate
                )
                retry_after = max(1, retry_after)  # Ensure at least 1 second
            else:
                retry_after = 1
            remaining = max(0, int(math.floor(capacity - new_queue_size)))
            metadata = {"remaining": remaining, "retry_after": retry_after}

        # Create new state (pure function - don't mutate input)
        new_state: dict[str, Any] = {
            "queue_size": new_queue_size,
            "last_leak": current_time,
        }

        return allowed, new_state, metadata
