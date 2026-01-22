"""Redis backend for rate limiting using Lua scripts."""

from __future__ import annotations

import asyncio
import importlib.resources
from typing import TYPE_CHECKING, Any, cast

from rate_limit_patterns.backend.keying import has_hash_tag
from rate_limit_patterns.exceptions import (
    RateLimitBackendConfigurationError,
    RateLimitBackendUnavailableError,
)
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient

# Lua script names to load
_LUA_SCRIPTS = ("token_bucket", "sliding_window", "leaky_bucket")
_REDIS_TIME_SENTINEL = -1


# Exposed symbol for patching in tests - this is the factory that tests can mock
def Redis(url: str, **kwargs: Any) -> RedisClient:  # noqa: N802
    """Factory function to create a Redis client.

    This function is exposed as a module-level symbol that tests can patch.
    The actual import is deferred to avoid hard dependency failures.
    """
    import redis.asyncio as redis

    return redis.Redis.from_url(url, **kwargs)  # type: ignore[no-any-return]


class RedisBackend:
    """Redis backend for rate limiting.

    Uses Lua scripts for atomic rate limit operations.
    """

    def __init__(
        self,
        url: str | None = None,
        *,
        client: RedisProtocol | None = None,
        key_prefix: str = "",
        cluster_mode: bool = False,
        socket_timeout: float | None = None,
        socket_connect_timeout: float | None = None,
        max_connections: int | None = None,
        socket_keepalive: bool | None = None,
        health_check_interval: float | None = None,
    ) -> None:
        """Initialize the Redis backend.

        Args:
            url: Redis connection URL (ignored when client is provided).
            client: Optional pre-configured Redis client (e.g., RedisCluster).
            key_prefix: Optional prefix applied to all rate limit keys.
            cluster_mode: When True, enforce Redis Cluster hash-tag compatibility.
            socket_timeout: Optional Redis socket timeout in seconds.
            socket_connect_timeout: Optional Redis connect timeout in seconds.
            max_connections: Optional max Redis connections for URL-based clients.
            socket_keepalive: Optional keepalive toggle for URL-based clients.
            health_check_interval: Optional health check interval for URL-based clients.
        """
        self._url = url
        self._key_prefix = key_prefix
        self._cluster_mode = cluster_mode
        self._socket_timeout = socket_timeout
        self._socket_connect_timeout = socket_connect_timeout
        self._max_connections = max_connections
        self._socket_keepalive = socket_keepalive
        self._health_check_interval = health_check_interval
        self._redis: RedisProtocol | None = None
        self._owns_client = client is None
        if client is not None:
            self._redis = client
        self._script_shas: dict[str, str] = {}
        self._init_lock = asyncio.Lock()

    def _apply_prefix(self, key: str) -> str:
        """Apply the configured key prefix."""
        if not self._key_prefix:
            return key
        return f"{self._key_prefix}{key}"

    @property
    def key_prefix(self) -> str:
        """Return the configured key prefix."""
        return self._key_prefix

    def _validate_cluster_key(self, key: str) -> None:
        if not has_hash_tag(key):
            raise RateLimitBackendConfigurationError(
                "Redis Cluster mode requires a hash tag in the key (e.g., rate:{user}:window)."
            )

    def _ensure_redis(self) -> None:
        """Ensure Redis client is connected (lazy initialization)."""
        if self._redis is None:
            if self._url is None:
                raise RateLimitBackendConfigurationError(
                    "Redis backend requires either a url or a pre-configured client."
                )
            kwargs: dict[str, Any] = {}
            if self._socket_timeout is not None:
                kwargs["socket_timeout"] = self._socket_timeout
            if self._socket_connect_timeout is not None:
                kwargs["socket_connect_timeout"] = self._socket_connect_timeout
            if self._max_connections is not None:
                kwargs["max_connections"] = self._max_connections
            if self._socket_keepalive is not None:
                kwargs["socket_keepalive"] = self._socket_keepalive
            if self._health_check_interval is not None:
                kwargs["health_check_interval"] = self._health_check_interval
            self._redis = cast("RedisProtocol", Redis(self._url, **kwargs))

    async def initialize(self) -> None:
        """Initialize the Redis connection and load Lua scripts.

        This method can be called multiple times safely.
        """
        self._ensure_redis()
        redis_client = cast("RedisProtocol", self._redis)
        from redis.exceptions import RedisError

        async with self._init_lock:
            # Load all Lua scripts (idempotent)
            for script_name in _LUA_SCRIPTS:
                if script_name in self._script_shas:
                    continue
                script_content = _load_lua_script(script_name)
                try:
                    sha = await redis_client.script_load(script_content)
                except RedisError as exc:
                    raise RateLimitBackendUnavailableError(
                        "Failed to load Redis Lua scripts."
                    ) from exc
                self._script_shas[script_name] = sha

    async def check_and_increment(
        self,
        key: str,
        config: RateLimitConfig,
        *,
        now: float | None = None,
    ) -> RateLimitResult:
        """Check and increment the rate limit for a key.

        Args:
            key: Unique identifier for the rate limit.
            config: Rate limit configuration.
            now: Optional Unix timestamp override for deterministic tests.

        Returns:
            RateLimitResult indicating if the request is allowed.
        """
        self._ensure_redis()
        if config.algorithm not in _LUA_SCRIPTS:
            raise RateLimitBackendConfigurationError(f"Unsupported algorithm: {config.algorithm}")

        if config.algorithm not in self._script_shas:
            await self.initialize()

        sha = self._script_shas.get(config.algorithm)
        if sha is None:
            raise RateLimitBackendConfigurationError(
                "Lua scripts not initialized. Call await RedisBackend.initialize()."
            )

        # Calculate arguments based on algorithm
        current_time = _REDIS_TIME_SENTINEL if now is None else now
        if config.algorithm == "token_bucket":
            tokens_per_second = config.tokens_per_second
            args: list[Any] = [
                config.burst_size or config.limit,
                tokens_per_second,
                current_time,
            ]
            keys = [self._apply_prefix(key)]
        elif config.algorithm == "sliding_window":
            window_key = self._apply_prefix(key)
            if self._cluster_mode:
                self._validate_cluster_key(window_key)
            args = [config.limit, config.period, current_time]
            seq_key = self._apply_prefix(f"{key}:seq")
            keys = [window_key, seq_key]
        elif config.algorithm == "leaky_bucket":
            capacity = config.burst_size or config.limit
            args = [capacity, config.tokens_per_second, current_time]
            keys = [self._apply_prefix(key)]
        else:
            raise RateLimitBackendConfigurationError(f"Unsupported algorithm: {config.algorithm}")

        redis_client = cast("RedisProtocol", self._redis)
        result = await self._evalsha_with_retry(redis_client, sha, keys, args, config)

        # Parse result: [allowed, remaining, retry_after, reset_at, request_count]
        allowed_int = int(result[0])
        remaining = int(result[1])
        retry_after_raw = int(result[2])
        reset_at = float(result[3])
        request_count = int(result[4]) if len(result) > 4 else 0

        allowed = bool(allowed_int)
        retry_after: int | None = None
        if not allowed:
            retry_after = None if retry_after_raw == 0 else retry_after_raw

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            limit=config.limit,
            retry_after=retry_after,
            reset_at=reset_at,
            request_count=request_count,
        )

    async def _evalsha_with_retry(
        self,
        redis_client: RedisProtocol,
        sha: str,
        keys: list[str],
        args: list[Any],
        config: RateLimitConfig,
    ) -> list[Any]:
        from redis.exceptions import (
            ConnectionError as RedisConnectionError,
        )
        from redis.exceptions import (
            NoScriptError,
            RedisError,
        )
        from redis.exceptions import (
            TimeoutError as RedisTimeoutError,
        )

        try:
            return cast(list[Any], await redis_client.evalsha(sha, len(keys), *keys, *args))
        except NoScriptError as exc:
            await self._reload_scripts(redis_client)
            new_sha = self._script_shas.get(config.algorithm)
            if new_sha is None:
                raise RateLimitBackendConfigurationError(
                    "Lua scripts not initialized after reload."
                ) from exc
            return cast(list[Any], await redis_client.evalsha(new_sha, len(keys), *keys, *args))
        except (RedisConnectionError, RedisTimeoutError, RedisError) as exc:
            raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc

    async def _reload_scripts(self, redis_client: RedisProtocol) -> None:
        from redis.exceptions import RedisError

        self._script_shas.clear()
        for script_name in _LUA_SCRIPTS:
            script_content = _load_lua_script(script_name)
            try:
                sha = await redis_client.script_load(script_content)
            except RedisError as exc:
                raise RateLimitBackendUnavailableError(
                    "Failed to reload Redis Lua scripts."
                ) from exc
            self._script_shas[script_name] = sha

    async def reset(self, key: str) -> None:
        """Reset the rate limit state for a key.

        Args:
            key: Unique identifier for the rate limit to reset.
        """
        self._ensure_redis()

        full_key = self._apply_prefix(key)
        redis_client = cast("RedisProtocol", self._redis)
        from redis.exceptions import RedisError

        try:
            await redis_client.delete(full_key)
        except RedisError as exc:
            raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc

    async def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key.

        Args:
            key: Unique identifier to get metrics for.

        Returns:
            Dictionary containing metrics for the key. Fields depend on the
            underlying Redis data type (hash for token/leaky buckets, zset for
            sliding window).
        """
        self._ensure_redis()

        full_key = self._apply_prefix(key)
        redis_client = cast("RedisProtocol", self._redis)
        from redis.exceptions import RedisError

        try:
            key_type_raw = await redis_client.type(full_key)
            if isinstance(key_type_raw, (bytes, bytearray)):
                key_type = key_type_raw.decode("utf-8")
            else:
                key_type = str(key_type_raw)
        except RedisError as exc:
            raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc

        if key_type == "none":
            return {}

        if key_type == "hash":
            try:
                state = await redis_client.hmget(
                    full_key, ["tokens", "last_refill", "queue_size", "last_leak"]
                )
            except RedisError as exc:
                raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc
            return {
                "key": full_key,
                "storage_type": "hash",
                "tokens": float(state[0]) if state[0] else None,
                "last_refill": float(state[1]) if state[1] else None,
                "queue_size": float(state[2]) if state[2] else None,
                "last_leak": float(state[3]) if state[3] else None,
            }

        if key_type == "zset":
            try:
                count = int(await redis_client.zcard(full_key))
            except RedisError as exc:
                raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc
            window_start: float | None = None
            if count > 0:
                try:
                    oldest = await redis_client.zrange(full_key, 0, 0, withscores=True)
                except RedisError as exc:
                    raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc
                if oldest:
                    window_start = float(oldest[0][1]) / 1000
            return {
                "key": full_key,
                "storage_type": "zset",
                "count": count,
                "window_start": window_start,
            }

        return {"key": full_key, "storage_type": key_type}

    async def close(self) -> None:
        """Close the Redis connection.

        Safe no-op if the client doesn't have a close method.
        """
        if not self._owns_client:
            return
        if self._redis is not None and hasattr(self._redis, "aclose"):
            await self._redis.aclose()
            self._redis = None
        elif self._redis is not None and hasattr(self._redis, "close"):
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
        def type(self, key: str, /) -> Any: ...
        def zcard(self, key: str, /) -> Any: ...
        def zrange(self, key: str, start: int, end: int, /, withscores: bool = False) -> Any: ...
        async def aclose(self) -> None: ...
        async def close(self) -> None: ...

else:
    RedisProtocol = Any
