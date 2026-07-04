# Rate Limit Patterns

> **Production-grade rate limiting primitives that treat distributed atomicity and concurrency correctness as first-class concerns.**

![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)
![Type Checked](https://img.shields.io/badge/type--checked-mypy-blue)
![Redis](https://img.shields.io/badge/redis-5.0+-red.svg)
![Performance](https://img.shields.io/badge/throughput-200K%2B%20RPS%20measured-green)
![License](https://img.shields.io/badge/license-MIT-green.svg)

![Live benchmark run: in-process latency, Redis Lua latency, and multi-instance correctness](docs/assets/benchmark-proof.gif)

*Live benchmark run recorded with [VHS](https://github.com/charmbracelet/vhs) ([`demo/benchmark-proof.tape`](demo/benchmark-proof.tape)) — nothing mocked: in-process latency, the atomic Redis Lua backend, and a 2-instance correctness check all run for real. Regenerate with `make demo-gif`.*

This library provides a suite of algorithms to enforce quotas with **microsecond-scale in-process overhead** and a **Redis Lua-backed atomic path** for robust multi-instance deployments.

### Core Strategies
*   **Token Bucket**: Burst-friendly average rate enforcement with `O(1)` state (ideal for public APIs).
*   **Leaky Bucket**: Traffic shaping that smooths bursty inputs into a steady drain rate (ideal for protecting background workers).
*   **Sliding Window Log**: Exact rolling-window enforcement with `O(N)` state (ideal for strict security audits).

---

## Benchmark Proof

The numbers below come from the live, unedited benchmark run shown in the recording at the top of this page.

**Environment**: Linux (Fedora, kernel 7.0) | Python 3.14 | Redis via Docker | **Date**: 2026-07-04

Reproduce it yourself: `make benchmark` (local) and `make benchmark-redis-docker` (distributed) — every run also writes raw JSON to `benchmarks/results/`.

### 1. In-Process Performance (Local Memory)
At **5,000 concurrent requests**, the stateless core decides in single-digit microseconds.

```text
Algorithm        p50       p99       Throughput
Token Bucket     2.8 µs    5.2 µs    244,081 rps
Sliding Window   2.4 µs    4.5 µs    289,675 rps
Leaky Bucket     2.6 µs    4.5 µs    269,123 rps
```

### 2. Distributed Performance (Redis Lua)
At **250 concurrent requests**, the Redis backend maintains strict atomicity with predictable network/execution latency.

```text
Algorithm        p50       p99        Throughput
Token Bucket     7.29 ms   11.37 ms   16,730 rps
Sliding Window   7.83 ms   10.75 ms   14,075 rps
Leaky Bucket     4.95 ms    8.39 ms   20,370 rps
```

### 3. Distributed Correctness Verification
Two independent processes sharing a global limit of 100/60s admit **exactly 100 requests** — zero over-limit leakage, no coordination beyond the atomic Lua scripts.

```text
Algorithm        Accepted / Expected   Status
Token Bucket     100 / 100             Distributed-Safe ✓
Sliding Window   100 / 100             Distributed-Safe ✓
Leaky Bucket     100 / 100             Distributed-Safe ✓
```

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
