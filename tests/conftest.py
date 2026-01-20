"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_redis() -> MagicMock:
    """Mock Redis client for unit tests."""
    redis = MagicMock()
    redis.evalsha = AsyncMock()
    redis.script_load = AsyncMock(return_value="fake_sha")
    redis.delete = AsyncMock()
    redis.hgetall = AsyncMock(return_value={})
    return redis


@pytest.fixture
def redis_url() -> str:
    """Redis URL for integration tests."""
    return os.getenv("REDIS_URL", "redis://localhost:6379/15")


# Placeholder for future fixtures:
# - mock_redis_backend
# - local_backend
# - sample_configs
# - fastapi_test_client
