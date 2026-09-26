from __future__ import annotations

import pytest
from xtr_clock import MockClock

from tests.support.recording_logger import RecordingLogger
from tests.support.scripted_store import ScriptedStore
from xtr_lock import DEFAULT_TTL, InMemoryStore, Key, Lock, LockFactory

pytestmark = pytest.mark.anyio


async def test_create_lock() -> None:
    store = ScriptedStore()
    factory = LockFactory(store)
    logger = RecordingLogger()
    factory.set_logger(logger)

    lock = factory.create_lock("foo")
    assert await lock.acquire()

    assert isinstance(lock, Lock)
    assert store.called("save") == [("foo",)]
    assert store.called("put_off_expiration") == [("foo", DEFAULT_TTL)]
    assert logger.messages("debug")[0] == 'Successfully acquired the "{resource}" lock.'


async def test_create_lock_with_another_ttl_or_none() -> None:
    store = ScriptedStore()
    factory = LockFactory(store)

    _ = await factory.create_lock("a", 10).acquire()
    _ = await factory.create_lock("b", None).acquire()

    assert store.called("put_off_expiration") == [("a", 10)]


async def test_each_created_lock_is_a_new_holder() -> None:
    factory = LockFactory(InMemoryStore())

    assert await factory.create_lock("foo").acquire()
    assert not await factory.create_lock("foo").acquire()


async def test_create_lock_from_key() -> None:
    store = InMemoryStore()
    factory = LockFactory(store)
    key = Key("foo")

    assert await factory.create_lock_from_key(key).acquire()

    assert await factory.create_lock_from_key(key).is_acquired()
    assert await store.exists(key)


async def test_locks_measure_time_on_the_factorys_clock() -> None:
    clock = MockClock("2026-01-01 00:00:00")
    store = ScriptedStore()
    store.script("put_off_expiration", lambda key: key.reduce_lifetime(10))
    lock = LockFactory(store, clock=clock).create_lock("foo", 10)
    await lock.refresh()

    clock.sleep(4)
    assert lock.get_remaining_lifetime() == 6

    clock.sleep(6)
    assert lock.is_expired()


async def test_the_default_ttl_is_five_minutes() -> None:
    assert DEFAULT_TTL == 300.0
