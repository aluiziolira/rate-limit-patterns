"""Synchronous backend implementations for rate limiting."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from rate_limit_patterns.algorithms.base import RateLimitAlgorithm
from rate_limit_patterns.algorithms.leaky_bucket import LeakyBucketAlgorithm
from rate_limit_patterns.algorithms.sliding_window import SlidingWindowAlgorithm
from rate_limit_patterns.algorithms.token_bucket import TokenBucketAlgorithm
from rate_limit_patterns.backend._redis_shared import (
    LUA_SCRIPTS,
    build_script_call,
    decode_key_type,
    hash_metrics,
    iter_missing_scripts,
    parse_script_result,
    zset_metrics,
)
from rate_limit_patterns.exceptions import (
    RateLimitBackendConfigurationError,
    RateLimitBackendUnavailableError,
)
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig, RateLimitResult

_LOCK_STRIPES = 64
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _LocalEntry:
    state: dict[str, Any]
    expires_at: float


class SyncLocalBackend:
    """Synchronous in-memory rate limit backend using striped locks."""

    def __init__(self) -> None:
        """Initialize the synchronous local backend."""
        self._locks = [threading.Lock() for _ in range(_LOCK_STRIPES)]
        self._cleanup_lock = threading.Lock()
        self._cleanup_interval: float | None = None
        self._cleanup_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._wakeup_event = threading.Event()
        self._state: dict[str, _LocalEntry] = {}
        self._algorithms: dict[AlgorithmType, RateLimitAlgorithm] = {
            "token_bucket": TokenBucketAlgorithm(),
            "sliding_window": SlidingWindowAlgorithm(),
            "leaky_bucket": LeakyBucketAlgorithm(),
        }
        self._time_offset = time.time() - time.monotonic()

    def initialize(self) -> None:
        """Start background cleanup thread."""
        if self._cleanup_thread is not None and self._cleanup_thread.is_alive():
            return
        self._stop_event.clear()
        self._wakeup_event.clear()
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_loop,
            name="rate-limit-sync-local-cleanup",
            daemon=True,
        )
        self._cleanup_thread.start()

    def close(self) -> None:
        """Stop background cleanup thread."""
        if self._cleanup_thread is None:
            return
        self._stop_event.set()
        self._wakeup_event.set()
        self._cleanup_thread.join()
        self._cleanup_thread = None

    def check_and_increment(
        self,
        key: str,
        config: RateLimitConfig,
        *,
        now: float | None = None,
    ) -> RateLimitResult:
        """Check and increment the rate limit counter for a key."""
        algorithm = self._algorithms.get(config.algorithm)
        if algorithm is None:
            msg = (
                f"Unknown algorithm: {config.algorithm}. "
                f"Supported algorithms: {list(self._algorithms.keys())}"
            )
            raise ValueError(msg)

        now_mono, now_wall = self._now(now)
        self._update_cleanup_interval(config.cleanup_interval)

        lock = self._lock_for_key(key)
        with lock:
            entry = self._state.get(key)
            if entry is None or entry.expires_at <= now_mono:
                state = algorithm.initial_state(config)
            else:
                state = entry.state

            allowed, new_state, metadata = algorithm.compute(state, config, now_mono)
            expires_at = now_mono + self._ttl_for(config)
            self._state[key] = _LocalEntry(state=new_state, expires_at=expires_at)

        reset_at = self._to_wall_time(metadata.get("reset_at"), now_mono, now_wall)
        return RateLimitResult(
            allowed=allowed,
            remaining=metadata["remaining"],
            limit=config.limit,
            retry_after=metadata.get("retry_after"),
            reset_at=reset_at,
            request_count=metadata.get("request_count", 0),
        )

    def reset(self, key: str) -> None:
        """Reset the rate limit state for a key."""
        lock = self._lock_for_key(key)
        with lock:
            self._state.pop(key, None)

    def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key."""
        now_mono, _ = self._now(None)
        lock = self._lock_for_key(key)
        with lock:
            entry = self._state.get(key)
            if entry is None or entry.expires_at <= now_mono:
                self._state.pop(key, None)
                return {}
            return dict(entry.state)

    def _lock_for_key(self, key: str) -> threading.Lock:
        return self._locks[hash(key) % len(self._locks)]

    def _ttl_for(self, config: RateLimitConfig) -> float:
        if config.algorithm == "sliding_window":
            ttl = float(config.period)
        else:
            capacity = config.burst_size if config.burst_size is not None else config.limit
            rate = config.tokens_per_second
            ttl = capacity / rate if rate > 0 else 1.0
        return max(1.0, ttl)

    def _now(self, now: float | None) -> tuple[float, float]:
        if now is None:
            now_mono = time.monotonic()
            now_wall = self._time_offset + now_mono
        else:
            now_wall = now
            now_mono = now - self._time_offset
        return now_mono, now_wall

    @staticmethod
    def _to_wall_time(reset_at: float | None, now_mono: float, now_wall: float) -> float | None:
        if reset_at is None:
            return None
        return now_wall + (reset_at - now_mono)

    def _update_cleanup_interval(self, cleanup_interval: float) -> None:
        if cleanup_interval <= 0:
            return
        if self._cleanup_interval is None or cleanup_interval < self._cleanup_interval:
            self._cleanup_interval = cleanup_interval
            self._wakeup_event.set()

    def _cleanup_loop(self) -> None:
        while not self._stop_event.is_set():
            interval = self._cleanup_interval
            if interval is None or interval <= 0:
                self._wakeup_event.wait()
                self._wakeup_event.clear()
                continue
            if self._wakeup_event.wait(interval):
                self._wakeup_event.clear()
                continue
            if self._stop_event.is_set():
                return
            now_mono = time.monotonic()
            try:
                self._cleanup_expired(now_mono)
            except Exception:
                logger.debug("Cleanup iteration failed", exc_info=True)
                continue

    def _cleanup_expired(self, now_mono: float) -> None:
        with self._cleanup_lock:
            for key in list(self._state.keys()):
                lock = self._lock_for_key(key)
                with lock:
                    entry = self._state.get(key)
                    if entry is not None and entry.expires_at <= now_mono:
                        self._state.pop(key, None)


class SyncRedisBackend:
    """Synchronous Redis backend for rate limiting."""

    def __init__(self, *, client: SyncRedisProtocol, key_prefix: str = "") -> None:
        """Initialize the synchronous Redis backend.

        Args:
            client: Pre-configured synchronous Redis client.
            key_prefix: Optional prefix applied to all rate limit keys.
        """
        self._redis = client
        self._key_prefix = key_prefix
        self._script_shas: dict[str, str] = {}
        self._init_lock = threading.Lock()

    def _apply_prefix(self, key: str) -> str:
        if not self._key_prefix:
            return key
        return f"{self._key_prefix}{key}"

    @property
    def key_prefix(self) -> str:
        return self._key_prefix

    def initialize(self) -> None:
        """Load Lua scripts into Redis."""
        from redis.exceptions import RedisError

        with self._init_lock:
            for script_name, script_content in iter_missing_scripts(self._script_shas):
                try:
                    sha = self._redis.script_load(script_content)
                except RedisError as exc:
                    raise RateLimitBackendUnavailableError(
                        "Failed to load Redis Lua scripts."
                    ) from exc
                self._script_shas[script_name] = sha

    def check_and_increment(
        self,
        key: str,
        config: RateLimitConfig,
        *,
        now: float | None = None,
    ) -> RateLimitResult:
        """Check and increment the rate limit for a key."""
        if config.algorithm not in LUA_SCRIPTS:
            raise RateLimitBackendConfigurationError(f"Unsupported algorithm: {config.algorithm}")

        if config.algorithm not in self._script_shas:
            self.initialize()

        sha = self._script_shas.get(config.algorithm)
        if sha is None:
            raise RateLimitBackendConfigurationError(
                "Lua scripts not initialized. Call SyncRedisBackend.initialize()."
            )

        call = build_script_call(key, config, now, self._apply_prefix)
        result = self._evalsha_with_retry(sha, call.keys, call.args, config)
        return parse_script_result(result, config)

    def _evalsha_with_retry(
        self,
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
            return cast(list[Any], self._redis.evalsha(sha, len(keys), *keys, *args))
        except NoScriptError as exc:
            self._reload_scripts()
            new_sha = self._script_shas.get(config.algorithm)
            if new_sha is None:
                raise RateLimitBackendConfigurationError(
                    "Lua scripts not initialized after reload."
                ) from exc
            return cast(list[Any], self._redis.evalsha(new_sha, len(keys), *keys, *args))
        except (RedisConnectionError, RedisTimeoutError, RedisError) as exc:
            raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc

    def _reload_scripts(self) -> None:
        from redis.exceptions import RedisError

        self._script_shas.clear()
        for script_name, script_content in iter_missing_scripts(self._script_shas):
            try:
                sha = self._redis.script_load(script_content)
            except RedisError as exc:
                raise RateLimitBackendUnavailableError(
                    "Failed to reload Redis Lua scripts."
                ) from exc
            self._script_shas[script_name] = sha

    def reset(self, key: str) -> None:
        """Reset the rate limit state for a key."""
        full_key = self._apply_prefix(key)
        from redis.exceptions import RedisError

        try:
            self._redis.delete(full_key)
        except RedisError as exc:
            raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc

    def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key."""
        full_key = self._apply_prefix(key)
        from redis.exceptions import RedisError

        try:
            key_type = decode_key_type(self._redis.type(full_key))

            if key_type == "none":
                return {}

            if key_type == "hash":
                state = self._redis.hmget(
                    full_key, ["tokens", "last_refill", "queue_size", "last_leak"]
                )
                return hash_metrics(full_key, state)

            if key_type == "zset":
                count = int(self._redis.zcard(full_key))
                oldest: list[Any] = []
                if count > 0:
                    oldest = self._redis.zrange(full_key, 0, 0, withscores=True)
                return zset_metrics(full_key, count, oldest)
        except RedisError as exc:
            raise RateLimitBackendUnavailableError("Redis backend unavailable.") from exc

        return {"key": full_key, "storage_type": key_type}

    def close(self) -> None:
        """Close the Redis connection."""
        if hasattr(self._redis, "close"):
            self._redis.close()


if TYPE_CHECKING:

    class SyncRedisProtocol:
        """Protocol for synchronous Redis client methods used by this backend."""

        def script_load(self, script: str, /) -> Any: ...
        def evalsha(self, sha: str, num_keys: int, *args: Any) -> Any: ...
        def delete(self, *keys: str) -> Any: ...
        def hmget(self, key: str, fields: list[str], /) -> Any: ...
        def type(self, key: str, /) -> Any: ...
        def zcard(self, key: str, /) -> Any: ...
        def zrange(self, key: str, start: int, end: int, /, withscores: bool = False) -> Any: ...
        def close(self) -> None: ...

else:
    SyncRedisProtocol = Any
