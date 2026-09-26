from __future__ import annotations

import pytest

from xtr_lock import NoLock, SharedLockInterface

pytestmark = pytest.mark.anyio


async def test_it_says_yes_to_everything() -> None:
    lock = NoLock()

    assert await lock.acquire()
    assert await lock.acquire(blocking=True)
    assert await lock.acquire_read()
    assert await lock.is_acquired()
    await lock.refresh()
    await lock.refresh(10)
    await lock.release()

    assert await lock.is_acquired()
    assert not lock.is_expired()
    assert lock.get_remaining_lifetime() is None


async def test_it_works_as_a_context() -> None:
    lock = NoLock()

    async with lock as entered:
        assert entered is lock


def test_it_is_a_shared_lock() -> None:
    assert isinstance(NoLock(), SharedLockInterface)
