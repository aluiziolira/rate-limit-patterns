# High-Performance Rate Limiting: Benchmark & Architecture Report

> **Metric Snapshot (Observed 2026-01-22)**:
> Local p50 ≈ 2.7–3.3µs and p99 ≈ 9.3–11.4µs @ 5,000 concurrency ·
> Memory @ 100K keys ≈ 37–44MB ·
> Redis p50 ≈ 10–13ms and p99 ≈ 20–22ms @ 250 concurrency ·
> Multi-instance accuracy: 100% (within tolerance)

## 1. Executive Summary

This report summarizes the observed performance and reliability characteristics of the `rate-limit-patterns` library based on the most recent benchmark execution.

**Run Metadata (Most Recent)**
* **Timestamp (UTC)**: 2026-01-22T00:24:32Z to 2026-01-22T00:24:48Z
* **Platform**: Linux (WSL2 kernel shown in benchmark metadata)
* **Python**: 3.12.1
* **Redis Image**: `redis:7-alpine` (via `docker-compose.yml`)

**Key Engineering Wins**
* **Zero-cost abstractions**: Protocol-based interfaces + `mypy --strict` allow a clean, typed surface without runtime inheritance overhead in the hot path.
* **Atomic consistency**: Redis-backed rate limiting uses Lua-scripted atomic updates to avoid check-then-act races.
* **Predictable cost model**: Token Bucket and Leaky Bucket are `O(1)` state; Sliding Window Log is `O(N)` by design for audit-grade precision.

---

## 2. Architectural Strategy & Design Decisions

### Algorithm Selection: The Trade-off Landscape

| Algorithm | Design Goal | Complexity | Ideal Use Case |
|-----------|-------------|------------|----------------|
| **Token Bucket** | **Throughput & burst tolerance** | **O(1)** | Default for public APIs; allows controlled bursts while enforcing long-term average. |
| **Leaky Bucket** | **Traffic shaping** | **O(1)** | Smooths bursty inbound traffic to protect downstream systems. |
| **Sliding Window Log** | **Absolute accuracy** | **O(N)** | Hard limits for security/billing where overages are unacceptable. |

### Optimization Highlights

* **Typed boundary, lean core**: The hot path operates on simple dict state and primitives while preserving a strict, composable API surface.
* **State locality**: Local backend uses in-process state with monotonic time to avoid clock regressions.
* **Network efficiency (Redis)**: Lua scripts are cached/executed server-side to keep operations atomic and reduce round-trips.

---

## 3. Performance Analysis

Benchmarks are `asyncio`-driven to simulate high concurrency. Latency values below are per `check_and_increment` call.

### 3.1 Local Latency (In-Process)

Observed at **5,000 concurrency** (`benchmarks/results/latency_20260122T002432Z.json`):

| Algorithm | p50 | p99 | Aggregate Throughput* |
|-----------|-----|-----|------------------------|
| Token Bucket | 3.29µs | 9.25µs | 229,540 rps |
| Sliding Window Log | 2.73µs | 10.60µs | 263,820 rps |
| Leaky Bucket | 3.22µs | 11.42µs | 197,861 rps |

\*Aggregate throughput is computed over the suite’s concurrency levels (100, 500, 1,000, 5,000).

### 3.2 Redis Latency (Network + Atomic Lua)

Observed at **250 concurrency** (`benchmarks/results/redis_latency_20260122T002447Z.json`):

| Algorithm | p50 | p99 | Aggregate Throughput* |
|-----------|-----|-----|------------------------|
| Token Bucket | 13.10ms | 21.12ms | 7,451 rps |
| Sliding Window Log | 13.22ms | 22.07ms | 7,944 rps |
| Leaky Bucket | 10.28ms | 20.45ms | 7,986 rps |

\*Aggregate throughput is computed over the suite’s concurrency levels (10, 50, 100, 250).

### 3.3 Memory Efficiency (Local State)

Observed peak allocations via `tracemalloc` (`benchmarks/results/memory_20260122T002439Z.json`):

| Key Count | Token Bucket | Sliding Window Log | Leaky Bucket |
|----------:|-------------:|---------------:|------------:|
| 1,000 | 0.37MB | 0.43MB | 0.37MB |
| 10,000 | 3.57MB | 4.18MB | 3.57MB |
| 100,000 | 37.42MB | 43.52MB | 37.42MB |

---

## 4. Distributed Consistency & Fairness

### 4.1 Multi-Instance Consistency (Redis)

`benchmarks/results/multi_instance_20260122T002448Z.json` simulates **2 instances** with a **global limit=100/60s** and tolerance **±2**.

* **Result**: All algorithms accepted **100/100** (within tolerance) in the tested scenario.

### 4.2 Fairness (Shared-Key Contention)

`benchmarks/results/fairness_20260122T002439Z.json` measures how evenly capacity is distributed when **multiple users contend for a single shared key**.

* **Result (Observed)**: CV=3.00 (Unfair), total accepted **100/5,000 (2.0%)**. Distribution is driven primarily by scheduling and queue order, not by algorithm guarantees.

---

## Appendix: Reproduction & Methodology

**Environment**: `Python 3.12+`, `Redis 7.x` (Docker image used for local runs: `redis:7-alpine`).
**Tools**: `time.perf_counter_ns`, `tracemalloc`.

To run benchmarks:

```bash
# Local-only suite (no Redis required)
make benchmark

# Individual scenarios
make benchmark-latency
make benchmark-memory
make benchmark-fairness

# Redis-backed scenarios (requires REDIS_URL, defaults to redis://localhost:6379/15)
make benchmark-redis

# Bring up Redis via docker-compose and run Redis benchmarks
make benchmark-redis-docker
```

All result artifacts are written to `benchmarks/results/`.
