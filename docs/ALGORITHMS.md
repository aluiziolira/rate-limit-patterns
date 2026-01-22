# Rate Limiting Algorithms

This document details the algorithmic core of the rate limiting engine. Each algorithm implements a common stateless protocol, designed to separate **logic** (calculation) from **persistence** (storage).

## Architectural Overview

The project employs a **Functional, Stateless Architecture** to maximize scalability and reliability in distributed environments.

### The `RateLimitAlgorithm` Protocol

All algorithms are implemented as "pure functions". They do not maintain internal state between calls. Instead, the current state is passed in, processed, and a new state is returned.

```python
# Conceptual signature
(allowed, new_state, metadata) = compute(current_state, configuration, current_time)
```

**System Benefits:**
*   **Concurrency Safe**: Logic execution contains no side effects, eliminating race conditions at the algorithm level.
*   **Storage Agnostic**: The simple `dict` state is easily serialized to Redis, Memcached, or local memory.
*   **Monotonicity**: Time calculations proactively guard against clock skew and negative elapsed time using `max(0, elapsed)`.

---

## Algorithm Inventory

### 1. Token Bucket ("The Generalist")

The industry standard for API rate limiting. It models a bucket that refills at a constant rate, allowing for short-term bursts while enforcing a long-term average.

*   **Behavior**: **Elastic**. Traffic flows freely up to the `burst_size`, then throttles to the fill rate.
*   **State**: `O(1)` constant size (Current Tokens + Last Refill Timestamp).
*   **Mechanism**: Uses "lazy refill" mechanics. Tokens are mathematically replenished only when a request arrives, avoiding expensive background timer threads.

**Best For:**
*   **Public HTTP APIs**: Accommodates natural user behavior (e.g., page loads triggering simultaneous requests).
*   **High-Volume Distributed Systems**: Minimal serialization overhead and storage cost in Redis.

### 2. Sliding Window Log ("The Auditor")

A high-precision algorithm that tracks the exact timestamp of every request within the time window.

*   **Behavior**: **Rigid**. Provides a mathematical guarantee that the limit is never exceeded by even a single request.
*   **State**: `O(N)` linear growth. Stores a list of timestamps `[t1, t2, t3...]`.
*   **Warning**: Storage and processing costs grow linearly with the rate limit. A limit of 10,000 req/min requires storing and sorting 10,000 timestamps, creating significant Redis memory pressure.
*   **Config Guardrail**: `RateLimitConfig` emits a `RuntimeWarning` when `limit > 1000` for Sliding Window Log unless `suppress_warnings=True`.

**Best For:**
*   **Security Controls**: Login attempts, PIN verification, or abuse prevention where exact enforcement is critical.
*   **Billing Quotas**: Hard limits where overages have financial consequences.

### 3. Leaky Bucket ("The Shaper")

Focuses on output stability rather than input acceptance. It simulates a queue that drains at a constant flow rate.

*   **Behavior**: **Smoothed**. Converts bursty input traffic into a steady, predictable output stream.
*   **State**: `O(1)` constant size (Current "Water" Level + Last Leak Timestamp).
*   **Mechanism**: Similar to Token Bucket but with inverted logic; requests add to the bucket, and time drains it "leaks" it out.

**Best For:**
*   **Infrastructure Protection**: Guarding limited-concurrency resources (e.g., legacy databases, thread pools).
*   **Webhook Ingress**: Preventing "Thundering Herd" problems when receiving batched events from external webhooks.

---

## Engineering Trade-offs

| Feature               | Token Bucket                | Sliding Window Log               | Leaky Bucket              |
| :-------------------- | :-------------------------- | :------------------------------- | :------------------------ |
| **Complexity (Time)** | **O(1)** - Fast             | **O(N)** - Slower at high limits | **O(1)** - Fast           |
| **Storage (Redis)**   | **Low** - Fixed ~50 bytes   | **High** - Grows with traffic    | **Low** - Fixed ~50 bytes |
| **Burst Handling**    | Configurable (`burst_size`) | None (Hard Limit)                | None (Smooths Traffic)    |
| **Precision**         | Interval-based Average      | Exact Rolling Window             | Interval-based Average    |
| **Fairness**          | First-come, first-served    | Strict FIFO                      | Queued semantics          |

**Fairness note:** fairness characteristics are *observed* in benchmarks and depend on
runtime scheduling and key distribution. They are not guaranteed unless explicitly
enforced by the calling system.

### Key Implementation Details
*   **Float Precision**: All algorithms utilize floating-point math to handle sub-second rates accurately, avoiding the "stair-step" inaccuracies common in integer-only implementations.
*   **Backoff Guidance**: Algorithms return `retry_after` metadata, enabling clients to implement jittered backoff rather than busy-looping.

---

## Decision Guide

Select the algorithm that matches your **traffic shape requirements** rather than just "rate limiting".

### Scenario 1: The Public REST API
**Recommendation**: `TokenBucket`
*   **Why**: Users click fast. A user loading a dashboard might fire 10 requests in 100ms. Token bucket permits this burst but stops them from sustaining 100 req/s.

### Scenario 2: The Login Form
**Recommendation**: `SlidingWindowLog`
*   **Why**: You need to stop a brute-force attack at *exactly* 5 attempts. "Around 5" is not secure. The volume is low, so the O(N) cost is negligible.

### Scenario 3: The Slow Database Worker
**Recommendation**: `LeakyBucket`
*   **Why**: Your worker can only handle 10 writes/sec. If 100 jobs arrive instantly, Leaky Bucket forces them to queue and process at 10/sec, preventing database lock contention.
