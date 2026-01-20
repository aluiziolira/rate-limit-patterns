"""Rate limit configuration and result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AlgorithmType = Literal["token_bucket", "sliding_window", "leaky_bucket"]


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Rate limiting configuration.

    Attributes:
        algorithm: The rate limiting algorithm to use.
        limit: Maximum number of tokens/requests allowed per period.
        period: Time window in seconds for the rate limit.
        burst_size: Maximum burst size for token bucket algorithm.
        cleanup_interval: Interval in seconds for cleaning up expired entries.
    """

    algorithm: AlgorithmType
    limit: int
    period: int
    burst_size: int | None = None
    cleanup_interval: float = 300.0

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.period <= 0:
            raise ValueError("period must be positive")

    @property
    def tokens_per_second(self) -> float:
        """Calculate tokens allowed per second.

        Returns:
            The rate limit expressed as tokens per second.
        """
        return self.limit / self.period


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    """Result of a rate limit check.

    Attributes:
        allowed: Whether the request is allowed.
        remaining: Number of tokens/requests remaining.
        retry_after: Seconds until the client can retry (if denied).
        reset_at: Unix timestamp when the rate limit resets.
        request_count: Number of requests in the current window.
        limit: The rate limit that was checked against.
    """

    allowed: bool
    remaining: int
    limit: int
    retry_after: int | None = None
    reset_at: float | None = None
    request_count: int = 0

    def __post_init__(self) -> None:
        if self.remaining > self.limit:
            raise ValueError("remaining cannot exceed limit")
