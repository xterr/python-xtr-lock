"""The root every error in this library derives from."""

from __future__ import annotations

__all__ = ["LockError"]


class LockError(Exception):
    """Base class for every error raised by this library.

    Catch this to handle anything locking can go wrong with; catch a subclass
    to handle one cause. Every subclass carries the data a caller needs as
    typed attributes and composes its own message from them.
    """
