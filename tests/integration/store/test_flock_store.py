"""Another process holds the lock: saving conflicts, waiting waits, and a dying holder frees it."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING

import pytest

from xtr_lock import FlockStore, Key, LockConflictedError, LockFactory

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio

_HOLDER = """
import asyncio
import sys

from xtr_lock import FlockStore, Key


async def main() -> None:
    store = FlockStore(sys.argv[1])
    key = Key(sys.argv[2])
    await store.save(key)
    print("locked", flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    await asyncio.sleep(float(sys.argv[3]))
    await store.delete(key)


asyncio.run(main())
"""


async def _spawn_holder(
    lock_path: Path,
    resource: str,
    hold_after_signal: float,
) -> asyncio.subprocess.Process:
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _HOLDER,
        str(lock_path),
        resource,
        str(hold_after_signal),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
    )
    assert child.stdout is not None
    line = await asyncio.wait_for(child.stdout.readline(), timeout=10)
    assert line.strip() == b"locked"

    return child


def _signal(child: asyncio.subprocess.Process) -> None:
    assert child.stdin is not None
    child.stdin.write(b"go\n")


async def test_blocking_locks(tmp_path: Path, resource: str) -> None:
    child = await _spawn_holder(tmp_path, resource, hold_after_signal=0.05)
    store = FlockStore(tmp_path)
    key = Key(resource)

    try:
        with pytest.raises(LockConflictedError):
            await store.save(key)
    finally:
        _signal(child)

    await asyncio.wait_for(store.wait_and_save(key), timeout=10)
    assert await store.exists(key)
    await store.delete(key)

    assert await child.wait() == 0


async def test_a_holder_that_dies_frees_the_lock(tmp_path: Path, resource: str) -> None:
    child = await _spawn_holder(tmp_path, resource, hold_after_signal=3600)
    store = FlockStore(tmp_path)
    key = Key(resource)

    with pytest.raises(LockConflictedError):
        await store.save(key)

    child.kill()
    _ = await child.wait()

    await asyncio.wait_for(store.wait_and_save(key), timeout=10)
    assert await store.exists(key)
    await store.delete(key)


async def test_a_lock_used_as_a_context_waits_for_the_other_process(
    tmp_path: Path,
    resource: str,
) -> None:
    child = await _spawn_holder(tmp_path, resource, hold_after_signal=0.1)
    lock = LockFactory(FlockStore(tmp_path)).create_lock(resource)

    assert not await lock.acquire()
    _signal(child)

    async with lock:
        assert await lock.is_acquired()

    assert not await lock.is_acquired()
    assert await child.wait() == 0
