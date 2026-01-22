# Production Recipes

Practical deployment patterns, defaults, and anti-patterns for production-grade
rate limiting with this library.

## Key Extraction Patterns

**Per-user / API key**

- **Source**: authenticated principal ID or API key hash.
- **Key format**: `rate:user:{user_id}:window` (hash tag if Redis Cluster).
- **Notes**: avoid raw API keys in logs; hash or truncate if needed.
  - For Redis Cluster, prefer `backend.build_redis_cluster_key(...)` to ensure a stable hash tag.

**Per-organization / tenant**

- **Source**: org/tenant ID from auth token or request context.
- **Key format**: `rate:tenant:{tenant_id}:window`.
- **Notes**: use tenant-level limits for shared quotas; combine with per-user for fairness.

**Per-IP (proxy-aware)**

- **Source**: trusted proxy headers (e.g., `X-Forwarded-For`) with a validated proxy chain.
- **Key format**: `rate:ip:{client_ip}:window`.
- **Notes**: document which proxy headers are trusted; normalize IPv6 and IPv4.

## Multi-Limit Composition

Common patterns combine multiple limits for defense-in-depth:

- **Per-user + per-IP + global**: protects against credential sharing and floods.
- **Per-tenant + per-user**: enforces tenant quotas while preventing noisy neighbors.
- **Per-route + global**: protects expensive endpoints without throttling the entire API.

**Where to enforce**

- **Middleware**: best for coarse-grained or global limits shared across endpoints.
- **Application layer**: best for endpoint-specific limits or conditional checks.

## Redis Outage Playbook

Choose failure modes based on endpoint criticality:

- **Auth / security**: `fail_closed` (deny when Redis is down).
- **Read-only / public**: `fail_open` (serve traffic to avoid outages).
- **Background jobs**: `fail_open` with backpressure or job queue limits.

**Telemetry to capture**

- Backend availability errors (`RateLimitBackendUnavailableError`).
- Rate-limit denials (HTTP 429) and retry-after distribution.
- Event hook failures (if `event_hook` is enabled).

## Redis Operations Defaults

Start with conservative pool and timeout settings, then tune based on concurrency:

- `max_connections`: set to expected peak concurrency * per-request Redis usage.
- `socket_timeout`: 0.5s–1.0s for latency-sensitive APIs.
- `socket_connect_timeout`: 0.2s–0.5s for fast failover.
- `health_check_interval`: 30s–60s for long-lived pools.

Avoid unbounded pools; connection storms under load are a common failure mode.

## Terminology Consistency

The algorithm that stores per-request timestamps is called **Sliding Window Log**.
Avoid referring to it as a “counter” unless a counter-based variant is explicitly
introduced.

## Choosing an Algorithm (Checklist)

- **Need burst tolerance?** Use **Token Bucket**.
- **Need strict, audit-grade limits?** Use **Sliding Window Log** (note the O(N) memory cost).
- **Need smooth output rate?** Use **Leaky Bucket**.

See `docs/ALGORITHMS.md` for full trade-offs and implementation details.
