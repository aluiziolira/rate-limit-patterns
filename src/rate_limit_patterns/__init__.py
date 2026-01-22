"""Rate Limit Patterns: Production-ready rate limiting for Python."""

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.backend.sync import SyncLocalBackend, SyncRedisBackend
from rate_limit_patterns.decorators import rate_limit
from rate_limit_patterns.exceptions import (
    RateLimitBackendConfigurationError,
    RateLimitBackendError,
    RateLimitBackendUnavailableError,
    RateLimitExceeded,
)
from rate_limit_patterns.limiter import RateLimiter, SyncRateLimiter
from rate_limit_patterns.models import RateLimitConfig, RateLimitEvent, RateLimitResult

__version__ = "0.1.0"

__all__ = [
    # Core
    "RateLimitConfig",
    "RateLimitEvent",
    "RateLimitResult",
    "RateLimiter",
    "SyncRateLimiter",
    # Backends
    "LocalBackend",
    "RedisBackend",
    "SyncLocalBackend",
    "SyncRedisBackend",
    # Integration
    "rate_limit",
    # Exceptions
    "RateLimitExceeded",
    "RateLimitBackendError",
    "RateLimitBackendUnavailableError",
    "RateLimitBackendConfigurationError",
    # Meta
    "__version__",
]
