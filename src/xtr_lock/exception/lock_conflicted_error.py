"""Someone else holds the lock."""

from __future__ import annotations

from .lock_error import LockError

__all__ = ["LockConflictedError"]


class LockConflictedError(LockError, RuntimeError):
    """Someone else holds the lock.

    The one signal a store gives for contention. A non-blocking
    :meth:`~xtr_lock.lock.Lock.acquire` turns it into ``False``; a blocking
    one waits it out; :meth:`~xtr_lock.lock.Lock.refresh` lets it through,
    since a lock that can no longer be extended has been lost.

    Attributes:
        resource: The resource someone else holds.
    """

    resource: str

    def __init__(self, resource: str) -> None:
        """Record the resource someone else holds."""
        self.resource = resource
        super().__init__(f"lock {resource!r} is held by someone else")
