from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_lock import BlockingStoreInterface, FlockStore, InMemoryStore, NullStore

if TYPE_CHECKING:
    from pathlib import Path


def test_the_file_and_null_stores_wait_to_write_but_memory_does_not(tmp_path: Path) -> None:
    assert isinstance(FlockStore(tmp_path), BlockingStoreInterface)
    assert isinstance(NullStore(), BlockingStoreInterface)
    assert not isinstance(InMemoryStore(), BlockingStoreInterface)
