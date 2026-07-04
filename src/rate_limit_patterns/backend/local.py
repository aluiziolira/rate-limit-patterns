"""Local (in-memory) rate limit backend implementation."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import Any

from rate_limit_patterns.backend._local_shared import (
    LOCK_STRIPES,
    LocalStateCore,
    _LocalEntry,
)
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult

logger = logging.getLogger(__name__)


class LocalBackend:
    """In-memory rate limit backend using striped locks for concurrency."""

    def __init__(self) -> None:
        """Initialize the local backend."""
        self._locks = [asyncio.Lock() for _ in range(LOCK_STRIPES)]
        self._cleanup_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()
        self._cleanup_interval: float | None = None
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_event = asyncio.Event()
        self._running = False
        self._core = LocalStateCore()

    @property
    def _state(self) -> dict[str, _LocalEntry]:
        """Key→entry map (exposed for white-box tests)."""
        return self._core.state

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
        algorithm = self._core.algorithm_for(config)
        now_mono, now_wall = self._core.now(now)
        self._update_cleanup_interval(config.cleanup_interval)
        if config.cleanup_interval > 0:
            await self._start_cleanup_task()

        async with self._lock_for_key(key):
            allowed, metadata = self._core.apply(algorithm, key, config, now_mono)

        return self._core.build_result(config, allowed, metadata, now_mono, now_wall)

    def _lock_for_key(self, key: str) -> asyncio.Lock:
        return self._locks[hash(key) % len(self._locks)]

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
            for key in self._core.snapshot_keys():
                async with self._lock_for_key(key):
                    self._core.drop_if_expired(key, now_mono)

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
        async with self._lock_for_key(key):
            self._core.reset(key)

    async def get_metrics(self, key: str) -> dict[str, Any]:
        """Get metrics for a specific key.

        Args:
            key: Unique identifier to get metrics for.

        Returns:
            Dictionary containing metrics for the key.
        """
        now_mono, _ = self._core.now(None)
        async with self._lock_for_key(key):
            return self._core.metrics_snapshot(key, now_mono)
