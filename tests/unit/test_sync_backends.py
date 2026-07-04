"""Unit tests for synchronous backends."""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import NoScriptError, RedisError
from redis.exceptions import TimeoutError as RedisTimeoutError

from rate_limit_patterns.backend.sync import SyncLocalBackend, SyncRedisBackend, _LocalEntry
from rate_limit_patterns.exceptions import (
    RateLimitBackendConfigurationError,
    RateLimitBackendUnavailableError,
)
from rate_limit_patterns.limiter import SyncRateLimiter
from rate_limit_patterns.models import RateLimitConfig


def test_sync_local_backend_allows_and_resets() -> None:
    """SyncLocalBackend supports basic check and reset."""
    backend = SyncLocalBackend()
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=100,
        period=60,
        burst_size=200,
    )

    backend.initialize()
    result = backend.check_and_increment("user:1", config)
    assert result.allowed is True
    backend.reset("user:1")
    result = backend.check_and_increment("user:1", config)
    assert result.remaining == 199
    backend.close()


def test_sync_local_close_without_thread_is_noop() -> None:
    """close() is safe before initialize()."""
    backend = SyncLocalBackend()

    backend.close()


def test_sync_local_initialize_idempotent() -> None:
    """initialize() returns early when thread already running."""
    backend = SyncLocalBackend()

    backend.initialize()
    first_thread = backend._cleanup_thread
    backend.initialize()
    second_thread = backend._cleanup_thread

    assert first_thread is second_thread
    backend.close()


def test_sync_local_unknown_algorithm_raises() -> None:
    """Unknown algorithms raise ValueError."""
    backend = SyncLocalBackend()
    config = RateLimitConfig(  # type: ignore[arg-type]
        algorithm="unknown",
        limit=1,
        period=1,
    )

    with pytest.raises(ValueError, match="Unknown algorithm"):
        backend.check_and_increment("user:1", config)


def test_sync_local_get_metrics_expired_entry_clears() -> None:
    """Expired entries are removed during metrics lookup."""
    backend = SyncLocalBackend()
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )

    backend.check_and_increment("user:expired", config, now=time.time() - 3600)
    metrics = backend.get_metrics("user:expired")

    assert metrics == {}
    assert "user:expired" not in backend._state


def test_sync_local_update_cleanup_interval_ignores_non_positive() -> None:
    """Non-positive cleanup intervals are ignored."""
    backend = SyncLocalBackend()

    backend._update_cleanup_interval(0)

    assert backend._cleanup_interval is None


def test_sync_local_cleanup_expired_removes_keys() -> None:
    """cleanup_expired removes only expired keys."""
    backend = SyncLocalBackend()
    now_mono = time.monotonic()
    backend._state["expired"] = _LocalEntry(state={}, expires_at=now_mono - 1)
    backend._state["active"] = _LocalEntry(state={}, expires_at=now_mono + 10)

    backend._cleanup_expired(now_mono)

    assert "expired" not in backend._state
    assert "active" in backend._state


class _StopSequence:
    def __init__(self, sequence: list[bool]) -> None:
        self._values = iter(sequence)

    def is_set(self) -> bool:
        return next(self._values, True)


def test_sync_local_cleanup_loop_waits_without_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup loop waits for wakeup event when no interval is set."""
    backend = SyncLocalBackend()
    backend._cleanup_interval = None
    backend._stop_event = _StopSequence([False, True])  # type: ignore[assignment]

    waited: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        backend._wakeup_event,
        "wait",
        lambda *args, **kwargs: waited.append(args) or True,
    )
    cleared: list[bool] = []
    monkeypatch.setattr(
        backend._wakeup_event,
        "clear",
        lambda: cleared.append(True),
    )

    backend._cleanup_loop()

    assert waited
    assert cleared


def test_sync_local_cleanup_loop_runs_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup loop calls cleanup when interval elapses."""
    backend = SyncLocalBackend()
    backend._cleanup_interval = 0.01
    backend._stop_event = _StopSequence([False, False, True])  # type: ignore[assignment]

    monkeypatch.setattr(backend._wakeup_event, "wait", lambda timeout=None: False)
    called: list[bool] = []
    monkeypatch.setattr(backend, "_cleanup_expired", lambda _: called.append(True))

    backend._cleanup_loop()

    assert called


def test_sync_local_cleanup_loop_handles_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """cleanup loop swallows transient exceptions."""
    backend = SyncLocalBackend()
    backend._cleanup_interval = 0.01
    backend._stop_event = _StopSequence([False, False, True])  # type: ignore[assignment]

    monkeypatch.setattr(backend._wakeup_event, "wait", lambda timeout=None: False)

    def _boom(_: float) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(backend, "_cleanup_expired", _boom)

    backend._cleanup_loop()


def test_sync_local_sliding_window_uses_period() -> None:
    """Sliding window TTL uses period seconds."""
    backend = SyncLocalBackend()
    config = RateLimitConfig(
        algorithm="sliding_window",
        limit=5,
        period=10,
    )

    ttl = backend._core._ttl_for(config)

    assert ttl == 10.0


def test_sync_local_now_and_reset_time_conversion() -> None:
    """_now and _to_wall_time behave deterministically with overrides."""
    backend = SyncLocalBackend()
    now_wall = time.time()
    now_mono, now_wall_result = backend._core.now(now_wall)

    assert now_wall_result == now_wall
    assert backend._core._to_wall_time(None, now_mono, now_wall_result) is None


def test_sync_rate_limiter_facade() -> None:
    """SyncRateLimiter delegates to backend and applies prefixes."""
    backend = SyncLocalBackend()
    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=10,
        period=60,
        burst_size=10,
    )

    with SyncRateLimiter(backend=backend, config=config, key_prefix="user:") as limiter:
        result = limiter.check("123")
        assert result.allowed is True


def test_sync_redis_backend_uses_evalsha() -> None:
    """SyncRedisBackend uses evalsha on the provided client."""
    mock_redis = MagicMock()
    mock_redis.evalsha.return_value = [1, 199, 0, 1705680000, 1]

    backend = SyncRedisBackend(client=mock_redis)
    backend._script_shas = {"token_bucket": "fake_sha"}

    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=100,
        period=60,
        burst_size=200,
    )

    result = backend.check_and_increment("user:123", config)

    assert result.allowed is True
    assert mock_redis.evalsha.called


def test_sync_redis_sliding_window_uses_two_keys() -> None:
    """Sliding window passes window and sequence keys to evalsha."""
    mock_redis = MagicMock()
    mock_redis.evalsha.return_value = [1, 2, 0, 1705680000, 1]

    backend = SyncRedisBackend(client=mock_redis, key_prefix="rl:")
    backend._script_shas = {"sliding_window": "fake_sha"}

    config = RateLimitConfig(
        algorithm="sliding_window",
        limit=5,
        period=60,
    )

    backend.check_and_increment("user:123", config)

    args = mock_redis.evalsha.call_args[0]
    assert args[1] == 2
    assert args[2] == "rl:user:123"
    assert args[3] == "rl:user:123:seq"


def test_sync_redis_initialize_loads_scripts() -> None:
    """initialize loads and caches Lua scripts."""
    mock_redis = MagicMock()
    mock_redis.script_load.return_value = "sha"

    backend = SyncRedisBackend(client=mock_redis)
    backend.initialize()

    assert mock_redis.script_load.call_count == 3
    assert "token_bucket" in backend._script_shas


def test_sync_redis_initialize_raises_on_error() -> None:
    """initialize translates RedisError into backend error."""
    mock_redis = MagicMock()
    mock_redis.script_load.side_effect = RedisError("boom")

    backend = SyncRedisBackend(client=mock_redis)

    with pytest.raises(RateLimitBackendUnavailableError):
        backend.initialize()


def test_sync_redis_check_unsupported_algorithm_raises() -> None:
    """Unsupported algorithms are rejected."""
    mock_redis = MagicMock()
    backend = SyncRedisBackend(client=mock_redis)
    config = RateLimitConfig(  # type: ignore[arg-type]
        algorithm="unknown",
        limit=1,
        period=1,
    )

    with pytest.raises(RateLimitBackendConfigurationError):
        backend.check_and_increment("user:1", config)


def test_sync_redis_check_raises_when_sha_missing_after_initialize() -> None:
    """Missing script SHA after initialize raises configuration error."""
    mock_redis = MagicMock()
    backend = SyncRedisBackend(client=mock_redis)

    backend.initialize = MagicMock()  # type: ignore[method-assign]

    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )

    with pytest.raises(RateLimitBackendConfigurationError):
        backend.check_and_increment("user:1", config)

    assert backend.initialize.called


def test_sync_redis_retry_after_none_when_zero() -> None:
    """retry_after is None when Redis reports 0 seconds."""
    mock_redis = MagicMock()
    mock_redis.evalsha.return_value = [0, 0, 0, 1700000000, 0]

    backend = SyncRedisBackend(client=mock_redis)
    backend._script_shas = {"token_bucket": "sha"}

    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )

    result = backend.check_and_increment("user:1", config)

    assert result.allowed is False
    assert result.retry_after is None


def test_sync_redis_evalsha_recovers_from_noscript() -> None:
    """NOSCRIPT triggers reload and retry."""
    mock_redis = MagicMock()
    mock_redis.evalsha.side_effect = [
        NoScriptError("missing"),
        [1, 1, 0, 1700000000, 1],
    ]
    mock_redis.script_load.return_value = "new_sha"

    backend = SyncRedisBackend(client=mock_redis)
    backend._script_shas = {"token_bucket": "stale_sha"}

    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )

    result = backend.check_and_increment("user:1", config)

    assert result.allowed is True
    assert mock_redis.evalsha.call_count == 2


def test_sync_redis_evalsha_translates_connection_errors() -> None:
    """Connection errors are mapped to backend-unavailable errors."""
    mock_redis = MagicMock()
    mock_redis.evalsha.side_effect = RedisConnectionError("down")

    backend = SyncRedisBackend(client=mock_redis)
    backend._script_shas = {"token_bucket": "sha"}

    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )

    with pytest.raises(RateLimitBackendUnavailableError):
        backend.check_and_increment("user:1", config)


def test_sync_redis_evalsha_translates_timeout_errors() -> None:
    """Timeout errors are mapped to backend-unavailable errors."""
    mock_redis = MagicMock()
    mock_redis.evalsha.side_effect = RedisTimeoutError("timeout")

    backend = SyncRedisBackend(client=mock_redis)
    backend._script_shas = {"token_bucket": "sha"}

    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )

    with pytest.raises(RateLimitBackendUnavailableError):
        backend.check_and_increment("user:1", config)


def test_sync_redis_reload_scripts_error() -> None:
    """Reloading scripts propagates Redis errors."""
    mock_redis = MagicMock()
    mock_redis.script_load.side_effect = RedisError("boom")

    backend = SyncRedisBackend(client=mock_redis)

    with pytest.raises(RateLimitBackendUnavailableError):
        backend._reload_scripts()


def test_sync_redis_reset_raises_on_error() -> None:
    """reset translates delete errors."""
    mock_redis = MagicMock()
    mock_redis.delete.side_effect = RedisError("boom")

    backend = SyncRedisBackend(client=mock_redis)

    with pytest.raises(RateLimitBackendUnavailableError):
        backend.reset("user:1")


def test_sync_redis_get_metrics_none_returns_empty() -> None:
    """get_metrics returns empty dict for missing keys."""
    mock_redis = MagicMock()
    mock_redis.type.return_value = b"none"

    backend = SyncRedisBackend(client=mock_redis)

    assert backend.get_metrics("user:1") == {}


def test_sync_redis_get_metrics_hash() -> None:
    """get_metrics parses hash state."""
    mock_redis = MagicMock()
    mock_redis.type.return_value = b"hash"
    mock_redis.hmget.return_value = [b"5.0", b"1700.0", b"2.0", b"1600.0"]

    backend = SyncRedisBackend(client=mock_redis)

    metrics = backend.get_metrics("user:1")

    assert metrics["storage_type"] == "hash"
    assert metrics["tokens"] == 5.0


def test_sync_redis_get_metrics_zset() -> None:
    """get_metrics parses zset state."""
    mock_redis = MagicMock()
    mock_redis.type.return_value = b"zset"
    mock_redis.zcard.return_value = 1
    mock_redis.zrange.return_value = [("member", 1700000000000.0)]

    backend = SyncRedisBackend(client=mock_redis)

    metrics = backend.get_metrics("user:1")

    assert metrics["storage_type"] == "zset"
    assert metrics["count"] == 1
    assert metrics["window_start"] == 1700000000.0


def test_sync_redis_get_metrics_other_type() -> None:
    """get_metrics returns storage type for unknown key types."""
    mock_redis = MagicMock()
    mock_redis.type.return_value = "stream"

    backend = SyncRedisBackend(client=mock_redis)

    metrics = backend.get_metrics("user:1")

    assert metrics["storage_type"] == "stream"


@pytest.mark.parametrize(
    ("method", "exception_source"),
    [
        ("type", "type"),
        ("hmget", "hash"),
        ("zcard", "zset"),
        ("zrange", "zset_range"),
    ],
)
def test_sync_redis_get_metrics_errors(method: str, exception_source: str) -> None:
    """get_metrics translates Redis errors for each branch."""
    mock_redis = MagicMock()
    if exception_source == "type":
        mock_redis.type.side_effect = RedisError("boom")
    elif exception_source == "hash":
        mock_redis.type.return_value = b"hash"
        mock_redis.hmget.side_effect = RedisError("boom")
    elif exception_source == "zset":
        mock_redis.type.return_value = b"zset"
        mock_redis.zcard.side_effect = RedisError("boom")
    else:
        mock_redis.type.return_value = b"zset"
        mock_redis.zcard.return_value = 1
        mock_redis.zrange.side_effect = RedisError("boom")

    backend = SyncRedisBackend(client=mock_redis)

    with pytest.raises(RateLimitBackendUnavailableError):
        backend.get_metrics("user:1")


def test_sync_redis_prefix_and_close() -> None:
    """Prefixing applies to keys and close() delegates to client."""
    mock_redis = MagicMock()
    mock_redis.evalsha.return_value = [1, 1, 0, 1700000000, 1]

    backend = SyncRedisBackend(client=mock_redis, key_prefix="rl:")
    backend._script_shas = {"token_bucket": "sha"}

    config = RateLimitConfig(
        algorithm="token_bucket",
        limit=1,
        period=1,
        burst_size=1,
    )

    backend.check_and_increment("user:1", config)
    backend.reset("user:1")
    backend.close()

    assert backend.key_prefix == "rl:"
    mock_redis.delete.assert_called_with("rl:user:1")
    mock_redis.close.assert_called_once()
