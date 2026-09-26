from __future__ import annotations

from xtr_lock import InMemoryStore, Key, Lock, LockInterface, NoLock


def test_both_locks_satisfy_it() -> None:
    assert isinstance(Lock(Key("r"), InMemoryStore()), LockInterface)
    assert isinstance(NoLock(), LockInterface)


def test_a_store_does_not() -> None:
    assert not isinstance(InMemoryStore(), LockInterface)
