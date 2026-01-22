"""Latency benchmark scenario."""

from __future__ import annotations

import asyncio
import itertools
import sys
from dataclasses import asdict

from benchmarks.formatter import BenchmarkFormatter
from benchmarks.runner import BenchmarkRunner, LatencyResult
from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig

ALGORITHMS: tuple[AlgorithmType, ...] = (
    "token_bucket",
    "sliding_window",
    "leaky_bucket",
)
CONCURRENCY_LEVELS: tuple[int, ...] = (100, 500, 1000, 5000)
WARMUP_CALLS = 100


async def _benchmark_algorithm(
    algorithm: AlgorithmType, runner: BenchmarkRunner
) -> list[LatencyResult]:
    results: list[LatencyResult] = []

    for concurrency in CONCURRENCY_LEVELS:
        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm=algorithm,
            limit=1000,
            period=60,
            burst_size=2000,
        )
        counter = itertools.count()

        async def call() -> None:
            key = f"bench:latency:{algorithm}:{next(counter)}"
            await backend.check_and_increment(key, config)

        for _ in range(WARMUP_CALLS):
            await call()

        result = await runner.run_latency_benchmark(
            call,
            iterations=concurrency,
            concurrency=concurrency,
            algorithm=algorithm,
        )
        results.append(result)

    return results


async def main() -> None:
    """Run latency benchmarks for all algorithms."""
    runner = BenchmarkRunner(warmup_iterations=0)
    results: list[LatencyResult] = []

    for algorithm in ALGORITHMS:
        results.extend(await _benchmark_algorithm(algorithm, runner))

    payload = {
        "scenario": "latency",
        "config": {"limit": 1000, "period": 60, "burst_size": 2000},
        "concurrency_levels": list(CONCURRENCY_LEVELS),
        "results": [asdict(result) for result in results],
    }
    output_path = runner.write_json("latency", payload)
    print(f"Wrote latency results to {output_path}")

    # Format and print human-readable output
    if "--no-format" not in sys.argv:
        formatter = BenchmarkFormatter(use_colors=True)
        formatted_output = formatter.format(output_path)
        if formatted_output:
            print("\n" + formatted_output)


if __name__ == "__main__":
    asyncio.run(main())
