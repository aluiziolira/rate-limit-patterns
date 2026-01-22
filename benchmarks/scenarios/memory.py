"""Memory benchmark scenario."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import asdict

from benchmarks.formatter import BenchmarkFormatter
from benchmarks.runner import BenchmarkRunner, MemoryResult
from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig

ALGORITHMS: tuple[AlgorithmType, ...] = (
    "token_bucket",
    "sliding_window",
    "leaky_bucket",
)
KEY_COUNTS: tuple[int, ...] = (1_000, 10_000, 100_000)


async def _benchmark_algorithm(
    algorithm: AlgorithmType, runner: BenchmarkRunner
) -> list[MemoryResult]:
    backend: LocalBackend | None = None
    config: RateLimitConfig | None = None

    def setup(_: int) -> None:
        nonlocal backend, config
        backend = LocalBackend()
        config = RateLimitConfig(
            algorithm=algorithm,
            limit=1000,
            period=60,
            burst_size=2000,
        )

    async def populate(key_count: int) -> None:
        assert backend is not None
        assert config is not None
        for i in range(key_count):
            await backend.check_and_increment(f"key:{i}", config)

    return await runner.run_memory_benchmark(
        populate,
        KEY_COUNTS,
        algorithm=algorithm,
        setup=setup,
    )


def _validate_token_bucket(results: list[MemoryResult]) -> None:
    for result in results:
        if result.algorithm == "token_bucket" and result.key_count == 10_000:
            if result.peak_bytes > 100 * 1024:
                print(
                    "Warning: token bucket peak bytes exceeded 100KB at 10K keys "
                    f"({result.peak_bytes} bytes)"
                )


async def main() -> None:
    """Run memory benchmarks for all algorithms."""
    runner = BenchmarkRunner(warmup_iterations=0)
    results: list[MemoryResult] = []

    for algorithm in ALGORITHMS:
        results.extend(await _benchmark_algorithm(algorithm, runner))

    _validate_token_bucket(results)

    payload = {
        "scenario": "memory",
        "key_counts": list(KEY_COUNTS),
        "config": {"limit": 1000, "period": 60, "burst_size": 2000},
        "results": [asdict(result) for result in results],
    }
    output_path = runner.write_json("memory", payload)
    print(f"Wrote memory results to {output_path}")

    # Format and print human-readable output
    if "--no-format" not in sys.argv:
        formatter = BenchmarkFormatter(use_colors=True)
        formatted_output = formatter.format(output_path)
        if formatted_output:
            print("\n" + formatted_output)


if __name__ == "__main__":
    asyncio.run(main())
