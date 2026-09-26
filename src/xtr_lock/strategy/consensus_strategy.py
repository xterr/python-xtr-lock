"""More than half the stores must agree."""

from __future__ import annotations

from typing import final

from typing_extensions import override

from .strategy_interface import StrategyInterface

__all__ = ["ConsensusStrategy"]


@final
class ConsensusStrategy(StrategyInterface):
    """Holds a lock once a strict majority of the stores do.

    Survives the loss of any minority of stores, which is what makes several
    independent servers safer than one.
    """

    __slots__ = ()

    @override
    def is_met(self, number_of_success: int, number_of_items: int) -> bool:
        """Tell whether more than half succeeded."""
        return number_of_success > number_of_items / 2

    @override
    def can_be_met(self, number_of_failure: int, number_of_items: int) -> bool:
        """Tell whether fewer than half have failed."""
        return number_of_failure < number_of_items / 2

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
