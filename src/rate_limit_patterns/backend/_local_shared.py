"""Shared in-memory state core for the local rate limit backends.

``LocalStateCore`` owns the key→state map, algorithm dispatch, entry TTLs,
and monotonic/wall-clock conversion. It performs no synchronization: the
async ``LocalBackend`` and sync ``SyncLocalBackend`` wrap each call in their
own (asyncio or threading) striped locks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from rate_limit_patterns.algorithms.base import RateLimitAlgorithm
from rate_limit_patterns.algorithms.leaky_bucket import LeakyBucketAlgorithm
from rate_limit_patterns.algorithms.sliding_window import SlidingWindowAlgorithm
from rate_limit_patterns.algorithms.token_bucket import TokenBucketAlgorithm
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig, RateLimitResult

LOCK_STRIPES = 64


@dataclass(slots=True)
class _LocalEntry:
    state: dict[str, Any]
    expires_at: float


class LocalStateCore:
    """Unsynchronized state store and algorithm dispatch for local backends."""

    def __init__(self) -> None:
        self.state: dict[str, _LocalEntry] = {}
        self._algorithms: dict[AlgorithmType, RateLimitAlgorithm] = {
            "token_bucket": TokenBucketAlgorithm(),
            "sliding_window": SlidingWindowAlgorithm(),
            "leaky_bucket": LeakyBucketAlgorithm(),
        }
        self._time_offset = time.time() - time.monotonic()

    def algorithm_for(self, config: RateLimitConfig) -> RateLimitAlgorithm:
        """Resolve the algorithm for a config, raising ValueError if unknown."""
        algorithm = self._algorithms.get(config.algorithm)
        if algorithm is None:
            msg = (
                f"Unknown algorithm: {config.algorithm}. "
                f"Supported algorithms: {list(self._algorithms.keys())}"
            )
            raise ValueError(msg)
        return algorithm

    def now(self, now: float | None) -> tuple[float, float]:
        """Return (monotonic, wall) times, honoring an optional wall-clock override."""
        if now is None:
            now_mono = time.monotonic()
            now_wall = self._time_offset + now_mono
        else:
            now_wall = now
            now_mono = now - self._time_offset
        return now_mono, now_wall

    def apply(
        self,
        algorithm: RateLimitAlgorithm,
        key: str,
        config: RateLimitConfig,
        now_mono: float,
    ) -> tuple[bool, dict[str, Any]]:
        """Run one check-and-increment against the store.

        Callers must hold the lock guarding ``key``.
        """
        entry = self.state.get(key)
        if entry is None or entry.expires_at <= now_mono:
            state = algorithm.initial_state(config)
        else:
            state = entry.state

        allowed, new_state, metadata = algorithm.compute(state, config, now_mono)
        expires_at = now_mono + self._ttl_for(config)
        self.state[key] = _LocalEntry(state=new_state, expires_at=expires_at)
        return allowed, metadata

    def build_result(
        self,
        config: RateLimitConfig,
        allowed: bool,
        metadata: dict[str, Any],
        now_mono: float,
        now_wall: float,
    ) -> RateLimitResult:
        """Convert algorithm metadata into a RateLimitResult with wall-clock reset."""
        return RateLimitResult(
            allowed=allowed,
            remaining=metadata["remaining"],
            limit=config.limit,
            retry_after=metadata.get("retry_after"),
            reset_at=self._to_wall_time(metadata.get("reset_at"), now_mono, now_wall),
            request_count=metadata.get("request_count", 0),
        )

    def reset(self, key: str) -> None:
        """Drop the state for a key. Callers must hold the key's lock."""
        self.state.pop(key, None)

    def metrics_snapshot(self, key: str, now_mono: float) -> dict[str, Any]:
        """Return a shallow copy of a key's live state, evicting it if expired.

        Callers must hold the key's lock.
        """
        entry = self.state.get(key)
        if entry is None or entry.expires_at <= now_mono:
            self.state.pop(key, None)
            return {}
        return dict(entry.state)

    def snapshot_keys(self) -> list[str]:
        """Snapshot of currently stored keys (for cleanup sweeps)."""
        return list(self.state.keys())

    def drop_if_expired(self, key: str, now_mono: float) -> None:
        """Evict a key if its entry has expired. Callers must hold the key's lock."""
        entry = self.state.get(key)
        if entry is not None and entry.expires_at <= now_mono:
            self.state.pop(key, None)

    @staticmethod
    def _ttl_for(config: RateLimitConfig) -> float:
        if config.algorithm == "sliding_window":
            ttl = float(config.period)
        else:
            capacity = config.burst_size if config.burst_size is not None else config.limit
            rate = config.tokens_per_second
            ttl = capacity / rate if rate > 0 else 1.0
        return max(1.0, ttl)

    @staticmethod
    def _to_wall_time(reset_at: float | None, now_mono: float, now_wall: float) -> float | None:
        if reset_at is None:
            return None
        return now_wall + (reset_at - now_mono)
