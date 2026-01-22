"""Multi-instance consistency benchmark scenario."""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import asdict, dataclass

from benchmarks.formatter import BenchmarkFormatter
from benchmarks.runner import BenchmarkRunner
from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig

ALGORITHMS: tuple[AlgorithmType, ...] = (
    "token_bucket",
    "sliding_window",
    "leaky_bucket",
)
INSTANCE_COUNT = 2
REQUESTS_PER_INSTANCE = 100
LIMIT = 100
PERIOD = 60
TOLERANCE = 2


@dataclass(frozen=True, slots=True)
class MultiInstanceResult:
    """Multi-instance benchmark results for a single algorithm."""

    algorithm: str
    instance_count: int
    requests_per_instance: int
    total_accepted: int
    limit: int
    within_tolerance: bool


async def _run_instance(
    backend: RedisBackend,
    key: str,
    config: RateLimitConfig,
    requests: int,
) -> int:
    queue: asyncio.Queue[None] = asyncio.Queue()
    for _ in range(requests):
        queue.put_nowait(None)
    allowed = 0
    counter_lock = asyncio.Lock()

    async def worker() -> None:
        nonlocal allowed
        while True:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            result = await backend.check_and_increment(key, config)
            if result.allowed:
                async with counter_lock:
                    allowed += 1
            queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(min(requests, 50))]
    await queue.join()
    for worker_task in workers:
        worker_task.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    return allowed


async def _benchmark_algorithm(
    algorithm: AlgorithmType, redis_url: str
) -> MultiInstanceResult:
    backend1 = RedisBackend(url=redis_url, key_prefix="bench:")
    backend2 = RedisBackend(url=redis_url, key_prefix="bench:")

    await backend1.initialize()
    await backend2.initialize()

    key = f"multi:{algorithm}"
    config = RateLimitConfig(
        algorithm=algorithm,
        limit=LIMIT,
        period=PERIOD,
        burst_size=LIMIT,
    )

    try:
        accepted1, accepted2 = await asyncio.gather(
            _run_instance(backend1, key, config, REQUESTS_PER_INSTANCE),
            _run_instance(backend2, key, config, REQUESTS_PER_INSTANCE),
        )
        total_accepted = accepted1 + accepted2
    finally:
        await backend1.reset(key)
        await backend1.close()
        await backend2.close()

    within_tolerance = total_accepted <= LIMIT + TOLERANCE
    return MultiInstanceResult(
        algorithm=algorithm,
        instance_count=INSTANCE_COUNT,
        requests_per_instance=REQUESTS_PER_INSTANCE,
        total_accepted=total_accepted,
        limit=LIMIT,
        within_tolerance=within_tolerance,
    )


async def main() -> None:
    """Run multi-instance benchmarks for all algorithms."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("REDIS_URL not set; skipping multi-instance benchmark.")
        return

    runner = BenchmarkRunner(warmup_iterations=0)
    results = [
        await _benchmark_algorithm(algorithm, redis_url) for algorithm in ALGORITHMS
    ]

    payload = {
        "scenario": "multi_instance",
        "config": {"limit": LIMIT, "period": PERIOD},
        "instance_count": INSTANCE_COUNT,
        "requests_per_instance": REQUESTS_PER_INSTANCE,
        "tolerance": TOLERANCE,
        "results": [asdict(result) for result in results],
    }
    output_path = runner.write_json("multi_instance", payload)
    print(f"Wrote multi-instance results to {output_path}")

    # Format and print human-readable output
    if "--no-format" not in sys.argv:
        formatter = BenchmarkFormatter(use_colors=True)
        formatted_output = formatter.format(output_path)
        if formatted_output:
            print("\n" + formatted_output)


if __name__ == "__main__":
    asyncio.run(main())
