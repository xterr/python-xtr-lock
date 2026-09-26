"""A lock's lifetime ran out before the store confirmed it."""

from __future__ import annotations

from .lock_error import LockError

__all__ = ["LockExpiredError"]


class LockExpiredError(LockError, RuntimeError):
    """A lock's lifetime ran out before the store confirmed it.

    Storing the lock took longer than the lock was meant to live — a slow
    network, several stores in a row — so by the time it was stored it had
    already expired. The store has been asked to forget it again.

    Attributes:
        resource: The resource the lock is for.
    """

    resource: str

    def __init__(self, resource: str) -> None:
        """Record the resource whose lock expired."""
        self.resource = resource
        super().__init__(f"lock {resource!r} expired before the store could confirm it")
