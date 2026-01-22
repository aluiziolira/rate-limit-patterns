"""Benchmark runner utilities for rate limit patterns."""

from __future__ import annotations

import asyncio
import json
import platform
import statistics
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

import psutil

LatencyCallable = Callable[[], Awaitable[None]]
MemoryCallable = Callable[[int], Awaitable[None]]
MemorySetup = Callable[[int], None]


@dataclass(frozen=True, slots=True)
class LatencyResult:
    """Latency benchmark results for a single algorithm and concurrency level."""

    algorithm: str
    concurrency: int
    iterations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    total_seconds: float


@dataclass(frozen=True, slots=True)
class MemoryResult:
    """Memory benchmark results for a single algorithm and key count."""

    algorithm: str
    key_count: int
    peak_bytes: int
    current_bytes: int
    rss_bytes: int


class BenchmarkRunner:
    """Reusable benchmark harness with stats and JSON output."""

    def __init__(
        self,
        *,
        warmup_iterations: int = 10,
        results_dir: str | Path = "benchmarks/results",
    ) -> None:
        """Initialize the benchmark runner."""
        if warmup_iterations < 0:
            raise ValueError("warmup_iterations must be non-negative")
        self.warmup_iterations = warmup_iterations
        self._results_dir = Path(results_dir)

    def write_json(self, scenario: str, payload: dict[str, Any]) -> Path:
        """Write benchmark results to a JSON file."""
        if not scenario:
            raise ValueError("scenario must be provided")

        self._results_dir.mkdir(parents=True, exist_ok=True)

        output: dict[str, Any] = {
            "metadata": self._metadata(),
            **payload,
        }
        path = self._results_dir / f"{scenario}_{self._timestamp()}.json"
        path.write_text(json.dumps(output, indent=2, sort_keys=True), encoding="utf-8")
        return path

    async def run_latency_benchmark(
        self,
        func: LatencyCallable,
        iterations: int,
        concurrency: int,
        *,
        algorithm: str | None = None,
    ) -> LatencyResult:
        """Run a latency benchmark for an async callable."""
        self._validate_positive("iterations", iterations)
        self._validate_positive("concurrency", concurrency)

        for _ in range(self.warmup_iterations):
            await func()

        durations_ns: list[int] = []
        queue: asyncio.Queue[None] = asyncio.Queue()
        for _ in range(iterations):
            queue.put_nowait(None)

        async def worker() -> None:
            while True:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                start_ns = time.perf_counter_ns()
                try:
                    await func()
                finally:
                    end_ns = time.perf_counter_ns()
                    durations_ns.append(end_ns - start_ns)
                    queue.task_done()

        worker_count = min(concurrency, iterations)
        workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
        start_total = time.perf_counter()
        await queue.join()
        total_seconds = time.perf_counter() - start_total
        for worker_task in workers:
            worker_task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)

        durations_ms = [duration / 1_000_000 for duration in durations_ns]
        p50_ms, p95_ms, p99_ms = _percentiles(durations_ms)

        return LatencyResult(
            algorithm=_resolve_algorithm(func, algorithm),
            concurrency=concurrency,
            iterations=iterations,
            p50_ms=p50_ms,
            p95_ms=p95_ms,
            p99_ms=p99_ms,
            min_ms=min(durations_ms),
            max_ms=max(durations_ms),
            total_seconds=total_seconds,
        )

    async def run_memory_benchmark(
        self,
        func: MemoryCallable,
        key_counts: Sequence[int],
        *,
        algorithm: str | None = None,
        setup: MemorySetup | None = None,
    ) -> list[MemoryResult]:
        """Run a memory benchmark for the provided key counts."""
        if not key_counts:
            raise ValueError("key_counts must not be empty")

        process = psutil.Process()
        results: list[MemoryResult] = []

        for key_count in key_counts:
            self._validate_positive("key_count", key_count)

            if setup is not None:
                setup(key_count)

            tracemalloc.start()
            try:
                await func(key_count)
                current_bytes, peak_bytes = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()

            rss_bytes = process.memory_info().rss
            results.append(
                MemoryResult(
                    algorithm=_resolve_algorithm(func, algorithm),
                    key_count=key_count,
                    peak_bytes=peak_bytes,
                    current_bytes=current_bytes,
                    rss_bytes=rss_bytes,
                )
            )

        return results

    def _metadata(self) -> dict[str, str]:
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "python_version": platform.python_version(),
            "platform": platform.platform(),
        }

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    @staticmethod
    def _validate_positive(name: str, value: int) -> None:
        if value <= 0:
            raise ValueError(f"{name} must be positive")


def _resolve_algorithm(func: Callable[..., Any], algorithm: str | None) -> str:
    if algorithm is not None:
        return algorithm
    return getattr(func, "__name__", "unknown")


def _percentiles(values: Sequence[float]) -> tuple[float, float, float]:
    if not values:
        raise ValueError("No latency samples collected")

    p50_ms = statistics.median(values)
    if len(values) < 2:
        return p50_ms, p50_ms, p50_ms

    quantiles = statistics.quantiles(values, n=100, method="inclusive")
    p95_ms = quantiles[94]
    p99_ms = quantiles[98]
    return p50_ms, p95_ms, p99_ms
