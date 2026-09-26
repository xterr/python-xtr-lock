from __future__ import annotations

import dataclasses

import pytest

from xtr_lock.bundle import ConnectionReference


def test_it_names_a_type_and_an_optional_qualifier() -> None:
    assert ConnectionReference(int) == ConnectionReference(int, None)
    assert ConnectionReference(int, "locks").qualifier == "locks"


def test_it_is_immutable() -> None:
    reference = ConnectionReference(int)

    with pytest.raises(dataclasses.FrozenInstanceError):
        # The refusal is the point.
        reference.qualifier = "other"  # pyright: ignore[reportAttributeAccessIssue]  # ty: ignore[invalid-assignment]
