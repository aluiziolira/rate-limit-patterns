# Rate Limit Patterns

> **Production-grade rate limiting primitives that treat distributed atomicity and concurrency correctness as first-class concerns.**

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)
![Type Checked](https://img.shields.io/badge/type--checked-mypy-blue)
![Redis](https://img.shields.io/badge/redis-5.0+-red.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)

![Live benchmark run: in-process latency, Redis Lua latency, and shared-quota correctness](docs/assets/benchmark-proof.gif)

*Demo recording via [VHS](https://github.com/charmbracelet/vhs) ([`demo/benchmark-proof.tape`](demo/benchmark-proof.tape)). Treat on-screen numbers as historical for that recording only — regenerate with `make demo-gif`, and use the reproducible commands below for current measurements.*

This library provides token bucket, leaky bucket, and sliding window log algorithms with an in-process backend and a Redis Lua-backed atomic path for shared quotas.

### Core Strategies
*   **Token Bucket**: Burst-friendly average rate enforcement with `O(1)` state (ideal for public APIs).
*   **Leaky Bucket**: Traffic shaping that smooths bursty inputs into a steady drain rate (ideal for protecting background workers).
*   **Sliding Window Log**: Exact rolling-window enforcement with `O(N)` state (ideal for strict security audits).

---

## Benchmarks

Hardcoded throughput/latency tables are intentionally omitted here. Absolute numbers vary by host, Python build, and Redis placement; commit JSON under `benchmarks/results/` is gitignored.

**Reproducible command (local latency):**

```bash
make benchmark-latency
```

That writes a timestamped `benchmarks/results/latency_*.json` artifact and prints a formatted summary. The formatter reports per-algorithm speed, stability, consistency, and throughput classifications, plus p50, p95, and p99 latency by concurrency level. Actual measurements depend on the host; no throughput figures are asserted here.

Redis-backed scenarios (requires Redis):

```bash
make benchmark-redis-docker
```

The shared-quota / multi-instance scenario exercises **two Redis clients in one process** against a shared key. It validates Lua atomicity under concurrent callers; it does **not** measure cross-host distributed behavior.

See [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) for methodology and additional targets (`make benchmark`, `make benchmark-memory`, `make benchmark-fairness`).

---

## Problem Statement

Most home-grown rate limiters fail in two critical ways:
1.  **Race Conditions**: Naive "Read-Check-Write" patterns allow parallel requests to slip through before the counter updates.
2.  **Clock Drift**: relying on server-local time without synchronization leads to inconsistent windows across a fleet.

This project solves these specific gaps by implementing **atomic-by-design** algorithms where every decision is the result of a single, indivisible Lua script execution on the storage backend.

---

## Technical Decisions

### 1. Atomicity is Non-Negotiable
Distributed systems cannot rely on application-level locks for rate limiting without destroying throughput. Instead of a "check then increment" flow (which is vulnerable to race conditions), this library pushes the logic to the data. By using Redis Lua scripts (`EVALSHA`), we ensure that the calculation of "allowed vs. denied" and the "state update" happen in a single frozen moment of time. This guarantees that even if 500 requests hit 10 containers simultaneously, the global limit is respected exactly.

### 2. Stateless Core, Swappable Backends
The algorithmic logic is decoupled from storage. Each algorithm implements a pure function protocol: `(state, config, time) -> (new_state, decision)`.
*   **Why?** This allows us to run the *exact same* logic in memory (for unit tests or single-process apps) as we do in Redis (translated to Lua).
*   **Trade-off**: While this requires maintaining dual implementations (Python + Lua), it ensures that our local simulations (`make benchmark-local`) are mathematically equivalent to production behavior, enabling high-confidence offline testing.

### 3. Explicit Memory vs. Precision Trade-offs
We expose the cost of precision. The **Sliding Window Log** offers "audit-grade" accuracy (remembering the exact timestamp of every request) but at `O(N)` memory cost. For high-throughput endpoints (e.g., 10k RPS), storing 10k timestamps is wasteful. In those cases, we explicitly recommend **Token Bucket** or **Leaky Bucket**, which maintain `O(1)` state (just two numbers: `tokens` and `last_updated`), sacrificing microscopic window precision for massive scalability.

---

## Getting Started

### Installation

```bash
pip install rate-limit-patterns
```

### Usage (Redis Backend)

```python
import asyncio
from rate_limit_patterns import RateLimitConfig, RateLimiter, RedisBackend

# 1. Configure the strategy
config = RateLimitConfig(algorithm="token_bucket", limit=100, period=60)

# 2. Initialize the distributed backend
backend = RedisBackend(url="redis://localhost:6379/0")
limiter = RateLimiter(backend=backend, config=config)

async def main():
    await backend.initialize()
    # 3. Check limit (Atomic operation)
    result = await limiter.check("user:123")

    if result.allowed:
        print(f"Allowed! Remaining: {result.remaining}")
    else:
        print(f"Blocked! Retry in: {result.retry_after}s")

    await backend.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## Documentation

*   [**API Reference**](docs/API.md)
*   [**Algorithm Deep Dive**](docs/ALGORITHMS.md)
*   [**Production Recipes**](docs/PRODUCTION_RECIPES.md)

## Remaining Limits

Engineering trade-offs that remain intentional:

*   **Local state is per backend instance** — `LocalBackend` / `SyncLocalBackend` instances do not share quotas, including instances in the same process.
*   **Script atomicity is per decision** — each `EVALSHA` is atomic; there is no multi-key saga across independent rate-limit keys.
*   **Out of scope** — automatic failover, reconstructing lost Redis state, resolving ambiguous responses after a timeout, and Redis Cluster operation beyond hash-tag key placement for sliding window.
