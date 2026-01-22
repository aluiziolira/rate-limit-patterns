"""Mock API server for integration benchmarks."""

from __future__ import annotations

import os
from typing import cast

from fastapi import FastAPI
from starlette.requests import Request

from rate_limit_patterns.backend.base import RateLimitBackend
from rate_limit_patterns.backend.local import LocalBackend
from rate_limit_patterns.backend.redis import RedisBackend
from rate_limit_patterns.middleware.asgi import RateLimitMiddleware
from rate_limit_patterns.models import AlgorithmType, RateLimitConfig

DEFAULT_LIMIT = 100
DEFAULT_PERIOD = 60
DEFAULT_ALGORITHM: AlgorithmType = "token_bucket"


def _default_key_extractor(request: Request) -> str:
    client = request.client
    if client is not None and client.host:
        return client.host
    return "unknown"


def _parse_int(value: str, name: str) -> int:
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _load_config() -> RateLimitConfig:
    algorithm_raw = os.getenv("RATE_ALGORITHM", DEFAULT_ALGORITHM)
    if algorithm_raw not in {"token_bucket", "sliding_window", "leaky_bucket"}:
        raise ValueError(f"Unsupported RATE_ALGORITHM: {algorithm_raw}")

    algorithm = cast(AlgorithmType, algorithm_raw)
    limit = _parse_int(os.getenv("RATE_LIMIT", str(DEFAULT_LIMIT)), "RATE_LIMIT")
    period = _parse_int(os.getenv("RATE_PERIOD", str(DEFAULT_PERIOD)), "RATE_PERIOD")
    burst_size = limit if algorithm == "token_bucket" else None

    return RateLimitConfig(
        algorithm=algorithm,
        limit=limit,
        period=period,
        burst_size=burst_size,
    )


def _load_backend() -> RateLimitBackend:
    redis_url = os.getenv("REDIS_URL")
    if redis_url:
        return RedisBackend(url=redis_url, key_prefix="bench:")
    return LocalBackend()


app = FastAPI()
limited_app = FastAPI()
backend = _load_backend()
config = _load_config()

limited_app.add_middleware(
    RateLimitMiddleware,
    backend=backend,
    config=config,
    key_extractor=_default_key_extractor,
)


@limited_app.get("/")
async def limited() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def status() -> dict[str, str]:
    return {"status": "ok"}


app.mount("/api/limited", limited_app)


if isinstance(backend, RedisBackend):

    @limited_app.on_event("startup")
    async def _startup() -> None:
        await backend.initialize()

    @limited_app.on_event("shutdown")
    async def _shutdown() -> None:
        await backend.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
