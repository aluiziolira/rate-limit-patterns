"""Redis backend for rate limiting using Lua scripts."""

from __future__ import annotations

import importlib.resources
from typing import TYPE_CHECKING, Any, cast

from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient

# Lua script names to load
_LUA_SCRIPTS = ("token_bucket", "sliding_window", "leaky_bucket")


# Exposed symbol for patching in tests - this is the factory that tests can mock
def Redis(url: str) -> RedisClient:  # noqa: N802
    """Factory function to create a Redis client.

    This function is exposed as a module-level symbol that tests can patch.
    The actual import is deferred to avoid hard dependency failures.
    """
    import redis.asyncio as redis

    return redis.Redis.from_url(url)  # type: ignore[no-any-return]


class RedisBackend:
    """Redis backend for rate limiting.

    Uses Lua scripts for atomic rate limit operations.
    """

    def __init__(self, url: str, *, key_prefix: str = "") -> None:
        """Initialize the Redis backend.

        Args:
            url: Redis connection URL.
            key_prefix: Optional prefix for all rate limit keys.
        """
        self._url = url
        self._key_prefix = key_prefix
        self._redis: RedisClient | None = None
        self._script_shas: dict[str, str] = {}

    def _ensure_redis(self) -> None:
        """Ensure Redis client is connected (lazy initialization)."""
        if self._redis is None:
            self._redis = Redis(self._url)

    async def initialize(self) -> None:
        """Initialize the Redis connection and load Lua scripts.

        This method can be called multiple times safely.
        """
        if self._redis is not None:
            return

        self._ensure_redis()

        # Load all Lua scripts
        for script_name in _LUA_SCRIPTS:
            script_content = _load_lua_script(script_name)
            redis_client = cast("RedisProtocol", self._redis)
            sha = await redis_client.script_load(script_content)
            self._script_shas[script_name] = sha

    async def check_and_increment(self, key: str, config: RateLimitConfig) -> RateLimitResult:
        """Check and increment the rate limit for a key.

        Args:
            key: Unique identifier for the rate limit.
            config: Rate limit configuration.

        Returns:
            RateLimitResult indicating if the request is allowed.
        """
        self._ensure_redis()

        full_key = f"{self._key_prefix}{key}" if self._key_prefix else key
        sha = self._script_shas.get(config.algorithm)

        if sha is None:
            raise ValueError(f"No script loaded for algorithm: {config.algorithm}")

        # Calculate arguments based on algorithm
        if config.algorithm == "token_bucket":
            tokens_per_second = config.limit / config.period
            args: list[Any] = [
                config.burst_size or config.limit,
                tokens_per_second,
                0,  # current_time (let Redis use TIME)
            ]
        elif config.algorithm == "sliding_window":
            args = [config.limit, config.period, 0]
        elif config.algorithm == "leaky_bucket":
            args = [config.limit, config.tokens_per_second, 0]
        else:
            raise ValueError(f"Unsupported algorithm: {config.algorithm}")

        # Execute the Lua script
        redis_client = cast("RedisProtocol", self._redis)
        result = await redis_client.evalsha(sha, 1, full_key, *args)

        # Parse result: [allowed, remaining, retry_after, reset_at]
        allowed_int = int(result[0])
        remaining = int(result[1])
        retry_after_raw = int(result[2])
        reset_at = float(result[3])

        # Convert retry_after: 0 means None
        retry_after: int | None = None if retry_after_raw == 0 else retry_after_raw

        # Convert allowed to bool
        allowed = bool(allowed_int)

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            limit=config.limit,
            retry_after=retry_after,
            reset_at=reset_at,
        )

    async def reset(self, key: str) -> None:
        """Reset the rate limit state for a key.

        Args:
            key: Unique identifier for the rate limit to reset.
        """
        self._ensure_redis()

        full_key = f"{self._key_prefix}{key}" if self._key_prefix else key
        redis_client = cast("RedisProtocol", self._redis)
        await redis_client.delete(full_key)

    async def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key.

        Args:
            key: Unique identifier to get metrics for.

        Returns:
            Dictionary containing metrics for the key.
        """
        self._ensure_redis()

        full_key = f"{self._key_prefix}{key}" if self._key_prefix else key
        redis_client = cast("RedisProtocol", self._redis)
        state = await redis_client.hmget(
            full_key, ["tokens", "last_refill", "count", "window_start"]
        )

        return {
            "key": full_key,
            "tokens": float(state[0]) if state[0] else None,
            "last_refill": float(state[1]) if state[1] else None,
            "count": int(state[2]) if state[2] else None,
            "window_start": float(state[3]) if state[3] else None,
        }

    async def close(self) -> None:
        """Close the Redis connection.

        Safe no-op if the client doesn't have a close method.
        """
        if self._redis is not None and hasattr(self._redis, "close"):
            await self._redis.close()
            self._redis = None


def _load_lua_script(script_name: str) -> str:
    """Load a Lua script from the lua directory.

    Args:
        script_name: Name of the Lua script (without .lua extension).

    Returns:
        The contents of the Lua script as a string.
    """
    # Use importlib.resources.files() to load the script (Python 3.9+)
    lua_file = importlib.resources.files("rate_limit_patterns.backend.lua").joinpath(
        f"{script_name}.lua"
    )
    return lua_file.read_text()


# Protocol for Redis client methods used by this backend
if TYPE_CHECKING:

    class RedisProtocol:
        """Protocol for Redis client methods used by this backend."""

        def script_load(self, script: str, /) -> Any: ...
        def evalsha(self, sha: str, num_keys: int, *args: Any) -> Any: ...
        def delete(self, *keys: str) -> Any: ...
        def hmget(self, key: str, fields: list[str], /) -> Any: ...
        async def close(self) -> None: ...

else:
    RedisProtocol = Any
