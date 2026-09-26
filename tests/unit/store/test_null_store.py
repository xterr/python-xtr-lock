from __future__ import annotations

import pytest

from xtr_lock import (
    BlockingSharedLockStoreInterface,
    BlockingStoreInterface,
    Key,
    Lock,
    NullStore,
)

pytestmark = pytest.mark.anyio


async def test_exists_always_returns_false() -> None:
    store = NullStore()
    key = Key("r")

    await store.save(key)

    assert not await store.exists(key)


async def test_every_save_succeeds_for_every_key() -> None:
    store = NullStore()
    first, second = Key("r"), Key("r")

    await store.save(first)
    await store.save(second)
    await store.save_read(first)
    await store.wait_and_save_read(second)
    await store.put_off_expiration(first, 10)
    await store.delete(first)

    assert not await store.exists(second)


async def test_a_lock_on_it_is_acquired_but_never_reported_held() -> None:
    lock = Lock(Key("r"), NullStore())

    assert await lock.acquire(blocking=True)
    assert await lock.acquire_read(blocking=True)
    assert not await lock.is_acquired()
    await lock.release()


def test_it_can_wait_to_share_but_has_no_writer_wait() -> None:
    assert isinstance(NullStore(), BlockingSharedLockStoreInterface)
    assert not isinstance(NullStore(), BlockingStoreInterface)
