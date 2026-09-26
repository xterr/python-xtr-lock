"""A store that can hold a lock for several readers at once."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .persisting_store_interface import PersistingStoreInterface

if TYPE_CHECKING:
    from .key import Key

__all__ = ["SharedLockStoreInterface"]


@runtime_checkable
class SharedLockStoreInterface(PersistingStoreInterface, Protocol):
    """A store with a shared mode next to the exclusive one.

    :meth:`save` on a key already reading promotes it to the writer, when it
    is the only reader; :meth:`save_read` on the writer demotes it.
    """

    async def save_read(self, key: Key) -> None:
        """Take the lock for reading for ``key``, without waiting.

        Raises:
            LockConflictedError: When another key holds the lock for writing.
        """
        ...
