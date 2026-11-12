# Benchmark Methodology

Reproduce measurements with the make targets below. Absolute latency and throughput depend on the host, Python build, and Redis placement. JSON outputs land in `benchmarks/results/` (gitignored); consult the artifact written by each target for actual numbers.

**Environment**: `Python 3.12+`, `Redis 7.x` (Docker image used for local runs: `redis:7-alpine`).
**Tools**: `time.perf_counter_ns`, `tracemalloc`.

## Design notes

* **Typed boundary, lean core**: Protocol-based interfaces + `mypy --strict` keep a typed surface while the hot path operates on simple dict state and primitives.
* **Atomic updates (Redis)**: Redis-backed checks use Lua scripts so allow/deny and state mutation happen in one server-side operation, avoiding check-then-act races for a single key.
* **Cost model**: Token Bucket and Leaky Bucket keep `O(1)` state; Sliding Window Log keeps an exact rolling-window quota at `O(N)` storage.

### Algorithm selection

| Algorithm | Design Goal | Complexity | Ideal Use Case |
|-----------|-------------|------------|----------------|
| **Token Bucket** | Throughput & burst tolerance | `O(1)` | Default for public APIs; controlled bursts with a long-term average. |
| **Leaky Bucket** | Traffic shaping | `O(1)` | Smooth bursty inbound traffic to protect downstream systems. |
| **Sliding Window Log** | Exact rolling-window quota | `O(N)` | Hard limits for security/billing where overages are unacceptable. |

### Optimization highlights

* **State locality**: Local backend uses in-process state with monotonic time to avoid clock regressions.
* **Network efficiency (Redis)**: Lua scripts are cached via `EVALSHA` to keep operations atomic and reduce round-trips.

---

## Scenarios

Benchmarks are `asyncio`-driven. Latency is measured per `check_and_increment` call.

### Local latency (in-process)

```bash
make benchmark-latency
```

Runs `python -m benchmarks.scenarios.latency` across concurrency levels (100, 500, 1,000, 5,000). Writes `benchmarks/results/latency_*.json` and prints speed/stability/consistency/throughput classifications plus p50/p95/p99 by concurrency. Actual values come from that JSON artifact.

### Redis latency (network + Lua)

```bash
make benchmark-redis-latency
# or with docker-compose Redis:
make benchmark-redis-docker
```

Measures Redis-backed `check_and_increment` latency across concurrency levels (10, 50, 100, 250). Writes `benchmarks/results/redis_latency_*.json`. Actual values come from that JSON artifact.

### Memory (local state)

```bash
make benchmark-memory
```

Uses `tracemalloc` while populating local-backend keys. Writes `benchmarks/results/memory_*.json` with peak allocation by key count and algorithm. Actual values come from that JSON artifact.

### Shared-quota consistency (Redis)

```bash
make benchmark-multi-instance
```

Runs **two Redis clients in one Python process** against a shared global limit (default 100/60s, tolerance ±2). Writes `benchmarks/results/multi_instance_*.json` with accepted counts per algorithm. This checks Lua atomicity under concurrent callers; it does **not** show cross-host distributed deployment behavior. Actual counts come from that JSON artifact.

### Fairness (shared-key contention)

```bash
make benchmark-fairness
```

Measures how capacity is distributed when multiple callers contend for one shared key. Writes `benchmarks/results/fairness_*.json` (coefficient of variation and accept totals). Distribution is driven primarily by scheduling and queue order, not by algorithm fairness guarantees. Actual values come from that JSON artifact.

---

## Reproduction commands

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
