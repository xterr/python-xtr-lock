"""What every store does: keep a lock, forget it, and say whether it has it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .key import Key

__all__ = ["PersistingStoreInterface"]


@runtime_checkable
class PersistingStoreInterface(Protocol):
    """Where locks are kept.

    The store-side contract: a :class:`~xtr_lock.lock.Lock` decides *when* to
    lock, a store decides *how*. A store that can also wait, or share, adds
    the matching interface; :class:`~xtr_lock.lock.Lock` looks for them and
    uses the best one available.
    """

    async def save(self, key: Key) -> None:
        """Take the lock for ``key``, without waiting.

        Saving a key that already holds the lock is not an error.

        Raises:
            LockConflictedError: When another key holds the lock.
        """
        ...

    async def delete(self, key: Key) -> None:
        """Let go of the lock ``key`` holds; a key holding nothing is fine."""
        ...

    async def exists(self, key: Key) -> bool:
        """Tell whether ``key`` holds the lock."""
        ...

    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        """Keep the lock ``key`` holds for another ``ttl`` seconds.

        A store whose locks never expire does nothing.

        Raises:
            LockConflictedError: When ``key`` no longer holds the lock.
        """
        ...
