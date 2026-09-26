"""Acquiring a lock, or extending one, failed for a reason other than contention."""

from __future__ import annotations

from .lock_error import LockError

__all__ = ["LockAcquiringError"]


class LockAcquiringError(LockError, RuntimeError):
    """Acquiring a lock, or extending one, failed for a reason other than contention.

    The store could not be reached, answered with an error, or the lock
    expired before the store confirmed it. The underlying error is chained as
    ``__cause__``. Contention is not a failure of this kind: a lock someone
    else holds is :class:`~xtr_lock.exception.LockConflictedError`.

    Attributes:
        resource: The resource the lock is for.
        reason: What was being attempted when it failed.
    """

    resource: str
    reason: str

    def __init__(self, resource: str, reason: str) -> None:
        """Record the resource and what was being attempted."""
        self.resource = resource
        self.reason = reason
        super().__init__(f"lock {resource!r}: {reason}")
