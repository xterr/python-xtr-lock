from __future__ import annotations

from xtr_lock import LockConflictedError


def test_it_carries_the_resource() -> None:
    error = LockConflictedError("invoice")

    assert error.resource == "invoice"
    assert str(error) == "lock 'invoice' is held by someone else"
