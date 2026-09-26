"""A store that can wait for a lock to come free."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .persisting_store_interface import PersistingStoreInterface

if TYPE_CHECKING:
    from .key import Key

__all__ = ["BlockingStoreInterface"]


@runtime_checkable
class BlockingStoreInterface(PersistingStoreInterface, Protocol):
    """A store that is told when a lock comes free, instead of asking over and over.

    Without it, a blocking :meth:`~xtr_lock.lock.Lock.acquire` retries
    :meth:`save` every tenth of a second.
    """

    async def wait_and_save(self, key: Key) -> None:
        """Wait until the lock is free, then take it for ``key``."""
        ...
