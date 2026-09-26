from __future__ import annotations

from xtr_lock import InMemoryStore, Key, Lock, LockFactory, NoLock, SharedLockInterface


def test_every_lock_this_library_makes_can_share() -> None:
    assert isinstance(Lock(Key("r"), InMemoryStore()), SharedLockInterface)
    assert isinstance(NoLock(), SharedLockInterface)
    assert isinstance(LockFactory(InMemoryStore()).create_lock("r"), SharedLockInterface)
