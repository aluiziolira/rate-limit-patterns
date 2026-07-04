"""Redis backend for rate limiting using Lua scripts."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, cast

from rate_limit_patterns.backend._redis_shared import (
    LUA_SCRIPTS,
    build_script_call,
    decode_key_type,
    hash_metrics,
    iter_missing_scripts,
    load_lua_script,
    parse_script_result,
    zset_metrics,
)
from rate_limit_patterns.backend.keying import has_hash_tag
from rate_limit_patterns.exceptions import (
    RateLimitBackendConfigurationError,
    RateLimitBackendUnavailableError,
)
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

if TYPE_CHECKING:
    from redis.asyncio import Redis as RedisClient

# Backwards-compatible alias; prefer rate_limit_patterns.backend._redis_shared.
_load_lua_script = load_lua_script


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
            for script_name, script_content in iter_missing_scripts(self._script_shas):
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
        if config.algorithm not in LUA_SCRIPTS:
            raise RateLimitBackendConfigurationError(f"Unsupported algorithm: {config.algorithm}")

        if config.algorithm not in self._script_shas:
            await self.initialize()

        sha = self._script_shas.get(config.algorithm)
        if sha is None:
            raise RateLimitBackendConfigurationError(
                "Lua scripts not initialized. Call await RedisBackend.initialize()."
            )

        call = build_script_call(key, config, now, self._apply_prefix)
        if self._cluster_mode and call.multi_key:
            self._validate_cluster_key(call.keys[0])

        redis_client = cast("RedisProtocol", self._redis)
        result = await self._evalsha_with_retry(redis_client, sha, call.keys, call.args, config)
        return parse_script_result(result, config)

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
        for script_name, script_content in iter_missing_scripts(self._script_shas):
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
            key_type = decode_key_type(await redis_client.type(full_key))

            if key_type == "none":
                return {}

            if key_type == "hash":
                state = await redis_client.hmget(
                    full_key, ["tokens", "last_refill", "queue_size", "last_leak"]
                )
                return hash_metrics(full_key, state)

            if key_type == "zset":
                count = int(await redis_client.zcard(full_key))
                oldest: list[Any] = []
                if count > 0:
                    oldest = await redis_client.zrange(full_key, 0, 0, withscores=True)
                return zset_metrics(full_key, count, oldest)
        except RedisError as exc:
            raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc

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
