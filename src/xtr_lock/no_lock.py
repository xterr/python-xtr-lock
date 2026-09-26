"""A lock that is always held, for code that must be handed one but should not lock."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from typing_extensions import override

from .shared_lock_interface import SharedLockInterface

if TYPE_CHECKING:
    from types import TracebackType

__all__ = ["NoLock"]


@final
class NoLock(SharedLockInterface):
    """Says yes to everything and locks nothing.

    Hand it to code that takes a :class:`~xtr_lock.lock_interface.LockInterface`
    to switch locking off there without a branch in that code. Every acquire
    succeeds, the lock always reports itself held and never expires, and
    refreshing or releasing it does nothing.
    """

    __slots__ = ()

    @override
    async def acquire(self, blocking: bool = False) -> bool:
        """Succeed at once."""
        return True

    @override
    async def acquire_read(self, blocking: bool = False) -> bool:
        """Succeed at once."""
        return True

    @override
    async def refresh(self, ttl: float | None = None) -> None:
        """Do nothing."""

    @override
    async def is_acquired(self) -> bool:
        """Report the lock held, always."""
        return True

    @override
    async def release(self) -> None:
        """Do nothing."""

    @override
    def is_expired(self) -> bool:
        """Report the lock unexpired, always."""
        return False

    @override
    def get_remaining_lifetime(self) -> float | None:
        """Report no lifetime."""
        return None

    @override
    async def __aenter__(self) -> Self:
        """Enter at once."""
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave at once."""
