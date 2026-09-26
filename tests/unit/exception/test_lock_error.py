from __future__ import annotations

from xtr_lock import (
    InvalidArgumentError,
    InvalidTtlError,
    LockAcquiringError,
    LockConflictedError,
    LockError,
    LockExpiredError,
    LockReleasingError,
    LockStorageError,
    UnserializableKeyError,
)


def test_every_error_derives_from_it() -> None:
    errors = [
        InvalidArgumentError("x"),
        InvalidTtlError(0),
        LockAcquiringError("r", "x"),
        LockConflictedError("r"),
        LockExpiredError("r"),
        LockReleasingError("r", "x"),
        LockStorageError("x"),
        UnserializableKeyError("r"),
    ]

    assert all(isinstance(error, LockError) for error in errors)
