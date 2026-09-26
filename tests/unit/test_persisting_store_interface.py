from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_lock import (
    CombinedStore,
    ConsensusStrategy,
    FlockStore,
    InMemoryStore,
    NullStore,
    PersistingStoreInterface,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_every_store_satisfies_it(tmp_path: Path) -> None:
    stores = [
        InMemoryStore(),
        NullStore(),
        FlockStore(tmp_path),
        CombinedStore([InMemoryStore()], ConsensusStrategy()),
    ]

    assert all(isinstance(store, PersistingStoreInterface) for store in stores)


def test_an_unrelated_object_does_not() -> None:
    assert not isinstance(object(), PersistingStoreInterface)
