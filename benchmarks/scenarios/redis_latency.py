"""Redis latency benchmark scenario."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import asdict

from benchmarks.formatter import BenchmarkFormatter
from benchmarks.runner import BenchmarkRunner, LatencyResult
from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig

ALGORITHMS: tuple[AlgorithmType, ...] = (
    "token_bucket",
    "sliding_window",
    "leaky_bucket",
)
CONCURRENCY_LEVELS: tuple[int, ...] = (10, 50, 100, 250)
WARMUP_CALLS = 20
LIMIT = 50000
PERIOD = 60
BURST_SIZE = 50000


async def _benchmark_algorithm(
    algorithm: AlgorithmType, runner: BenchmarkRunner, redis_url: str
) -> list[LatencyResult]:
    results: list[LatencyResult] = []
    backend = RedisBackend(url=redis_url, key_prefix="bench:")
    await backend.initialize()

    config = RateLimitConfig(
        algorithm=algorithm,
        limit=LIMIT,
        period=PERIOD,
        burst_size=BURST_SIZE,
    )
    key = f"redis-latency:{algorithm}"

    async def call() -> None:
        await backend.check_and_increment(key, config)

    try:
        for concurrency in CONCURRENCY_LEVELS:
            for _ in range(WARMUP_CALLS):
                await call()
            result = await runner.run_latency_benchmark(
                call,
                iterations=concurrency,
                concurrency=concurrency,
                algorithm=algorithm,
            )
            results.append(result)
    finally:
        await backend.reset(key)
        await backend.close()

    return results


async def main() -> None:
    """Run Redis latency benchmarks for all algorithms."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("REDIS_URL not set; skipping Redis latency benchmark.")
        return

    runner = BenchmarkRunner(warmup_iterations=0)
    results: list[LatencyResult] = []

    for algorithm in ALGORITHMS:
        results.extend(await _benchmark_algorithm(algorithm, runner, redis_url))

    payload = {
        "scenario": "redis_latency",
        "config": {"limit": LIMIT, "period": PERIOD, "burst_size": BURST_SIZE},
        "concurrency_levels": list(CONCURRENCY_LEVELS),
        "results": [asdict(result) for result in results],
    }
    output_path = runner.write_json("redis_latency", payload)
    print(f"Wrote Redis latency results to {output_path}")

    if "--no-format" not in sys.argv:
        formatter = BenchmarkFormatter(use_colors=True)
        formatted_output = formatter.format(output_path)
        if formatted_output:
            print("\n" + formatted_output)


if __name__ == "__main__":
    asyncio.run(main())
