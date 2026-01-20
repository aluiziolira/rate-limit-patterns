"""Token Bucket rate limiting algorithm."""

from __future__ import annotations

import math
from typing import Any

from rate_limit_patterns.models import RateLimitConfig


class TokenBucketAlgorithm:
    """Token Bucket algorithm implementation.

    A token bucket algorithm where tokens are added at a fixed rate
    up to a maximum burst capacity. Each request consumes one token.
    """

    def initial_state(self, config: RateLimitConfig) -> dict[str, Any]:
        """Return initial state with full bucket of tokens.

        Args:
            config: Rate limit configuration.

        Returns:
            Initial state with tokens at burst_size (or limit if no burst).
        """
        burst = config.burst_size if config.burst_size is not None else config.limit
        return {
            "tokens": float(burst),
            "last_refill": 0.0,
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
        last_refill = state["last_refill"]
        current_tokens = state["tokens"]

        # Calculate elapsed time and refill tokens
        elapsed = max(0.0, current_time - last_refill)
        refill_amount = elapsed * config.tokens_per_second

        # Calculate capacity cap
        burst = config.burst_size if config.burst_size is not None else config.limit

        # Calculate new token balance with cap
        new_tokens = min(float(burst), current_tokens + refill_amount)

        # Create new state (pure function - don't mutate input)
        new_state: dict[str, Any] = {
            "tokens": new_tokens,
            "last_refill": current_time,
        }

        # Check if we can consume a token
        if new_tokens >= 1.0:
            # Consume exactly 1 token
            new_state["tokens"] = new_tokens - 1.0
            remaining = int(new_state["tokens"])
            return True, new_state, {"remaining": remaining}
        else:
            # Deny request - calculate retry_after
            # Need to wait until we have at least 1 token
            # Time needed = 1 / tokens_per_second (rounded up to be safe)
            retry_after = math.ceil(1.0 / config.tokens_per_second)
            return False, new_state, {"remaining": 0, "retry_after": retry_after}
