from __future__ import annotations

import pickle
from typing import cast

import pytest

from tests.support.store_conformance import AbstractStoreTests, SharedLockStoreTests
from xtr_lock import InMemoryStore, Key

pytestmark = pytest.mark.anyio


class TestInMemoryStore(AbstractStoreTests, SharedLockStoreTests):
    @pytest.fixture
    def store(self) -> InMemoryStore:
        return InMemoryStore()


async def test_a_lifetime_never_expires_the_lock() -> None:
    store = InMemoryStore()
    key = Key("r")
    await store.save(key)

    await store.put_off_expiration(key, 0.000_001)

    assert await store.exists(key)


async def test_a_key_that_saved_can_still_be_pickled_and_act_as_the_same_holder() -> None:
    store = InMemoryStore()
    key = Key("r")
    await store.save(key)

    copy = cast("Key", pickle.loads(pickle.dumps(key)))  # noqa: S301 — the pickle was made two lines up.

    assert await store.exists(copy)
    await store.delete(copy)
    assert not await store.exists(key)


async def test_two_stores_do_not_share_locks() -> None:
    first, second = InMemoryStore(), InMemoryStore()

    await first.save(Key("r"))
    await second.save(Key("r"))
