"""How many of several stores must hold a lock for it to count as held."""

from __future__ import annotations

from .consensus_strategy import ConsensusStrategy
from .strategy_interface import StrategyInterface
from .unanimous_strategy import UnanimousStrategy

__all__ = ["ConsensusStrategy", "StrategyInterface", "UnanimousStrategy"]
