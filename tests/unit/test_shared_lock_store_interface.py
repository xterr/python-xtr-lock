from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_lock import (
    CombinedStore,
    ConsensusStrategy,
    FlockStore,
    InMemoryStore,
    NullStore,
    SharedLockStoreInterface,
)
from xtr_lock.store.redis_store import RedisStore

if TYPE_CHECKING:
    from pathlib import Path


def test_every_store_here_can_share(tmp_path: Path) -> None:
    for store_type in (InMemoryStore, NullStore, RedisStore, CombinedStore):
        assert issubclass(store_type, SharedLockStoreInterface)
    assert isinstance(FlockStore(tmp_path), SharedLockStoreInterface)
    assert isinstance(CombinedStore([], ConsensusStrategy()), SharedLockStoreInterface)
