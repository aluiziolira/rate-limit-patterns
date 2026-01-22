"""Rate limit configuration and result models."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import ClassVar, Literal

AlgorithmType = Literal["token_bucket", "sliding_window", "leaky_bucket"]


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    """Rate limiting configuration.

    Attributes:
        algorithm: The rate limiting algorithm to use.
        limit: Maximum number of tokens/requests allowed per period.
        period: Time window in seconds for the rate limit.
        burst_size: Maximum burst size for token bucket algorithm.
        cleanup_interval: Interval in seconds for cleaning up expired entries (local backend).
        suppress_warnings: Disable configuration warnings when set to True.
    """

    SLIDING_WINDOW_LIMIT_WARNING_THRESHOLD: ClassVar[int] = 1000

    algorithm: AlgorithmType
    limit: int
    period: int
    burst_size: int | None = None
    cleanup_interval: float = 300.0
    suppress_warnings: bool = False

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise ValueError("limit must be positive")
        if self.period <= 0:
            raise ValueError("period must be positive")
        if (
            not self.suppress_warnings
            and self.algorithm == "sliding_window"
            and self.limit > self.SLIDING_WINDOW_LIMIT_WARNING_THRESHOLD
        ):
            warnings.warn(
                "Sliding window log limits above 1000 can create O(N) memory pressure. "
                "Consider token bucket or lower limits for high-throughput keys.",
                RuntimeWarning,
                stacklevel=2,
            )

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
        request_count: Algorithm-specific count of tracked requests.
        limit: The rate limit that was checked against.
    """

    allowed: bool
    remaining: int
    limit: int
    retry_after: int | None = None
    reset_at: float | None = None
    request_count: int = 0

    def __post_init__(self) -> None:
        if self.remaining < 0:
            raise ValueError("remaining cannot be negative")
        if self.request_count < 0:
            raise ValueError("request_count cannot be negative")


@dataclass(frozen=True, slots=True)
class RateLimitEvent:
    """Observability event emitted by integrations.

    Attributes:
        algorithm: The algorithm used for the check.
        allowed: Whether the request was allowed.
        remaining: Remaining capacity reported by the backend.
        retry_after: Retry-after seconds when denied.
        backend_type: Backend class name (e.g., RedisBackend).
        latency_ms: Backend check latency in milliseconds.
    """

    algorithm: AlgorithmType
    allowed: bool
    remaining: int
    retry_after: int | None
    backend_type: str
    latency_ms: float
