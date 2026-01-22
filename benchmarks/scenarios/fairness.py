"""Fairness benchmark scenario (shared key contention)."""

from __future__ import annotations

import asyncio
import statistics
import sys
from dataclasses import asdict, dataclass

from benchmarks.formatter import BenchmarkFormatter
from benchmarks.runner import BenchmarkRunner
from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig

ALGORITHMS: tuple[AlgorithmType, ...] = (
    "token_bucket",
    "sliding_window",
    "leaky_bucket",
)
USER_COUNT = 10
REQUESTS_PER_USER = 500
CONCURRENCY = 100
SHARED_KEY = "fairness:shared"


@dataclass(frozen=True, slots=True)
class FairnessResult:
    """Fairness benchmark results for a single algorithm."""

    algorithm: str
    total_requests: int
    total_accepted: int
    per_user_accepted: list[int]
    std_deviation: float
    coefficient_of_variation: float


async def _benchmark_algorithm(algorithm: AlgorithmType) -> FairnessResult:
    backend = LocalBackend()
    config = RateLimitConfig(algorithm=algorithm, limit=100, period=60, burst_size=100)

    per_user_accepted = [0 for _ in range(USER_COUNT)]
    counter_lock = asyncio.Lock()
    queue: asyncio.Queue[int] = asyncio.Queue()
    for user_index in range(USER_COUNT):
        for _ in range(REQUESTS_PER_USER):
            queue.put_nowait(user_index)

    async def worker() -> None:
        while True:
            try:
                user_index = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            result = await backend.check_and_increment(SHARED_KEY, config)
            if result.allowed:
                async with counter_lock:
                    per_user_accepted[user_index] += 1
            queue.task_done()

    worker_count = min(CONCURRENCY, USER_COUNT * REQUESTS_PER_USER)
    workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
    await queue.join()
    for worker_task in workers:
        worker_task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)

    total_requests = USER_COUNT * REQUESTS_PER_USER
    total_accepted = sum(per_user_accepted)
    std_deviation = statistics.pstdev(per_user_accepted)
    mean_accepted = total_accepted / USER_COUNT
    coefficient_of_variation = (
        std_deviation / mean_accepted if mean_accepted > 0 else 0.0
    )

    return FairnessResult(
        algorithm=algorithm,
        total_requests=total_requests,
        total_accepted=total_accepted,
        per_user_accepted=per_user_accepted,
        std_deviation=std_deviation,
        coefficient_of_variation=coefficient_of_variation,
    )


async def main() -> None:
    """Run fairness benchmarks for all algorithms."""
    runner = BenchmarkRunner(warmup_iterations=0)
    results = [await _benchmark_algorithm(algorithm) for algorithm in ALGORITHMS]

    payload = {
        "scenario": "fairness",
        "config": {"limit": 100, "period": 60},
        "users": USER_COUNT,
        "requests_per_user": REQUESTS_PER_USER,
        "concurrency": CONCURRENCY,
        "shared_key": SHARED_KEY,
        "results": [asdict(result) for result in results],
    }
    output_path = runner.write_json("fairness", payload)
    print(f"Wrote fairness results to {output_path}")

    # Format and print human-readable output
    if "--no-format" not in sys.argv:
        formatter = BenchmarkFormatter(use_colors=True)
        formatted_output = formatter.format(output_path)
        if formatted_output:
            print("\n" + formatted_output)


if __name__ == "__main__":
    asyncio.run(main())
