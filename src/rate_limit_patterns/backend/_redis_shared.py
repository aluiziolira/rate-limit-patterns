"""Shared Redis command construction and result parsing.

Pure helpers used by both the async ``RedisBackend`` and the synchronous
``SyncRedisBackend`` so the Lua-facing wire format lives in one place.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from rate_limit_patterns.exceptions import RateLimitBackendConfigurationError
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

LUA_SCRIPTS = ("token_bucket", "sliding_window", "leaky_bucket")
REDIS_TIME_SENTINEL = -1

HASH_METRIC_FIELDS = ("tokens", "last_refill", "queue_size", "last_leak")


def load_lua_script(script_name: str) -> str:
    """Load a Lua script from the lua directory.

    Args:
        script_name: Name of the Lua script (without .lua extension).

    Returns:
        The contents of the Lua script as a string.
    """
    lua_file = importlib.resources.files("rate_limit_patterns.backend.lua").joinpath(
        f"{script_name}.lua"
    )
    return lua_file.read_text()


def iter_missing_scripts(loaded: dict[str, str]) -> Iterator[tuple[str, str]]:
    """Yield (name, content) for Lua scripts not yet present in ``loaded``."""
    for script_name in LUA_SCRIPTS:
        if script_name not in loaded:
            yield script_name, load_lua_script(script_name)


@dataclass(frozen=True, slots=True)
class ScriptCall:
    """A prepared EVALSHA invocation for one rate limit check."""

    keys: list[str]
    args: list[Any]
    multi_key: bool


def build_script_call(
    key: str,
    config: RateLimitConfig,
    now: float | None,
    apply_prefix: Callable[[str], str],
) -> ScriptCall:
    """Build the KEYS/ARGV payload for the algorithm's Lua script.

    Args:
        key: Unprefixed rate limit key.
        config: Rate limit configuration.
        now: Optional Unix timestamp override; None means "use Redis TIME".
        apply_prefix: Backend's key-prefix function.

    Raises:
        RateLimitBackendConfigurationError: For unsupported algorithms.
    """
    current_time = REDIS_TIME_SENTINEL if now is None else now
    if config.algorithm == "token_bucket":
        args: list[Any] = [
            config.burst_size or config.limit,
            config.tokens_per_second,
            current_time,
        ]
        return ScriptCall(keys=[apply_prefix(key)], args=args, multi_key=False)
    if config.algorithm == "sliding_window":
        args = [config.limit, config.period, current_time]
        keys = [apply_prefix(key), apply_prefix(f"{key}:seq")]
        return ScriptCall(keys=keys, args=args, multi_key=True)
    if config.algorithm == "leaky_bucket":
        capacity = config.burst_size or config.limit
        args = [capacity, config.tokens_per_second, current_time]
        return ScriptCall(keys=[apply_prefix(key)], args=args, multi_key=False)
    raise RateLimitBackendConfigurationError(f"Unsupported algorithm: {config.algorithm}")


def parse_script_result(result: list[Any], config: RateLimitConfig) -> RateLimitResult:
    """Parse a Lua script reply [allowed, remaining, retry_after, reset_at, request_count]."""
    allowed = bool(int(result[0]))
    retry_after_raw = int(result[2])
    retry_after: int | None = None
    if not allowed and retry_after_raw != 0:
        retry_after = retry_after_raw
    return RateLimitResult(
        allowed=allowed,
        remaining=int(result[1]),
        limit=config.limit,
        retry_after=retry_after,
        reset_at=float(result[3]),
        request_count=int(result[4]) if len(result) > 4 else 0,
    )


def decode_key_type(key_type_raw: Any) -> str:
    """Normalize a Redis TYPE reply (bytes or str) to a string."""
    if isinstance(key_type_raw, (bytes, bytearray)):
        return key_type_raw.decode("utf-8")
    return str(key_type_raw)


def hash_metrics(full_key: str, state: list[Any]) -> dict[str, Any]:
    """Build the metrics payload for hash-backed state (token/leaky bucket)."""
    metrics: dict[str, Any] = {"key": full_key, "storage_type": "hash"}
    for field, value in zip(HASH_METRIC_FIELDS, state, strict=False):
        metrics[field] = float(value) if value else None
    return metrics


def zset_metrics(full_key: str, count: int, oldest: list[Any]) -> dict[str, Any]:
    """Build the metrics payload for zset-backed state (sliding window)."""
    window_start: float | None = None
    if oldest:
        window_start = float(oldest[0][1]) / 1000
    return {
        "key": full_key,
        "storage_type": "zset",
        "count": count,
        "window_start": window_start,
    }
