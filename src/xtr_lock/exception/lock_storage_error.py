"""The storage behind a store failed."""

from __future__ import annotations

from .lock_error import LockError

__all__ = ["LockStorageError"]


class LockStorageError(LockError, RuntimeError):
    """The storage behind a store failed.

    Not a question of who holds the lock: the lock file could not be opened,
    the server answered a command with an error. Whatever the storage said is
    kept in :attr:`reason`, and its own error, when there is one, is chained
    as ``__cause__``.

    Attributes:
        reason: What the storage reported.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record what the storage reported."""
        self.reason = reason
        super().__init__(reason)
