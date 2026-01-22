"""CI guardrails for integration coverage."""

from __future__ import annotations

import os


def test_redis_url_configured_in_ci() -> None:
    """Ensure Redis integration tests run in CI."""
    if os.getenv("CI") == "true":
        assert os.getenv("REDIS_URL"), "REDIS_URL must be set in CI"
