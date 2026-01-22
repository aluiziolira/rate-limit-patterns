# API Contract

This document describes the public API surface and the semantic contract for
rate-limit results and headers.

## Installation Paths

- Minimal (local backend only): `pip install rate-limit-patterns`
- Redis backend: `pip install rate-limit-patterns[redis]`
- ASGI middleware (Starlette): `pip install rate-limit-patterns[asgi]`
- FastAPI dependency: `pip install rate-limit-patterns[fastapi]`

## Public Entrypoints

- `RateLimiter` (facade; supports `async with` and forwards `initialize()`/`close()`)
- `SyncRateLimiter` (blocking facade; supports `with` and forwards `initialize()`/`close()`)
- `LocalBackend` (in-memory)
- `RedisBackend` (distributed; requires `redis` extra)
- `SyncLocalBackend` (blocking in-memory)
- `SyncRedisBackend` (blocking Redis)
- `backend.build_redis_cluster_key` (Redis Cluster hash-tag helper)
- `RateLimitEvent` (observability event model)
- `rate_limit` decorator
- `middleware.asgi.RateLimitMiddleware` (requires `asgi` extra)
- `middleware.fastapi.RateLimitDependency` (requires `fastapi` extra)

## Lifecycle (Redis)

Call `initialize()` during application startup and `close()` on shutdown. For
apps that already use `RateLimiter`, `async with` handles this automatically.

```python
backend = RedisBackend(url="redis://localhost:6379/0")
await backend.initialize()
# use backend ...
await backend.close()
```

## Redis Cluster Key Hashing

Sliding Window Log uses two Redis keys: the window zset (`<key>`) and a sequence
counter (`<key>:seq`). In Redis Cluster, both keys must map to the same hash
slot. Ensure the rate-limit key includes a shared hash tag (e.g.,
`rate:{user}:window` and the derived `rate:{user}:window:seq`).

Use `backend.build_redis_cluster_key()` to construct tagged keys, or enable
`RedisBackend(cluster_mode=True)` to enforce hash tags at runtime.

Example:

```python
from rate_limit_patterns.backend import build_redis_cluster_key

key = build_redis_cluster_key(prefix="rate", tag="user:42", suffix="window")
# key == "rate:{user:42}:window"
```

## RedisBackend URL Configuration

When using `RedisBackend(url=...)`, the backend creates its own connection pool.
To avoid connection exhaustion under load, set explicit pool limits and health
checks:

- `max_connections`: hard cap on open connections.
- `socket_keepalive`: enable TCP keepalive for long-lived connections.
- `health_check_interval`: seconds between connection health checks.
- `socket_timeout` / `socket_connect_timeout`: timeouts for IO and connect.
- `cluster_mode`: enforce hash-tagged keys for Sliding Window Log on Redis Cluster.

These options are ignored when `client=` is provided. For advanced setups
(Redis Cluster, TLS, custom pools), inject a pre-configured client instead.

## Lifecycle (Synchronous)

```python
backend = SyncLocalBackend()
backend.initialize()
# use backend ...
backend.close()
```

## RateLimitConfig

Fields:

- `algorithm`: `"token_bucket" | "sliding_window" | "leaky_bucket"`
- `limit`: integer rate per period
- `period`: window length in seconds
- `burst_size`: optional capacity override
- `cleanup_interval`: local backend cleanup cadence (seconds; <= 0 disables periodic cleanup)
- `suppress_warnings`: disable configuration warnings for high-memory settings

`RateLimitConfig` emits a `RuntimeWarning` when Sliding Window Log limits exceed
1000 requests per window, unless `suppress_warnings=True`.

## Local Backend Cleanup

For `LocalBackend`, a background cleanup task starts lazily on the first
`check_and_increment()` call when `cleanup_interval > 0`. You can still call
`initialize()`/`close()` to control lifecycle explicitly.

## Time Override Semantics

- `now=None` uses the backend time source (monotonic wall time for local, Redis `TIME` for Redis).
- `now=0.0` is treated as an explicit Unix timestamp override (epoch 0), not as a sentinel.

Algorithm semantics:

- **Token bucket**
  - `limit` = refill amount per `period`
  - `burst_size` = bucket capacity (defaults to `limit`)
- **Leaky bucket**
  - `limit` = leak rate per `period`
  - `burst_size` = queue capacity (defaults to `limit`)
- **Sliding Window Log**
  - `burst_size` is ignored

## RateLimitResult

Fields:

- `allowed`: request is permitted
- `remaining`: non-negative integer capacity remaining
- `retry_after`: seconds until the next request can be allowed (set when denied)
- `reset_at`: Unix timestamp (seconds) for the next reset boundary
- `request_count`: algorithm-specific occupancy count

Per-algorithm result semantics:

- **Token bucket**
  - `remaining` = `floor(tokens_remaining)`
  - `retry_after` = time until at least one token is available
  - `reset_at` = time when the bucket is fully refilled
  - `request_count` = `floor(burst_size - tokens_remaining)`
  - Note: `request_count` can exceed `limit` when `burst_size > limit`
- **Sliding Window Log**
  - `remaining` = `limit - requests_in_window`
  - `retry_after` = time until the oldest request expires (when denied)
  - `reset_at` = time when the oldest request expires
  - `request_count` = `requests_in_window`
  - Boundary: timestamps at `now - period` are excluded (window is `(now - period, now]`)
- **Leaky bucket**
  - `remaining` = `floor(capacity - queue_size)`
  - `retry_after` = time until one slot drains (when denied)
  - `reset_at` = time when the queue drains to zero
  - `request_count` = `floor(queue_size)`

## Key Extraction Guidance

- Prefer stable identifiers (user or API key) over IP addresses.
- If you must use IP, normalize via trusted proxy headers and document the source.
- When using `RateLimitMiddleware`, pass a custom `key_extractor` to control isolation.

## Decorator Options

The `rate_limit` decorator accepts:

- `key`: a kwarg name to extract or a static key string.
- `key_func`: optional callable for deriving keys from args/kwargs.
- `algorithm`: override the default `token_bucket`.

## HTTP Headers

The middleware and dependency map results to headers. By default, only the
legacy `X-RateLimit-*` headers are emitted. Configure `header_style` to switch
to IETF-style `RateLimit-*` headers or emit both.

`header_style` accepts `"x"`, `"standard"`, or `"both"`.

`X-RateLimit-*` (default):

- `X-RateLimit-Limit` = `limit`
- `X-RateLimit-Remaining` = `remaining`
- `Retry-After` = `retry_after` (when set)
- `X-RateLimit-Reset` = `ceil(reset_at)` (Unix seconds)

`RateLimit-*` (standard):

- `RateLimit-Limit` = `limit`
- `RateLimit-Remaining` = `remaining`
- `Retry-After` = `retry_after` (when set)
- `RateLimit-Reset` = `ceil(reset_at)` (Unix seconds)

## Failure Policy (Integrations)

`RateLimitMiddleware` and `RateLimitDependency` accept a `failure_mode` setting
to control behavior when the backend is unavailable:

- `fail_closed`: return 503 (middleware) or raise HTTPException (FastAPI).
- `fail_open`: allow the request without rate-limit headers.

The policy is triggered on `RateLimitBackendUnavailableError`.

## Observability Hook

`RateLimitMiddleware` and `RateLimitDependency` accept an `event_hook` callback
that receives a `RateLimitEvent` for every check (allowed or denied). The hook
is synchronous and is called after the backend responds. Control failures with
`event_hook_failure`:

- `raise`: propagate the exception (current default).
- `log`: log the exception and continue (recommended in production if hooks are not guaranteed safe).

## Error Model

- `RateLimitExceeded`: raised by the `rate_limit` decorator when denied
- `RateLimitBackendUnavailableError`: backend connectivity or timeout errors
- `RateLimitBackendConfigurationError`: invalid algorithm or script initialization problems
- `ValueError`: invalid `RateLimitConfig` values
