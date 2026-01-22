"""Unit tests for Redis backend (mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from redis.exceptions import (
    ConnectionError as RedisConnectionError,
)
from redis.exceptions import (
    NoScriptError,
)
from redis.exceptions import (
    TimeoutError as RedisTimeoutError,
)

from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.exceptions import (
    RateLimitBackendConfigurationError,
    RateLimitBackendUnavailableError,
)
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
        mock_redis.evalsha = AsyncMock(return_value=[1, 199, 0, 1705680000, 1])

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            backend._script_shas = {"token_bucket": "fake_sha"}

            result = await backend.check_and_increment("user:123", config)

            assert mock_redis.evalsha.called
            assert result.allowed is True
            assert result.request_count == 1

    @pytest.mark.asyncio
    async def test_now_override_zero_is_passed_through(
        self, mock_redis: MagicMock, config: RateLimitConfig
    ) -> None:
        """Explicit now=0.0 is forwarded instead of using Redis time."""
        mock_redis.evalsha = AsyncMock(return_value=[1, 199, 0, 1705680000, 1])

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            backend._script_shas = {"token_bucket": "fake_sha"}

            await backend.check_and_increment("user:123", config, now=0.0)

            args = mock_redis.evalsha.call_args[0]
            assert args[-1] == 0.0

    @pytest.mark.asyncio
    async def test_injected_client_usage(
        self, mock_redis: MagicMock, config: RateLimitConfig
    ) -> None:
        """Injected Redis clients are used directly."""
        mock_redis.evalsha = AsyncMock(return_value=[1, 199, 0, 1705680000, 1])

        backend = RedisBackend(client=mock_redis)
        backend._script_shas = {"token_bucket": "fake_sha"}

        await backend.check_and_increment("user:123", config)

        assert mock_redis.evalsha.called

    @pytest.mark.asyncio
    async def test_sliding_window_uses_two_keys(self, mock_redis: MagicMock) -> None:
        """Sliding window uses window and sequence keys in evalsha."""
        mock_redis.evalsha = AsyncMock(return_value=[1, 2, 0, 1705680000, 1])

        config = RateLimitConfig(
            algorithm="sliding_window",
            limit=5,
            period=60,
        )

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost", key_prefix="rl:")
            backend._script_shas = {"sliding_window": "fake_sha"}

            await backend.check_and_increment("user:123", config)

            args = mock_redis.evalsha.call_args[0]
            assert args[1] == 2
            assert args[2] == "rl:user:123"
            assert args[3] == "rl:user:123:seq"

    @pytest.mark.asyncio
    async def test_cluster_mode_requires_hash_tag(self, mock_redis: MagicMock) -> None:
        """Cluster mode enforces hash tags for sliding window keys."""
        mock_redis.evalsha = AsyncMock(return_value=[1, 2, 0, 1705680000, 1])
        config = RateLimitConfig(
            algorithm="sliding_window",
            limit=5,
            period=60,
        )

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost", cluster_mode=True)
            backend._script_shas = {"sliding_window": "fake_sha"}

            with pytest.raises(RateLimitBackendConfigurationError):
                await backend.check_and_increment("user:123", config)

    @pytest.mark.asyncio
    async def test_cluster_mode_allows_tagged_keys(self, mock_redis: MagicMock) -> None:
        """Cluster mode accepts hash-tagged keys."""
        mock_redis.evalsha = AsyncMock(return_value=[1, 2, 0, 1705680000, 1])
        config = RateLimitConfig(
            algorithm="sliding_window",
            limit=5,
            period=60,
        )

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost", cluster_mode=True)
            backend._script_shas = {"sliding_window": "fake_sha"}

            await backend.check_and_increment("rate:{user}:window", config)

            assert mock_redis.evalsha.called

    @pytest.mark.asyncio
    async def test_initialize_is_idempotent(self, mock_redis: MagicMock) -> None:
        """initialize loads missing scripts even when client exists."""
        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            await backend.initialize()
            backend._script_shas.clear()
            await backend.initialize()

            assert mock_redis.script_load.called

    @pytest.mark.asyncio
    async def test_lazy_initialize_on_check(
        self, mock_redis: MagicMock, config: RateLimitConfig
    ) -> None:
        """check_and_increment lazily initializes scripts."""
        mock_redis.evalsha = AsyncMock(return_value=[1, 199, 0, 1705680000, 1])

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            backend.initialize = AsyncMock(  # type: ignore[method-assign]
                side_effect=lambda: backend._script_shas.update({"token_bucket": "fake_sha"})
            )

            await backend.check_and_increment("user:123", config)

            assert backend.initialize.called

    @pytest.mark.asyncio
    async def test_noscript_recovers(self, mock_redis: MagicMock, config: RateLimitConfig) -> None:
        """NOSCRIPT triggers reload and retry once."""
        mock_redis.evalsha = AsyncMock(
            side_effect=[
                NoScriptError("NOSCRIPT"),
                [1, 199, 0, 1705680000, 1],
            ]
        )

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            backend._script_shas = {"token_bucket": "stale_sha"}

            result = await backend.check_and_increment("user:123", config)

            assert result.allowed is True
            assert mock_redis.script_load.called
            assert mock_redis.evalsha.call_count == 2

    @pytest.mark.asyncio
    async def test_timeout_translates_to_backend_error(
        self, mock_redis: MagicMock, config: RateLimitConfig
    ) -> None:
        """Redis timeouts translate to backend-unavailable error."""
        mock_redis.evalsha = AsyncMock(side_effect=RedisTimeoutError("timeout"))

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            backend._script_shas = {"token_bucket": "fake_sha"}

            with pytest.raises(RateLimitBackendUnavailableError):
                await backend.check_and_increment("user:123", config)

    @pytest.mark.asyncio
    async def test_connection_error_translates_to_backend_error(
        self, mock_redis: MagicMock, config: RateLimitConfig
    ) -> None:
        """Redis connection errors translate to backend-unavailable error."""
        mock_redis.evalsha = AsyncMock(side_effect=RedisConnectionError("down"))

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")
            backend._script_shas = {"token_bucket": "fake_sha"}

            with pytest.raises(RateLimitBackendUnavailableError):
                await backend.check_and_increment("user:123", config)

    @pytest.mark.asyncio
    async def test_socket_timeouts_passed_to_factory(self, mock_redis: MagicMock) -> None:
        """Socket timeout settings are passed to the Redis factory."""
        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ) as redis_factory:
            backend = RedisBackend(
                url="redis://localhost",
                socket_timeout=1.5,
                socket_connect_timeout=2.5,
            )
            await backend.initialize()

            redis_factory.assert_called_with(
                "redis://localhost",
                socket_timeout=1.5,
                socket_connect_timeout=2.5,
            )

    @pytest.mark.asyncio
    async def test_pool_settings_passed_to_factory(self, mock_redis: MagicMock) -> None:
        """Pool settings are passed to the Redis factory."""
        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ) as redis_factory:
            backend = RedisBackend(
                url="redis://localhost",
                max_connections=20,
                socket_keepalive=True,
                health_check_interval=30.0,
            )
            await backend.initialize()

            redis_factory.assert_called_with(
                "redis://localhost",
                max_connections=20,
                socket_keepalive=True,
                health_check_interval=30.0,
            )

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

    @pytest.mark.asyncio
    async def test_get_metrics_for_hash(self, mock_redis: MagicMock) -> None:
        """get_metrics returns hash-based metrics for token/leaky buckets."""
        mock_redis.type = AsyncMock(return_value=b"hash")
        mock_redis.hmget = AsyncMock(return_value=[b"5.0", b"1700.0", b"2.0", b"1600.0"])

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")

            metrics = await backend.get_metrics("user:123")

            assert metrics["storage_type"] == "hash"
            assert metrics["tokens"] == 5.0
            assert metrics["last_refill"] == 1700.0
            assert metrics["queue_size"] == 2.0
            assert metrics["last_leak"] == 1600.0

    @pytest.mark.asyncio
    async def test_get_metrics_for_zset(self, mock_redis: MagicMock) -> None:
        """get_metrics returns zset-based metrics for sliding window."""
        mock_redis.type = AsyncMock(return_value=b"zset")
        mock_redis.zcard = AsyncMock(return_value=2)
        mock_redis.zrange = AsyncMock(return_value=[("member", 1700000000000.0)])

        with patch(
            "rate_limit_patterns.backend.redis.Redis",
            return_value=mock_redis,
        ):
            backend = RedisBackend(url="redis://localhost")

            metrics = await backend.get_metrics("user:123")

            assert metrics["storage_type"] == "zset"
            assert metrics["count"] == 2
            assert metrics["window_start"] == 1700000000.0
