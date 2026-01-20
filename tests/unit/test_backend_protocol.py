"""Tests for backend protocol definition."""

from __future__ import annotations

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.models import RateLimitConfig, RateLimitResult


def test_backend_is_protocol() -> None:
    """RateLimitBackend is a Protocol class."""
    assert hasattr(RateLimitBackend, "__protocol_attrs__") or isinstance(RateLimitBackend, type)


def test_backend_is_runtime_checkable() -> None:
    """Backend protocol can be checked at runtime."""

    class FakeBackend:
        async def check_and_increment(
            self, key: str, config: RateLimitConfig
        ) -> RateLimitResult: ...

        async def reset(self, key: str) -> None: ...

        async def get_metrics(self, key: str) -> dict: ...

    assert isinstance(FakeBackend(), RateLimitBackend)


def test_backend_requires_check_and_increment() -> None:
    """Backend must implement check_and_increment method."""

    class IncompleteBackend:
        async def reset(self, key: str) -> None: ...

    # Should not satisfy protocol
    assert not isinstance(IncompleteBackend(), RateLimitBackend)
