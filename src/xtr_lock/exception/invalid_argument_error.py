"""A lock, a store or a factory was given an argument it cannot work with."""

from __future__ import annotations

from .lock_error import LockError

__all__ = ["InvalidArgumentError"]


class InvalidArgumentError(LockError, ValueError):
    """A lock, a store or a factory was given an argument it cannot work with.

    Raised where the argument is given — a lock directory that cannot be
    written, a connection no store knows, a refresh with no duration — rather
    than on the first attempt to lock.

    Also a :class:`ValueError`, so code that already guards its configuration
    with ``except ValueError`` keeps working without learning a new exception.

    Attributes:
        reason: What is wrong with the argument.
    """

    reason: str

    def __init__(self, reason: str) -> None:
        """Record what is wrong with the argument."""
        self.reason = reason
        super().__init__(reason)
