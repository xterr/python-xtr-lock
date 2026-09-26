from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_lock import BlockingSharedLockStoreInterface, FlockStore, InMemoryStore, NullStore

if TYPE_CHECKING:
    from pathlib import Path


def test_the_file_and_null_stores_wait_to_share(tmp_path: Path) -> None:
    assert isinstance(FlockStore(tmp_path), BlockingSharedLockStoreInterface)
    assert isinstance(NullStore(), BlockingSharedLockStoreInterface)
    assert not isinstance(InMemoryStore(), BlockingSharedLockStoreInterface)
