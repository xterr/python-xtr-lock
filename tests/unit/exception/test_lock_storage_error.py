from __future__ import annotations

from xtr_lock import LockStorageError


def test_it_carries_what_the_storage_said() -> None:
    error = LockStorageError("ERR unknown command")

    assert error.reason == "ERR unknown command"
    assert str(error) == "ERR unknown command"
