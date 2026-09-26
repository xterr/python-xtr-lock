from __future__ import annotations

from xtr_lock import LockAcquiringError


def test_it_carries_the_resource_and_reason() -> None:
    error = LockAcquiringError("invoice", "failed to acquire the lock")

    assert (error.resource, error.reason) == ("invoice", "failed to acquire the lock")
    assert str(error) == "lock 'invoice': failed to acquire the lock"
    assert isinstance(error, RuntimeError)
