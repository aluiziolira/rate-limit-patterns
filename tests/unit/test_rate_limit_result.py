"""Unit tests for RateLimitResult."""

from __future__ import annotations

import pytest

from rate_limit_patterns.models import RateLimitResult


class TestRateLimitResult:
    """Tests for RateLimitResult dataclass."""

    def test_allowed_result_fields(self) -> None:
        """Allowed result contains all expected fields."""
        result = RateLimitResult(
            allowed=True,
            limit=100,
            remaining=99,
            reset=1234567890,
        )
        assert result.allowed is True
        assert result.limit == 100
        assert result.remaining == 99
        assert result.reset == 1234567890
        assert result.retry_after is None

    def test_denied_result_includes_retry_after(self) -> None:
        """Denied result includes retry_after field."""
        result = RateLimitResult(
            allowed=False,
            limit=100,
            remaining=0,
            reset=1234567890,
            retry_after=30,
        )
        assert result.allowed is False
        assert result.limit == 100
        assert result.remaining == 0
        assert result.reset == 1234567890
        assert result.retry_after == 30

    def test_denied_result_without_retry_after(self) -> None:
        """Denied result can omit retry_after (defaults to None)."""
        result = RateLimitResult(
            allowed=False,
            limit=100,
            remaining=0,
            reset=1234567890,
        )
        assert result.allowed is False
        assert result.retry_after is None

    def test_result_is_immutable(self) -> None:
        """Result dataclass is frozen and raises AttributeError on assignment."""
        result = RateLimitResult(
            allowed=True,
            limit=100,
            remaining=99,
            reset=1234567890,
        )
        with pytest.raises(AttributeError):
            result.allowed = False

    def test_result_remaining_cannot_exceed_limit(self) -> None:
        """Remaining cannot exceed the limit."""
        result = RateLimitResult(
            allowed=True,
            limit=100,
            remaining=150,
            reset=1234567890,
        )
        assert result.remaining <= result.limit
