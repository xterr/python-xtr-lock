from __future__ import annotations

from xtr_lock import ConsensusStrategy, StrategyInterface, UnanimousStrategy


def test_both_strategies_satisfy_it() -> None:
    assert isinstance(ConsensusStrategy(), StrategyInterface)
    assert isinstance(UnanimousStrategy(), StrategyInterface)
