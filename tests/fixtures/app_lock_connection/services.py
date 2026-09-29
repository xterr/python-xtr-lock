"""The application's own Redis client, which it opens and closes."""

from __future__ import annotations

from collections.abc import AsyncIterator  # noqa: TC003 — the container reads the annotation.

from fakeredis import FakeAsyncRedis, FakeServer
from redis.asyncio import Redis  # noqa: TC002 — the container reads the annotation.
from xtr_dependency_injection import as_service

LOCKS = "locks"


@as_service(qualifier=LOCKS)
async def locks_redis() -> AsyncIterator[Redis]:
    # A server of its own, in this process, running the store's scripts.
    client = FakeAsyncRedis(server=FakeServer())
    try:
        yield client
    finally:
        await client.aclose()
