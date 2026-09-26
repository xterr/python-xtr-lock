"""A shared-lock store that can also wait for a read lock to come free."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .shared_lock_store_interface import SharedLockStoreInterface

if TYPE_CHECKING:
    from .key import Key

__all__ = ["BlockingSharedLockStoreInterface"]


@runtime_checkable
class BlockingSharedLockStoreInterface(SharedLockStoreInterface, Protocol):
    """A store that is told when a writer lets go, instead of asking over and over.

    Without it, a blocking :meth:`~xtr_lock.lock.Lock.acquire_read` retries
    :meth:`save_read` every tenth of a second.
    """

    async def wait_and_save_read(self, key: Key) -> None:
        """Wait until no writer holds the lock, then take it for reading for ``key``."""
        ...
