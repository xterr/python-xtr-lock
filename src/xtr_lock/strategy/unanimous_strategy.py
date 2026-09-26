"""Every store must agree."""

from __future__ import annotations

from typing import final

from typing_extensions import override

from .strategy_interface import StrategyInterface

__all__ = ["UnanimousStrategy"]


@final
class UnanimousStrategy(StrategyInterface):
    """Holds a lock only when every store does; one refusal is enough to give up."""

    __slots__ = ()

    @override
    def is_met(self, number_of_success: int, number_of_items: int) -> bool:
        """Tell whether every store succeeded."""
        return number_of_success == number_of_items

    @override
    def can_be_met(self, number_of_failure: int, number_of_items: int) -> bool:
        """Tell whether no store has failed yet."""
        return number_of_failure == 0

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"
