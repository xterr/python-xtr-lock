from __future__ import annotations

from typing import TYPE_CHECKING

from xtr_lock import BlockingStoreInterface, FlockStore, InMemoryStore, NullStore

if TYPE_CHECKING:
    from pathlib import Path


def test_only_the_file_store_waits_to_write(tmp_path: Path) -> None:
    assert isinstance(FlockStore(tmp_path), BlockingStoreInterface)
    assert not isinstance(InMemoryStore(), BlockingStoreInterface)
    assert not isinstance(NullStore(), BlockingStoreInterface)
