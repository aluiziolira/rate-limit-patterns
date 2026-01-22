"""Utilities for building rate limit headers."""

from __future__ import annotations

import math
from typing import Literal

from rate_limit_patterns.models import RateLimitResult

HeaderStyle = Literal["x", "standard", "both"]


def build_rate_limit_headers(
    result: RateLimitResult, *, header_style: HeaderStyle = "x"
) -> dict[str, str]:
    """Build HTTP headers for a rate limit result."""
    headers: dict[str, str] = {}
    if header_style in ("x", "both"):
        headers["X-RateLimit-Limit"] = str(result.limit)
        headers["X-RateLimit-Remaining"] = str(result.remaining)
    if header_style in ("standard", "both"):
        headers["RateLimit-Limit"] = str(result.limit)
        headers["RateLimit-Remaining"] = str(result.remaining)
    if result.retry_after is not None:
        headers["Retry-After"] = str(result.retry_after)
    if result.reset_at is not None:
        reset_at = str(int(math.ceil(result.reset_at)))
        if header_style in ("x", "both"):
            headers["X-RateLimit-Reset"] = reset_at
        if header_style in ("standard", "both"):
            headers["RateLimit-Reset"] = reset_at
    return headers


def build_rate_limit_header_bytes(
    result: RateLimitResult, *, header_style: HeaderStyle = "x"
) -> list[tuple[bytes, bytes]]:
    """Build ASGI header tuples for a rate limit result."""
    return [
        (name.encode(), value.encode())
        for name, value in build_rate_limit_headers(result, header_style=header_style).items()
    ]
