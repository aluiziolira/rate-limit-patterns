"""Local (in-memory) rate limit backend implementation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Any

from rate_limit_patterns.algorithms.base import RateLimitAlgorithm
from rate_limit_patterns.algorithms.leaky_bucket import LeakyBucketAlgorithm
from rate_limit_patterns.algorithms.sliding_window import SlidingWindowAlgorithm
from rate_limit_patterns.algorithms.token_bucket import TokenBucketAlgorithm
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig, RateLimitResult

_LOCK_STRIPES = 64
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _LocalEntry:
    state: dict[str, Any]
    expires_at: float


class LocalBackend:
    """In-memory rate limit backend using striped locks for concurrency."""

    def __init__(self) -> None:
        """Initialize the local backend."""
        self._locks = [asyncio.Lock() for _ in range(_LOCK_STRIPES)]
        self._cleanup_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._cleanup_interval: float | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_event = asyncio.Event()
        self._running = False
        self._state: dict[str, _LocalEntry] = {}
        self._algorithms: dict[AlgorithmType, RateLimitAlgorithm] = {
            "token_bucket": TokenBucketAlgorithm(),
            "sliding_window": SlidingWindowAlgorithm(),
            "leaky_bucket": LeakyBucketAlgorithm(),
        }
        self._time_offset = time.time() - time.monotonic()

    async def check_and_increment(
        self,
        key: str,
        config: RateLimitConfig,
        *,
        now: float | None = None,
    ) -> RateLimitResult:
        """Check and increment the rate limit counter for a key.

        Args:
            key: Unique identifier for the rate limit (e.g., user ID, IP).
            config: Rate limit configuration to apply.
            now: Optional Unix timestamp override for deterministic tests.

        Returns:
            RateLimitResult indicating if the request is allowed and state.
        """
        algorithm = self._algorithms.get(config.algorithm)
        if algorithm is None:
            msg = (
                f"Unknown algorithm: {config.algorithm}. "
                f"Supported algorithms: {list(self._algorithms.keys())}"
            )
            raise ValueError(msg)

        now_mono, now_wall = self._now(now)
        self._update_cleanup_interval(config.cleanup_interval)
        if config.cleanup_interval > 0:
            await self._start_cleanup_task()

        lock = self._lock_for_key(key)
        async with lock:
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

    def _lock_for_key(self, key: str) -> asyncio.Lock:
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
            self._cleanup_event.set()

    async def initialize(self) -> None:
        """Start background cleanup task."""
        await self._start_cleanup_task()

    async def _start_cleanup_task(self) -> None:
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        async with self._init_lock:
            if self._cleanup_task is not None and not self._cleanup_task.done():
                return
            self._running = True
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        while self._running:
            interval = self._cleanup_interval
            if interval is None or interval <= 0:
                try:
                    await self._cleanup_event.wait()
                except asyncio.CancelledError:
                    return
                self._cleanup_event.clear()
                continue
            try:
                await asyncio.wait_for(self._cleanup_event.wait(), timeout=interval)
                self._cleanup_event.clear()
                continue
            except TimeoutError:
                self._cleanup_event.clear()
            except asyncio.CancelledError:
                return
            now_mono = time.monotonic()
            try:
                await self._cleanup_expired(now_mono)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.debug("Cleanup iteration failed", exc_info=True)
                continue

    async def _cleanup_expired(self, now_mono: float) -> None:
        async with self._cleanup_lock:
            for key in list(self._state.keys()):
                lock = self._lock_for_key(key)
                async with lock:
                    entry = self._state.get(key)
                    if entry is not None and entry.expires_at <= now_mono:
                        self._state.pop(key, None)

    async def close(self) -> None:
        """Stop background cleanup task."""
        self._running = False
        if self._cleanup_task is None:
            return
        self._cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._cleanup_task
        self._cleanup_task = None

    async def reset(self, key: str) -> None:
        """Reset the rate limit state for a key.

        Args:
            key: Unique identifier for the rate limit to reset.
        """
        lock = self._lock_for_key(key)
        async with lock:
            self._state.pop(key, None)

    async def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key.

        Args:
            key: Unique identifier to get metrics for.

        Returns:
            Dictionary containing metrics for the key.
        """
        now_mono, _ = self._now(None)
        lock = self._lock_for_key(key)
        async with lock:
            entry = self._state.get(key)
            if entry is None or entry.expires_at <= now_mono:
                self._state.pop(key, None)
                return {}
            # Return shallow copy to prevent external mutation
            return dict(entry.state)
