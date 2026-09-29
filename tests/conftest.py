"""Shared test fixtures."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from fakeredis import FakeAsyncRedis, FakeServer
from xtr_clock import Clock

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Generator

    from redis.asyncio import Redis


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
    """Name a resource no other test uses."""
    return f"xtr-lock-test:{uuid4().hex}"


@pytest.fixture
async def redis_client() -> AsyncIterator[Redis]:
    """Yield a client on a Redis server of its own, in this process, running the store's scripts."""
    client = FakeAsyncRedis(server=FakeServer())
    try:
        yield client
    finally:
        await client.aclose()
