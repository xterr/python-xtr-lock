"""End-to-end: an application listing LockBundle locks through the stores it configured."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from xtr_dependency_injection import Kernel

from tests.support.redis_server import redis_dsn
from xtr_lock import LockFactory

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio


def _kernel(tmp_path: Path, redis: str = "redis://localhost:6379/15") -> Kernel:
    return Kernel(
        "tests.fixtures.app_lock",
        env="test",
        environ={"LOCK_TEST_DSN": f"flock://{tmp_path}", "LOCK_TEST_REDIS_DSN": redis},
    )


async def test_two_kernels_share_the_default_file_lock(tmp_path: Path, resource: str) -> None:
    async with await _kernel(tmp_path).boot() as first, await _kernel(tmp_path).boot() as second:
        holder = (await first.container.get(LockFactory)).create_lock(resource)
        waiter = (await second.container.get(LockFactory)).create_lock(resource)

        assert await holder.acquire()
        assert not await waiter.acquire()

        waiting = asyncio.create_task(waiter.acquire(blocking=True))
        await asyncio.sleep(0.05)
        await holder.release()

        assert await asyncio.wait_for(waiting, timeout=5)
        await waiter.release()


async def test_a_redis_dsn_resource_locks_and_closes_its_connection(
    tmp_path: Path,
    resource: str,
) -> None:
    async with await _kernel(tmp_path, redis_dsn()).boot() as booted:
        factory = await booted.container.get(LockFactory, "redis")
        lock = factory.create_lock(resource, ttl=5)

        async with lock:
            assert await lock.is_acquired()
            assert not await factory.create_lock(resource).acquire()

        assert not await lock.is_acquired()


async def test_a_referenced_redis_client_is_shared_and_left_to_the_application(
    resource: str,
) -> None:
    _ = redis_dsn()

    async with await Kernel("tests.fixtures.app_lock_connection", env="test").boot() as booted:
        factory = await booted.container.get(LockFactory)

        async with factory.create_lock(resource, ttl=5) as lock:
            assert await lock.is_acquired()
