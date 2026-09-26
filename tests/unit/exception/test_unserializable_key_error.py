from __future__ import annotations

from xtr_lock import UnserializableKeyError


def test_it_carries_the_resource() -> None:
    error = UnserializableKeyError("invoice")

    assert error.resource == "invoice"
    assert "'invoice'" in str(error)
    assert "cannot be pickled" in str(error)
