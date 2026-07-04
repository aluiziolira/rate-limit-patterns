"""Shared types and event emission for the middleware integrations."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal

from rate_limit_patterns.models import AlgorithmType, RateLimitEvent, RateLimitResult

FailureMode = Literal["fail_closed", "fail_open"]
EventHookFailure = Literal["raise", "log"]

logger = logging.getLogger(__name__)


def emit_rate_limit_event(
    hook: Callable[[RateLimitEvent], None] | None,
    failure_policy: EventHookFailure,
    *,
    algorithm: AlgorithmType,
    result: RateLimitResult,
    backend_type: str,
    latency_ms: float,
) -> None:
    """Invoke the observability hook, honoring the configured failure policy."""
    if hook is None:
        return
    event = RateLimitEvent(
        algorithm=algorithm,
        allowed=result.allowed,
        remaining=result.remaining,
        retry_after=result.retry_after,
        backend_type=backend_type,
        latency_ms=latency_ms,
    )
    if failure_policy == "raise":
        hook(event)
        return
    try:
        hook(event)
    except Exception:
        logger.exception("Rate limit event hook failed")
