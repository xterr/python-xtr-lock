"""A key holding something that cannot leave the process was pickled."""

from __future__ import annotations

from .lock_error import LockError

__all__ = ["UnserializableKeyError"]


class UnserializableKeyError(LockError, RuntimeError):
    """A key holding something that cannot leave the process was pickled.

    Some stores keep an operating system handle on the key — an open file
    descriptor, for one — which means nothing to another process. Once such a
    store has touched a key, the key refuses to be pickled rather than arrive
    somewhere else claiming a lock it cannot hold.

    Attributes:
        resource: The resource the key is for.
    """

    resource: str

    def __init__(self, resource: str) -> None:
        """Record the resource the key is for."""
        self.resource = resource
        super().__init__(
            f"the key for {resource!r} holds state its store keeps in this process only, "
            f"so it cannot be pickled",
        )
