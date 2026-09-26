"""A store that keeps nothing."""

from __future__ import annotations

from typing import TYPE_CHECKING, final

from typing_extensions import override

from xtr_lock.blocking_shared_lock_store_interface import BlockingSharedLockStoreInterface

if TYPE_CHECKING:
    from xtr_lock.key import Key

__all__ = ["NullStore"]


@final
class NullStore(BlockingSharedLockStoreInterface):
    """Accepts every lock at once and remembers none of them.

    Switches locking off at the store: every save succeeds without waiting,
    and :meth:`exists` always answers ``False``, so a lock on it never reports
    itself held. To switch locking off where a lock is handed in instead, use
    :class:`~xtr_lock.no_lock.NoLock`.
    """

    __slots__ = ()

    @override
    async def save(self, key: Key) -> None:
        """Do nothing."""

    @override
    async def save_read(self, key: Key) -> None:
        """Do nothing."""

    @override
    async def wait_and_save_read(self, key: Key) -> None:
        """Do nothing."""

    @override
    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        """Do nothing."""

    @override
    async def delete(self, key: Key) -> None:
        """Do nothing."""

    @override
    async def exists(self, key: Key) -> bool:
        """Answer ``False``, always."""
        return False

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
