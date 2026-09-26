"""What code holding a lock depends on."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

if TYPE_CHECKING:
    from types import TracebackType

__all__ = ["LockInterface"]


@runtime_checkable
class LockInterface(Protocol):
    """An exclusive lock on one resource.

    Depend on this rather than on :class:`~xtr_lock.lock.Lock`, and switching
    locking off becomes a matter of handing in a
    :class:`~xtr_lock.no_lock.NoLock`.
    """

    async def acquire(self, blocking: bool = False) -> bool:
        """Take the lock.

        Args:
            blocking: Wait until the lock is free instead of giving up at
                once.

        Returns:
            ``True`` once the lock is held; ``False`` when it is held by
            someone else and ``blocking`` is false.

        Raises:
            LockConflictedError: When waiting was asked for but the store
                gave up.
            LockAcquiringError: When the store failed for any other reason.
        """
        ...

    async def refresh(self, ttl: float | None = None) -> None:
        """Push the expiry back to ``ttl`` seconds from now.

        Args:
            ttl: The new lifetime; ``None`` reuses the one the lock was made
                with.

        Raises:
            InvalidArgumentError: When no lifetime is given here or on the
                lock.
            LockConflictedError: When someone else holds the lock now.
            LockAcquiringError: When the store failed for any other reason.
        """
        ...

    async def is_acquired(self) -> bool:
        """Ask the store whether this lock is still held by its holder."""
        ...

    async def release(self) -> None:
        """Let the lock go.

        Raises:
            LockReleasingError: When the store failed to let it go, or still
                holds it afterwards.
        """
        ...

    def is_expired(self) -> bool:
        """Tell whether the lifetime set on the lock has run out."""
        ...

    def get_remaining_lifetime(self) -> float | None:
        """Return the seconds left, negative once past, ``None`` when no lifetime is set."""
        ...

    async def __aenter__(self) -> Self:
        """Wait for the lock, and hold it for the ``async with`` block."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Let the lock go on the way out of the block, if it is still held."""
        ...
