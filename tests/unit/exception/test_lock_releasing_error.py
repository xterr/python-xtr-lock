from __future__ import annotations

from xtr_lock import LockReleasingError


def test_it_carries_the_resource_and_reason() -> None:
    error = LockReleasingError("invoice", "still locked")

    assert (error.resource, error.reason) == ("invoice", "still locked")
    assert str(error) == "lock 'invoice': still locked"
