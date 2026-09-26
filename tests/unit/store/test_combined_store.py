from __future__ import annotations

from typing import final

import pytest
from typing_extensions import override
from xtr_clock import Clock, MockClock

from tests.support.fake_redis import FakeRedis
from tests.support.recording_logger import RecordingLogger
from tests.support.scripted_store import ScriptedBlockingStore, ScriptedSharedStore, ScriptedStore
from tests.support.store_conformance import AbstractStoreTests, SharedLockStoreTests
from xtr_lock import (
    CombinedStore,
    ConsensusStrategy,
    InMemoryStore,
    InvalidArgumentError,
    Key,
    LockConflictedError,
    LockExpiredError,
    RedisStore,
    StrategyInterface,
    UnanimousStrategy,
)

pytestmark = pytest.mark.anyio


class TestCombinedStoreOverMemory(AbstractStoreTests, SharedLockStoreTests):
    @pytest.fixture
    def store(self) -> CombinedStore:
        return CombinedStore(
            [InMemoryStore(), InMemoryStore(), InMemoryStore()], ConsensusStrategy()
        )


@final
class FixedStrategy(StrategyInterface):
    """Answers what it is told, and records what it was asked."""

    def __init__(self, *, met: bool, can_be_met: bool) -> None:
        self.met = met
        self.meetable = can_be_met
        self.is_met_calls: list[tuple[int, int]] = []
        self.can_be_met_calls: list[tuple[int, int]] = []

    @override
    def is_met(self, number_of_success: int, number_of_items: int) -> bool:
        self.is_met_calls.append((number_of_success, number_of_items))
        return self.met

    @override
    def can_be_met(self, number_of_failure: int, number_of_items: int) -> bool:
        self.can_be_met_calls.append((number_of_failure, number_of_items))
        return self.meetable


def _pair() -> tuple[ScriptedBlockingStore, ScriptedBlockingStore]:
    return ScriptedBlockingStore(), ScriptedBlockingStore()


def test_every_member_must_be_a_store() -> None:
    with pytest.raises(InvalidArgumentError, match='Got "object"'):
        # The refusal is the point.
        _ = CombinedStore([InMemoryStore(), object()], ConsensusStrategy())  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]


async def test_save_throws_exception_on_failure() -> None:
    store1, store2 = _pair()
    store1.script("save", LockConflictedError("r"))
    store2.script("save", LockConflictedError("r"))
    store = CombinedStore([store1, store2], FixedStrategy(met=False, can_be_met=True))

    with pytest.raises(LockConflictedError):
        await store.save(Key("r"))

    assert len(store1.called("save")) == 1
    assert len(store2.called("save")) == 1


async def test_save_cleanup_on_failure() -> None:
    store1, store2 = _pair()
    store1.script("save", LockConflictedError("r"))
    store2.script("save", LockConflictedError("r"))
    store = CombinedStore([store1, store2], FixedStrategy(met=False, can_be_met=True))

    with pytest.raises(LockConflictedError):
        await store.save(Key("r"))

    assert len(store1.called("delete")) == 1
    assert len(store2.called("delete")) == 1


async def test_save_abort_when_strategy_cant_be_met() -> None:
    store1, store2 = _pair()
    store1.script("save", LockConflictedError("r"))
    strategy = FixedStrategy(met=False, can_be_met=False)
    store = CombinedStore([store1, store2], strategy)

    with pytest.raises(LockConflictedError):
        await store.save(Key("r"))

    assert store2.called("save") == []
    assert strategy.can_be_met_calls == [(1, 2)]


async def test_save_counts_any_failure_against_the_quorum_and_logs_it() -> None:
    store1, store2, store3 = ScriptedStore(), ScriptedStore(), ScriptedStore()
    store1.script("save", RuntimeError("down"))
    store = CombinedStore([store1, store2, store3], ConsensusStrategy())
    logger = RecordingLogger()
    store.set_logger(logger)

    await store.save(Key("r"))

    assert logger.messages("debug") == ['One store failed to save the "{resource}" lock.']
    assert store1.called("delete") == []


async def test_put_off_expiration_throws_exception_on_failure() -> None:
    store1, store2 = _pair()
    store1.script("put_off_expiration", LockConflictedError("r"))
    store2.script("put_off_expiration", LockConflictedError("r"))
    store = CombinedStore([store1, store2], FixedStrategy(met=False, can_be_met=True))

    with pytest.raises(LockConflictedError):
        await store.put_off_expiration(Key("r"), 5)


async def test_put_off_expiration_cleanup_on_failure() -> None:
    store1, store2 = _pair()
    store1.script("put_off_expiration", LockConflictedError("r"))
    store2.script("put_off_expiration", LockConflictedError("r"))
    store = CombinedStore([store1, store2], FixedStrategy(met=False, can_be_met=True))

    with pytest.raises(LockConflictedError):
        await store.put_off_expiration(Key("r"), 5)

    assert len(store1.called("delete")) == 1
    assert len(store2.called("delete")) == 1


async def test_put_off_expiration_abort_when_strategy_cant_be_met() -> None:
    store1, store2 = _pair()
    store1.script("put_off_expiration", LockConflictedError("r"))
    store = CombinedStore([store1, store2], FixedStrategy(met=False, can_be_met=False))

    with pytest.raises(LockConflictedError):
        await store.put_off_expiration(Key("r"), 5)

    assert store2.called("put_off_expiration") == []


async def test_put_off_expiration_ignore_non_expiring_storage() -> None:
    strategy = FixedStrategy(met=True, can_be_met=True)
    store = CombinedStore([ScriptedStore(), ScriptedStore()], strategy)

    await store.put_off_expiration(Key("r"), 7)

    assert strategy.is_met_calls == [(2, 2)]


async def test_put_off_expiration_gives_each_store_what_is_left_of_one_deadline() -> None:
    clock = MockClock("2026-01-01 00:00:00")
    first, second = ScriptedStore(), ScriptedStore()
    first.script("put_off_expiration", lambda _: clock.sleep(2))
    store = CombinedStore([first, second], UnanimousStrategy(), clock=clock)

    with Clock.using(clock):
        await store.put_off_expiration(Key("r"), 10)

    assert first.called("put_off_expiration") == [("r", 10)]
    assert second.called("put_off_expiration") == [("r", 8)]


async def test_put_off_expiration_expires_the_key_when_the_deadline_passes_midway() -> None:
    clock = MockClock("2026-01-01 00:00:00")
    first, second = ScriptedStore(), ScriptedStore()
    first.script("put_off_expiration", lambda _: clock.sleep(11))
    store = CombinedStore([first, second], UnanimousStrategy(), clock=clock)
    key = Key("r", clock=clock)

    with pytest.raises(LockExpiredError):
        await store.put_off_expiration(key, 10)

    assert second.called("put_off_expiration") == []
    assert key.is_expired()
    assert len(first.called("delete")) == 1


async def test_a_key_expired_before_saving_is_refused_and_taken_back() -> None:
    store1 = ScriptedStore()
    store = CombinedStore([store1], UnanimousStrategy())
    key = Key("r")
    key.reduce_lifetime(0)

    with pytest.raises(LockExpiredError):
        await store.save(key)

    assert len(store1.called("delete")) == 1


async def test_exists_dont_ask_to_every_body() -> None:
    store1, store2 = _pair()
    strategy = FixedStrategy(met=True, can_be_met=True)

    assert await CombinedStore([store1, store2], strategy).exists(Key("r"))

    assert len(store1.called("exists")) == 1
    assert store2.called("exists") == []
    assert len(strategy.is_met_calls) == 1


async def test_exists_abort_when_strategy_cant_be_met() -> None:
    store1, store2 = _pair()
    strategy = FixedStrategy(met=False, can_be_met=False)

    assert not await CombinedStore([store1, store2], strategy).exists(Key("r"))

    assert store2.called("exists") == []
    assert len(strategy.can_be_met_calls) == 1


async def test_delete_dont_stop_on_failure() -> None:
    store1, store2 = _pair()
    store1.script("delete", RuntimeError("down"))
    store = CombinedStore([store1, store2], ConsensusStrategy())
    logger = RecordingLogger()
    store.set_logger(logger)

    await store.delete(Key("r"))

    assert len(store2.called("delete")) == 1
    assert logger.messages("notice") == ['One store failed to delete the "{resource}" lock.']


async def test_exists_dont_stop_on_failure() -> None:
    store1, store2 = _pair()
    store1.script("exists", RuntimeError("down"))

    exists = await CombinedStore(
        [store1, store2], FixedStrategy(met=False, can_be_met=True)
    ).exists(Key("r"))

    assert not exists
    assert len(store2.called("exists")) == 1


async def test_save_read_with_compatible_store() -> None:
    shared = ScriptedSharedStore()

    await CombinedStore([shared], UnanimousStrategy()).save_read(Key("r"))

    assert shared.called("save_read") == [("r",)]
    assert shared.called("save") == []


async def test_save_read_falls_back_to_save_on_a_store_that_cannot_share() -> None:
    shared, plain = ScriptedSharedStore(), ScriptedStore()

    await CombinedStore([shared, plain], UnanimousStrategy()).save_read(Key("r"))

    assert shared.called("save_read") == [("r",)]
    assert plain.called("save") == [("r",)]


async def test_save_read_takes_back_a_lock_short_of_quorum() -> None:
    shared, plain = ScriptedSharedStore(), ScriptedStore()
    plain.script("save", LockConflictedError("r"))

    with pytest.raises(LockConflictedError):
        await CombinedStore([shared, plain], UnanimousStrategy()).save_read(Key("r"))

    assert len(shared.called("delete")) == 1


def _granted(script: str, arguments: tuple[object, ...]) -> object:
    del script, arguments
    return 1


async def test_aclose_closes_every_store_that_can_be_closed() -> None:
    owned, lent = FakeRedis(_granted), FakeRedis(_granted)
    owning = RedisStore(owned.as_client())
    owning._owns_connection = True
    store = CombinedStore(
        [owning, RedisStore(lent.as_client()), InMemoryStore()],
        ConsensusStrategy(),
    )

    await store.aclose()

    assert owned.closed
    assert not lent.closed


@final
class _FailingToClose(ScriptedStore):
    def __init__(self, error: Exception | None = None) -> None:
        super().__init__()
        self.error = error
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True
        if self.error is not None:
            raise self.error


async def test_aclose_asks_every_store_and_raises_the_failures_together() -> None:
    first, second, third = (
        _FailingToClose(RuntimeError("a")),
        _FailingToClose(),
        _FailingToClose(OSError("c")),
    )

    with pytest.raises(ExceptionGroup) as raised:
        await CombinedStore([first, second, third], ConsensusStrategy()).aclose()

    assert [first.closed, second.closed, third.closed] == [True, True, True]
    assert [str(error) for error in raised.value.exceptions] == ["a", "c"]


async def test_the_deadline_is_counted_monotonically_by_default() -> None:
    first, second = ScriptedStore(), ScriptedStore()
    frozen = MockClock("2026-01-01 00:00:00")
    first.script("put_off_expiration", lambda _: frozen.sleep(3600))
    store = CombinedStore([first, second], UnanimousStrategy())

    with Clock.using(frozen):
        await store.put_off_expiration(Key("r"), 10)

    ((_, ttl),) = second.called("put_off_expiration")
    assert isinstance(ttl, float)
    assert 9 < ttl <= 10
