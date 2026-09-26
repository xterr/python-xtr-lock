"""Releasing a lock failed, or the lock was still there afterwards."""

from __future__ import annotations

from .lock_error import LockError

__all__ = ["LockReleasingError"]


class LockReleasingError(LockError, RuntimeError):
    """Releasing a lock failed, or the lock was still there afterwards.

    A store's delete can fail outright — the underlying error is then
    chained as ``__cause__`` — or appear to succeed while the lock remains,
    which is checked for rather than trusted.

    Attributes:
        resource: The resource the lock is for.
        reason: What went wrong.
    """

    resource: str
    reason: str

    def __init__(self, resource: str, reason: str) -> None:
        """Record the resource and what went wrong."""
        self.resource = resource
        self.reason = reason
        super().__init__(f"lock {resource!r}: {reason}")
