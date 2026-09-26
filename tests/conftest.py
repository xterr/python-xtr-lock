"""Shared test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError
from xtr_clock import Clock

from tests.support.redis_server import redis_dsn

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolate_clock() -> Generator[None, None, None]:
    """Keep a test that installs a clock from reaching the next one."""
    with Clock.using(Clock.get()):
        yield


@pytest.fixture
def resource() -> str:
    """Name a resource no other test, and no earlier run against a shared server, uses."""
    return f"xtr-lock-test:{uuid4().hex}"


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Yield a client for ``REDIS_DSN``, closed afterwards; skip when there is no server."""
    # Only the keyword arguments are untyped, and none are passed.
    client = Redis.from_url(redis_dsn())  # pyright: ignore[reportUnknownMemberType]
    try:
        try:
            _ = await client.ping()  # pyright: ignore[reportUnknownMemberType] -- ping's reply type is a union with the blocking client's
        except RedisConnectionError as error:
            pytest.skip(f"Redis is unreachable: {error}")
        yield client
    finally:
        await client.aclose()
