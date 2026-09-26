"""How many stores must agree before a lock held in several of them counts."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["StrategyInterface"]


@runtime_checkable
class StrategyInterface(Protocol):
    """Decides whether a lock held in some of several stores is held."""

    def is_met(self, number_of_success: int, number_of_items: int) -> bool:
        """Tell whether ``number_of_success`` stores out of ``number_of_items`` are enough."""
        ...

    def can_be_met(self, number_of_failure: int, number_of_items: int) -> bool:
        """Tell whether enough stores could still agree after ``number_of_failure`` refused.

        A ``True`` promises nothing; a ``False`` means asking the remaining
        stores is pointless.
        """
        ...
