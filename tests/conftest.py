"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import asyncio
from collections.abc import Generator

import pytest


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# Placeholder for future fixtures:
# - mock_redis_backend
# - local_backend
# - sample_configs
# - fastapi_test_client
