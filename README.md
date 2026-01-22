# Rate Limit Patterns

**Production-grade rate limiting primitives that treat distributed atomicity and concurrency correctness as first-class concerns.**

This library provides a suite of algorithms to enforce quotas with **microsecond-scale in-process overhead** and a **Redis Lua-backed atomic path** for robust multi-instance deployments.

### Core Strategies
*   **Token Bucket**: Burst-friendly average rate enforcement with `O(1)` state (ideal for public APIs).
*   **Leaky Bucket**: Traffic shaping that smooths bursty inputs into a steady drain rate (ideal for protecting background workers).
*   **Sliding Window Log**: Exact rolling-window enforcement with `O(N)` state (ideal for strict security audits).

---

## Benchmark Proof

**Status**: Verified on `Linux/WSL2` (Python 3.12) | **Date**: 2026-01-22

### 1. In-Process Performance (Local Memory)
At **5,000 concurrent requests**, the stateless core operates with negligible overhead (~3µs).

```text
Algorithm        p50       p99       Throughput      Memory (100k keys)
Token Bucket     3.3 µs    12 µs     215,962 rps     37.4 MB
Sliding Window   2.8 µs    13 µs     244,598 rps     43.5 MB
Leaky Bucket     3.3 µs    11 µs     193,962 rps     37.4 MB
```

### 2. Distributed Performance (Redis Lua)
At **250 concurrent requests**, the Redis backend maintains strict consistency with predictable network/execution latency.

```text
Algorithm        p50       p99       Throughput      Consistency
Sliding Window   13.75 ms  23.24 ms  7,495 rps       100% (No race conditions)
Leaky Bucket     12.17 ms  21.65 ms  7,544 rps       100% (No race conditions)
```

### 3. Distributed Correctness Verification
Multi-instance simulations (2 independent processes, global limit 100/60s) confirm **zero over-limit leakages** despite network latency and concurrency.

```text
Target: 100 accepted requests
Result: 100 accepted requests (0.0% error rate)
Status: PASSED
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