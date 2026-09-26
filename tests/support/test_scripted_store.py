"""The scripted store fakes keep their own contract."""

from __future__ import annotations

import pytest

from tests.support.scripted_store import (
    ScriptedBlockingSharedStore,
    ScriptedBlockingStore,
    ScriptedSharedStore,
    ScriptedStore,
)
from xtr_lock import (
    BlockingSharedLockStoreInterface,
    BlockingStoreInterface,
    Key,
    LockConflictedError,
    PersistingStoreInterface,
    SharedLockStoreInterface,
)

pytestmark = pytest.mark.anyio


async def test_an_unscripted_store_succeeds_and_holds_nothing() -> None:
    store = ScriptedStore()
    key = Key("r")

    await store.save(key)

    assert await store.exists(key) is False
    assert store.calls == [("save", "r"), ("exists", "r")]


async def test_scripted_outcomes_play_in_order_then_fall_back() -> None:
    store = ScriptedStore()
    conflict = LockConflictedError("r")
    store.script("save", conflict, None)
    store.script("exists", True)
    key = Key("r")

    with pytest.raises(LockConflictedError) as raised:
        await store.save(key)
    await store.save(key)
    await store.save(key)

    assert raised.value is conflict
    assert await store.exists(key) is True
    assert await store.exists(key) is False


async def test_a_callable_outcome_runs_against_the_key() -> None:
    store = ScriptedStore()
    store.script("put_off_expiration", lambda key: key.reduce_lifetime(-1))
    key = Key("r")

    await store.put_off_expiration(key, 10)

    assert key.is_expired()
    assert store.called("put_off_expiration") == [("r", 10)]


def test_each_fake_satisfies_exactly_its_interfaces() -> None:
    plain, blocking = ScriptedStore(), ScriptedBlockingStore()
    shared, blocking_shared = ScriptedSharedStore(), ScriptedBlockingSharedStore()

    assert all(
        isinstance(store, PersistingStoreInterface)
        for store in (plain, blocking, shared, blocking_shared)
    )
    assert [isinstance(store, BlockingStoreInterface) for store in (plain, shared)] == [False] * 2
    assert isinstance(blocking, BlockingStoreInterface)
    assert not isinstance(blocking, SharedLockStoreInterface)
    assert isinstance(shared, SharedLockStoreInterface)
    assert not isinstance(shared, BlockingSharedLockStoreInterface)
    assert isinstance(blocking_shared, BlockingSharedLockStoreInterface)
    assert not isinstance(blocking_shared, BlockingStoreInterface)
