"""Every error this library raises.

All of them derive from :class:`LockError`, so one ``except`` catches
anything a lock can go wrong with, and a narrower one handles a single
cause. Each carries the data a caller needs as typed attributes rather than
forcing a message to be parsed.
"""

from __future__ import annotations

from .invalid_argument_error import InvalidArgumentError
from .invalid_ttl_error import InvalidTtlError
from .lock_acquiring_error import LockAcquiringError
from .lock_conflicted_error import LockConflictedError
from .lock_error import LockError
from .lock_expired_error import LockExpiredError
from .lock_releasing_error import LockReleasingError
from .lock_storage_error import LockStorageError
from .unserializable_key_error import UnserializableKeyError

__all__ = [
    "InvalidArgumentError",
    "InvalidTtlError",
    "LockAcquiringError",
    "LockConflictedError",
    "LockError",
    "LockExpiredError",
    "LockReleasingError",
    "LockStorageError",
    "UnserializableKeyError",
]
