"""End-to-end: an application listing LockBundle locks through the stores it configured."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from xtr_dependency_injection import Kernel

from xtr_lock import LockFactory

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        "tests.fixtures.app_lock",
        env="test",
        environ={
            "LOCK_TEST_DSN": f"flock://{tmp_path}",
            "LOCK_TEST_REDIS_DSN": "redis://localhost:6379/15",
        },
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


async def test_a_referenced_redis_client_is_shared_and_left_to_the_application(
    resource: str,
) -> None:
    async with await Kernel("tests.fixtures.app_lock_connection", env="test").boot() as booted:
        factory = await booted.container.get(LockFactory)

        async with factory.create_lock(resource, ttl=5) as lock:
            assert await lock.is_acquired()
