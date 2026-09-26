"""A store was given a lifetime it cannot keep a lock for."""

from __future__ import annotations

from .invalid_argument_error import InvalidArgumentError

__all__ = ["InvalidTtlError"]


class InvalidTtlError(InvalidArgumentError):
    """A store was given a lifetime it cannot keep a lock for.

    A store whose locks expire on their own needs a lifetime greater than
    zero: a lock that expires the moment it is taken protects nothing.

    Attributes:
        ttl: The lifetime, in seconds, that was refused.
    """

    ttl: float

    def __init__(self, ttl: float) -> None:
        """Record the lifetime that was refused."""
        self.ttl = ttl
        super().__init__(f"a lock lifetime must be strictly positive, got {ttl!r} seconds")
