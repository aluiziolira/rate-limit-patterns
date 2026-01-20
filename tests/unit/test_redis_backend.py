"""Unit tests for Redis backend (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.models import RateLimitConfig


class TestRedisBackendUnit:
    """Unit tests with mocked Redis."""

    @pytest.fixture
    def config(self) -> RateLimitConfig:
        """Create test configuration."""
        return RateLimitConfig(
            algorithm="token_bucket",
            limit=100,
            period=60,
            burst_size=200,
        )

    @pytest.mark.asyncio
    async def test_backend_loads_lua_scripts(self, mock_redis: MagicMock) -> None:
        """Backend loads Lua scripts on initialization."""
        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            await backend.initialize()

            assert mock_redis.script_load.called

    @pytest.mark.asyncio
    async def test_check_calls_evalsha(
        self, mock_redis: MagicMock, config: RateLimitConfig
    ) -> None:
        """check_and_increment uses evalsha for atomic operations."""
        mock_redis.evalsha = AsyncMock(return_value=[1, 199, 0, 1705680000])

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            backend._script_shas = {"token_bucket": "fake_sha"}

            result = await backend.check_and_increment("user:123", config)

            assert mock_redis.evalsha.called
            assert result.allowed is True

    @pytest.mark.asyncio
    async def test_reset_deletes_key(self, mock_redis: MagicMock) -> None:
        """reset() deletes the Redis key."""
        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")

            await backend.reset("user:123")

            mock_redis.delete.assert_called_with("user:123")
