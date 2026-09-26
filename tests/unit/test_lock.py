from __future__ import annotations

import asyncio
import pickle
from typing import TYPE_CHECKING, final

import pytest
from typing_extensions import override
from xtr_clock import MockClock

from tests.support.recording_logger import RecordingLogger
from tests.support.scripted_store import (
    ScriptedBlockingSharedStore,
    ScriptedBlockingStore,
    ScriptedSharedStore,
    ScriptedStore,
)
from xtr_lock import (
    ExpiringStoreMixin,
    FlockStore,
    InMemoryStore,
    InvalidArgumentError,
    Key,
    Lock,
    LockAcquiringError,
    LockConflictedError,
    LockExpiredError,
    LockReleasingError,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.anyio


def _expire(key: Key) -> None:
    key.reduce_lifetime(-1)


async def test_acquire_no_blocking() -> None:
    store = ScriptedBlockingStore()
    lock = Lock(Key("r"), store)

    assert await lock.acquire(blocking=False)

    assert [call[0] for call in store.calls] == ["save"]


async def test_acquire_no_blocking_with_persisting_store_interface() -> None:
    store = ScriptedStore()

    assert await Lock(Key("r"), store).acquire(blocking=False)

    assert store.called("save") == [("r",)]


async def test_acquire_blocking_with_persisting_store_interface() -> None:
    store = ScriptedStore()

    assert await Lock(Key("r"), store).acquire(blocking=True)

    assert store.called("save") == [("r",)]


async def test_acquire_blocking_retry_with_persisting_store_interface() -> None:
    store = ScriptedStore()
    store.script("save", LockConflictedError("r"), LockConflictedError("r"), None)
    clock = MockClock("2026-01-01 00:00:00")
    start = clock.now()

    assert await Lock(Key("r"), store, clock=clock).acquire(blocking=True)

    assert len(store.called("save")) == 3
    waited = (clock.now() - start).total_seconds()
    assert 0.18 <= waited <= 0.22


async def test_acquire_returns_false() -> None:
    store = ScriptedBlockingStore()
    store.script("save", LockConflictedError("r"))

    assert not await Lock(Key("r"), store).acquire(blocking=False)


async def test_acquire_returns_false_store_interface() -> None:
    store = ScriptedStore()
    store.script("save", LockConflictedError("r"))

    assert not await Lock(Key("r"), store).acquire(blocking=False)


async def test_acquire_blocking_with_blocking_store_interface() -> None:
    store = ScriptedBlockingStore()

    assert await Lock(Key("r"), store).acquire(blocking=True)

    assert store.called("wait_and_save") == [("r",)]
    assert store.called("save") == []


async def test_a_blocking_store_giving_up_raises_the_same_conflict() -> None:
    store = ScriptedBlockingStore()
    conflict = LockConflictedError("r")
    store.script("wait_and_save", conflict)

    with pytest.raises(LockConflictedError) as raised:
        _ = await Lock(Key("r"), store).acquire(blocking=True)

    assert raised.value is conflict


async def test_acquire_sets_ttl() -> None:
    store = ScriptedBlockingStore()

    assert await Lock(Key("r"), store, 10).acquire()

    assert store.called("put_off_expiration") == [("r", 10)]


async def test_a_zero_ttl_sets_no_lifetime() -> None:
    store = ScriptedStore()

    assert await Lock(Key("r"), store, 0).acquire()

    assert store.called("put_off_expiration") == []


async def test_refresh() -> None:
    store = ScriptedStore()

    await Lock(Key("r"), store, 10).refresh()

    assert store.called("put_off_expiration") == [("r", 10)]


async def test_refresh_custom() -> None:
    store = ScriptedStore()

    await Lock(Key("r"), store, 10).refresh(20)

    assert store.called("put_off_expiration") == [("r", 20)]


@pytest.mark.parametrize(("lock_ttl", "ttl"), [(None, None), (10, 0), (None, 0), (0, None)])
async def test_refresh_needs_a_duration(lock_ttl: float | None, ttl: float | None) -> None:
    store = ScriptedStore()

    with pytest.raises(InvalidArgumentError, match=r"You have to define an expiration duration\."):
        await Lock(Key("r"), store, lock_ttl).refresh(ttl)

    assert store.calls == []


async def test_refresh_lets_a_conflict_through_and_forgets_the_lock() -> None:
    store = ScriptedStore()
    conflict = LockConflictedError("r")
    store.script("put_off_expiration", conflict)
    store.script("exists", True)
    lock = Lock(Key("r"), store, 10)
    logger = RecordingLogger()
    lock.set_logger(logger)

    with pytest.raises(LockConflictedError) as raised:
        await lock.refresh()

    assert raised.value is conflict
    # Leaving a context on a lock it no longer holds asks the store nothing.
    await lock.__aexit__(None, None, None)
    assert store.called("exists") == []
    assert store.called("delete") == []
    assert logger.messages("notice") == [
        'Failed to define an expiration for the "{resource}" lock, someone else acquired the lock.',
    ]


async def test_refresh_wraps_any_other_failure() -> None:
    store = ScriptedStore()
    failure = RuntimeError("down")
    store.script("put_off_expiration", failure)

    with pytest.raises(LockAcquiringError, match="failed to define an expiration") as raised:
        await Lock(Key("r"), store, 10).refresh()

    assert raised.value.__cause__ is failure


async def test_refresh_releases_a_lock_that_expired_on_the_way() -> None:
    store = ScriptedStore()
    store.script("put_off_expiration", _expire)

    with pytest.raises(LockAcquiringError) as raised:
        await Lock(Key("r"), store, 10).refresh()

    assert isinstance(raised.value.__cause__, LockExpiredError)
    assert store.called("delete") == [("r",)]


async def test_acquire_releases_a_lock_that_expired_while_being_stored() -> None:
    store = ScriptedStore()
    store.script("save", _expire)

    with pytest.raises(LockAcquiringError) as raised:
        _ = await Lock(Key("r"), store).acquire()

    assert isinstance(raised.value.__cause__, LockExpiredError)
    assert store.called("delete") == [("r",)]


async def test_an_expired_lock_is_reported_even_when_releasing_it_fails() -> None:
    store = ScriptedStore()
    store.script("save", _expire)
    store.script("delete", RuntimeError("down"))

    with pytest.raises(LockAcquiringError) as raised:
        _ = await Lock(Key("r"), store).acquire()

    assert isinstance(raised.value.__cause__, LockExpiredError)


async def test_acquire_wraps_any_other_failure_and_logs_it() -> None:
    store = ScriptedStore()
    failure = OSError("disk")
    store.script("save", failure)
    lock = Lock(Key("r"), store)
    logger = RecordingLogger()
    lock.set_logger(logger)

    with pytest.raises(LockAcquiringError, match="'r': failed to acquire the lock") as raised:
        _ = await lock.acquire()

    assert raised.value.__cause__ is failure
    assert logger.records[-1] == (
        "notice",
        'Failed to acquire the "{resource}" lock.',
        {"resource": "r", "exception": failure},
    )


async def test_acquire_logs_success_and_contention() -> None:
    store = ScriptedStore()
    store.script("save", None, LockConflictedError("r"))
    lock = Lock(Key("r"), store)
    logger = RecordingLogger()
    lock.set_logger(logger)

    assert await lock.acquire()
    assert not await lock.acquire()

    assert logger.messages("debug") == ['Successfully acquired the "{resource}" lock.']
    assert logger.messages("info") == [
        'Failed to acquire the "{resource}" lock. Someone else already acquired the lock.',
    ]


async def test_is_acquired() -> None:
    store = ScriptedStore()
    store.script("exists", True)

    assert await Lock(Key("r"), store, 10).is_acquired()


async def test_release() -> None:
    store = ScriptedStore()
    store.script("exists", False)

    await Lock(Key("r"), store, 10).release()

    assert store.called("delete") == [("r",)]


async def test_release_throws_exception_when_deletion_fail() -> None:
    store = ScriptedStore()
    failure = RuntimeError("Boom")
    store.script("delete", failure)

    with pytest.raises(LockReleasingError, match="failed to release the lock") as raised:
        await Lock(Key("r"), store, 10).release()

    assert raised.value.__cause__ is failure


async def test_release_lets_a_releasing_error_through_unwrapped() -> None:
    store = ScriptedStore()
    failure = LockReleasingError("r", "the store says no")
    store.script("delete", failure)

    with pytest.raises(LockReleasingError) as raised:
        await Lock(Key("r"), store).release()

    assert raised.value is failure


async def test_release_throws_exception_if_not_well_deleted() -> None:
    store = ScriptedStore()
    store.script("exists", True)

    with pytest.raises(LockReleasingError, match="the resource is still locked"):
        await Lock(Key("r"), store, 10).release()


async def test_release_throws_and_log() -> None:
    store = ScriptedStore()
    store.script("exists", True)
    lock = Lock(Key("r"), store, 10)
    logger = RecordingLogger()
    lock.set_logger(logger)

    with pytest.raises(LockReleasingError):
        await lock.release()

    assert logger.records == [
        ("notice", 'Failed to release the "{resource}" lock.', {"resource": "r"}),
    ]


async def test_success_release_log() -> None:
    lock = Lock(Key("r"), ScriptedStore())
    logger = RecordingLogger()
    lock.set_logger(logger)

    await lock.release()

    assert logger.records == [
        ("debug", 'Successfully released the "{resource}" lock.', {"resource": "r"}),
    ]


@pytest.mark.parametrize(
    ("ttls", "expected"),
    [
        ([-0.1], True),
        ([0.1, -0.1], True),
        ([-0.1, 0.1], True),
        ([], False),
        ([0.1], False),
        ([-0.1, None], False),
    ],
)
async def test_expiration(ttls: list[float | None], expected: bool) -> None:
    key = Key("r")
    lock = Lock(key, ScriptedStore(), 10)

    for ttl in ttls:
        if ttl is None:
            key.reset_lifetime()
        else:
            key.reduce_lifetime(ttl)

    assert lock.is_expired() is expected


async def test_remaining_lifetime_is_the_keys() -> None:
    clock = MockClock("2026-01-01 00:00:00")
    key = Key("r", clock=clock)
    lock = Lock(key, ScriptedStore(), 10)
    assert lock.get_remaining_lifetime() is None

    key.reduce_lifetime(10)
    clock.sleep(3)

    assert lock.get_remaining_lifetime() == 7


async def test_acquire_read_no_blocking_with_shared_lock_store_interface() -> None:
    store = ScriptedSharedStore()

    assert await Lock(Key("r"), store).acquire_read(blocking=False)

    assert store.called("save_read") == [("r",)]


async def test_acquire_read_falls_back_to_a_write_lock_and_says_so() -> None:
    store = ScriptedBlockingStore()
    lock = Lock(Key("r"), store)
    logger = RecordingLogger()
    lock.set_logger(logger)

    assert await lock.acquire_read(blocking=True)

    assert store.called("wait_and_save") == [("r",)]
    assert logger.messages("debug")[0] == (
        "Store does not support read locks, falling back to a write lock."
    )


async def test_acquire_read_returns_false_on_conflict() -> None:
    store = ScriptedSharedStore()
    store.script("save_read", LockConflictedError("r"))

    assert not await Lock(Key("r"), store).acquire_read()


async def test_acquire_read_blocking_raises_a_conflict_the_store_gives_up_with() -> None:
    store = ScriptedBlockingSharedStore()
    store.script("wait_and_save_read", LockConflictedError("r"))

    with pytest.raises(LockConflictedError):
        _ = await Lock(Key("r"), store).acquire_read(blocking=True)


async def test_acquire_read_wraps_any_other_failure() -> None:
    store = ScriptedSharedStore()
    store.script("save_read", RuntimeError("down"))

    with pytest.raises(LockAcquiringError):
        _ = await Lock(Key("r"), store).acquire_read()


async def test_acquire_read_sets_ttl_and_refuses_an_expired_lock() -> None:
    store = ScriptedSharedStore()
    store.script("put_off_expiration", _expire)

    with pytest.raises(LockAcquiringError) as raised:
        _ = await Lock(Key("r"), store, 10).acquire_read()

    assert store.called("put_off_expiration") == [("r", 10)]
    # The expiry surfaces through refresh, which wraps it too.
    refresh_failure = raised.value.__cause__
    assert isinstance(refresh_failure, LockAcquiringError)
    assert isinstance(refresh_failure.__cause__, LockExpiredError)


@final
class _ExpiringStore(ExpiringStoreMixin):
    """Grants every key a thirty-second hold, and honours whatever lifetime is set after."""

    initial_ttl = 30

    def __init__(self) -> None:
        self.keys: dict[int, Key] = {}

    async def save(self, key: Key) -> None:
        key.reduce_lifetime(self.initial_ttl)
        self.keys[id(key)] = key
        await self._check_not_expired(key)

    async def save_read(self, key: Key) -> None:
        await self.save(key)

    @override
    async def delete(self, key: Key) -> None:
        _ = self.keys.pop(id(key), None)

    async def exists(self, key: Key) -> bool:
        return id(key) in self.keys

    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        key.reduce_lifetime(ttl)
        await self._check_not_expired(key)


@pytest.mark.parametrize("read", [False, True])
async def test_acquire_twice_with_expiration(read: bool) -> None:
    clock = MockClock("2026-01-01 00:00:00")
    lock = Lock(Key("r", clock=clock), _ExpiringStore(), 1, clock=clock)
    acquire = lock.acquire_read if read else lock.acquire

    assert await acquire()
    await lock.release()
    clock.sleep(2)
    assert await acquire()
    await lock.release()


async def test_acquire_read_blocking_with_blocking_shared_lock_store_interface() -> None:
    store = ScriptedBlockingSharedStore()

    assert await Lock(Key("r"), store).acquire_read(blocking=True)

    assert store.called("wait_and_save_read") == [("r",)]


async def test_acquire_read_blocking_with_shared_lock_store_interface() -> None:
    store = ScriptedSharedStore()
    store.script("save_read", LockConflictedError("r"), LockConflictedError("r"), None)

    assert await Lock(Key("r"), store, clock=MockClock()).acquire_read(blocking=True)

    assert len(store.called("save_read")) == 3


async def test_acquire_read_blocking_with_persisting_store_interface() -> None:
    store = ScriptedStore()

    assert await Lock(Key("r"), store).acquire_read(blocking=True)

    assert store.called("save") == [("r",)]


async def test_a_retrying_wait_yields_to_other_tasks() -> None:
    store = InMemoryStore()
    holder = Lock(Key("r"), store)
    assert await holder.acquire()
    waiter = Lock(Key("r"), store)

    waiting = asyncio.create_task(waiter.acquire(blocking=True))
    await asyncio.sleep(0.01)
    assert not waiting.done()

    await holder.release()
    assert await asyncio.wait_for(waiting, timeout=2)
    await waiter.release()


async def test_context_waits_for_the_lock_and_releases_it() -> None:
    store = InMemoryStore()
    lock = Lock(Key("r"), store)

    async with lock as entered:
        assert entered is lock
        assert await lock.is_acquired()
        assert not await Lock(Key("r"), store).acquire()

    assert not await lock.is_acquired()
    assert await Lock(Key("r"), store).acquire()


async def test_context_releases_when_the_block_raises() -> None:
    store = InMemoryStore()
    lock = Lock(Key("r"), store)

    with pytest.raises(ValueError, match="boom"):
        async with lock:
            raise ValueError("boom")

    assert not await lock.is_acquired()


async def test_context_leaves_alone_a_lock_it_no_longer_holds() -> None:
    store = ScriptedStore()
    store.script("exists", False)

    async with Lock(Key("r"), store):
        pass

    assert store.called("delete") == []


async def test_it_cannot_be_pickled() -> None:
    with pytest.raises(TypeError, match="cannot pickle Lock"):
        _ = pickle.dumps(Lock(Key("r"), InMemoryStore()))


def test_repr_names_the_resource_and_store() -> None:
    assert repr(Lock(Key("r"), InMemoryStore())) == "Lock('r', InMemoryStore())"


@final
class _SlowStore(ScriptedStore):
    """Saves only once ``proceed`` is set, so a test can act while a save is in flight."""

    def __init__(self) -> None:
        super().__init__()
        self.proceed = asyncio.Event()
        self.saving = asyncio.Event()

    @override
    async def save(self, key: Key) -> None:
        self.saving.set()
        _ = await self.proceed.wait()
        await super().save(key)


async def test_two_tasks_waiting_on_one_lock_leave_nothing_behind(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    other = Lock(Key("r"), store)
    assert await other.acquire()
    shared = Lock(Key("r"), store)

    first = asyncio.create_task(shared.acquire(blocking=True))
    second = asyncio.create_task(shared.acquire(blocking=True))
    await asyncio.sleep(0.05)
    await other.release()

    assert await asyncio.wait_for(first, timeout=5)
    assert await asyncio.wait_for(second, timeout=5)
    await shared.release()
    assert not await shared.is_acquired()
    assert await Lock(Key("r"), store).acquire()


async def test_operations_on_one_holder_take_turns() -> None:
    store = _SlowStore()
    lock = Lock(Key("r"), store)

    acquiring = asyncio.create_task(lock.acquire())
    _ = await store.saving.wait()
    releasing = asyncio.create_task(lock.release())
    await asyncio.sleep(0.01)

    assert store.called("delete") == []
    store.proceed.set()
    assert await acquiring
    await releasing
    assert [call[0] for call in store.calls] == ["save", "delete", "exists"]


async def test_locks_made_from_one_key_are_one_holder() -> None:
    store = InMemoryStore()
    key = Key("r")
    first, second = Lock(key, store), Lock(key, store)

    assert await first.acquire()
    assert await second.acquire()
    await second.release()

    assert not await first.is_acquired()
    assert await Lock(Key("r"), store).acquire()


async def test_a_timed_out_wait_holds_nothing_and_leaves_the_holder_alone() -> None:
    store = InMemoryStore()
    holder = Lock(Key("r"), store)
    assert await holder.acquire()
    waiter = Lock(Key("r"), store)

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.05):
            _ = await waiter.acquire(blocking=True)

    assert not await waiter.is_acquired()
    assert await holder.is_acquired()


async def test_a_cancelled_save_is_taken_back() -> None:
    store = _SlowStore()
    lock = Lock(Key("r"), store)

    acquiring = asyncio.create_task(lock.acquire())
    _ = await store.saving.wait()
    _ = acquiring.cancel()
    with pytest.raises(asyncio.CancelledError):
        await acquiring

    assert store.called("delete") == [("r",)]


async def test_a_cancelled_reacquire_keeps_what_the_holder_already_held() -> None:
    store = _SlowStore()
    store.proceed.set()
    lock = Lock(Key("r"), store)
    assert await lock.acquire()
    store.proceed.clear()

    reacquiring = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0.01)
    _ = reacquiring.cancel()
    with pytest.raises(asyncio.CancelledError):
        await reacquiring

    assert store.called("delete") == []


@final
class _StallingStore(ScriptedStore):
    """Saves at once, then never finishes setting a lifetime."""

    @override
    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        await super().put_off_expiration(key, ttl)
        _ = await asyncio.Event().wait()


async def test_a_cancelled_refresh_after_saving_is_taken_back() -> None:
    store = _StallingStore()
    lock = Lock(Key("r"), store, 10)
    acquiring = asyncio.create_task(lock.acquire())
    await asyncio.sleep(0.01)
    _ = acquiring.cancel()
    with pytest.raises(asyncio.CancelledError):
        await acquiring

    assert store.called("delete") == [("r",)]
