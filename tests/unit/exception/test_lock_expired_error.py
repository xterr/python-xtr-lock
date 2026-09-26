from __future__ import annotations

from xtr_lock import LockExpiredError


def test_it_carries_the_resource() -> None:
    error = LockExpiredError("invoice")

    assert error.resource == "invoice"
    assert str(error) == "lock 'invoice' expired before the store could confirm it"
