"""The application's own Redis client, which it opens and closes."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator  # noqa: TC003 — the container reads the annotation.

from redis.asyncio import Redis
from xtr_dependency_injection import as_service

LOCKS = "locks"


@as_service(qualifier=LOCKS)
async def locks_redis() -> AsyncIterator[Redis]:
    dsn = os.environ.get("REDIS_DSN", "redis://localhost:6379/15")
    # Only the keyword arguments are untyped, and none are passed.
    client = Redis.from_url(dsn)  # pyright: ignore[reportUnknownMemberType]
    try:
        yield client
    finally:
        await client.aclose()
