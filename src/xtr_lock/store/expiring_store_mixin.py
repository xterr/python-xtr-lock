"""What a store whose locks expire does once it has stored one: check it had not already."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from contextlib import suppress
from typing import TYPE_CHECKING, ClassVar

from xtr_lock.exception import LockExpiredError

if TYPE_CHECKING:
    from xtr_lock.key import Key

__all__ = ["ExpiringStoreMixin"]


class ExpiringStoreMixin(metaclass=ABCMeta):
    """For a store that sets a lifetime on the locks it keeps.

    Storing a lock takes time — a round trip, several stores in a row — and
    that time comes out of the lock's lifetime. A store calls
    :meth:`_check_not_expired` once it is done: a lock that expired on the way
    is taken back out of the store rather than reported as held.

    List it after the store's interfaces, so the store's own :meth:`delete`
    is the one found.
    """

    __slots__: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    async def delete(self, key: Key) -> None:
        """Let go of the lock ``key`` holds."""

    async def _check_not_expired(self, key: Key) -> None:
        """Take the lock back out and report it, when ``key`` has already expired.

        Raises:
            LockExpiredError: When ``key`` has expired.
        """
        if not key.is_expired():
            return

        # Taking it back out may fail too; the expiry is what the caller needs to hear about.
        with suppress(Exception):
            await self.delete(key)

        raise LockExpiredError(str(key))
