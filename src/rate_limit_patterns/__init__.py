"""Rate Limit Patterns: Production-ready rate limiting for Python."""

from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.decorators import rate_limit
from rate_limit_patterns.exceptions import RateLimitExceeded
from rate_limit_patterns.limiter import RateLimiter
from rate_limit_patterns.middleware.asgi import RateLimitMiddleware
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

__version__ = "0.1.0"

__all__ = [
    # Core
    "RateLimitConfig",
    "RateLimitResult",
    "RateLimiter",
    # Backends
    "LocalBackend",
    "RedisBackend",
    # Integration
    "RateLimitMiddleware",
    "rate_limit",
    # Exceptions
    "RateLimitExceeded",
    # Meta
    "__version__",
]
