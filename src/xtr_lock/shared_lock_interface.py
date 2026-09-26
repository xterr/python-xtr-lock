"""A lock that can also be held for reading, by several holders at once."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .lock_interface import LockInterface

__all__ = ["SharedLockInterface"]


@runtime_checkable
class SharedLockInterface(LockInterface, Protocol):
    """A lock with a shared, read-only mode next to the exclusive one.

    Any number of holders may read at once; a writer excludes everyone. A
    sole reader may become the writer, and a writer may step down to a
    reader, without letting go in between.
    """

    async def acquire_read(self, blocking: bool = False) -> bool:
        """Take the lock for reading.

        Falls back to the exclusive lock when the store cannot share.

        Args:
            blocking: Wait until the lock can be shared instead of giving up
                at once.

        Returns:
            ``True`` once the lock is held; ``False`` when a writer holds it
            and ``blocking`` is false.

        Raises:
            LockConflictedError: When waiting was asked for but the store
                gave up.
            LockAcquiringError: When the store failed for any other reason.
        """
        ...
