from __future__ import annotations

import pytest

from xtr_lock import InvalidArgumentError
from xtr_lock.bundle import DEFAULT_RESOURCE, ConnectionReference, LockConfig


def test_the_default_is_one_flock_resource() -> None:
    assert LockConfig().stores_by_resource() == {DEFAULT_RESOURCE: ("flock",)}


def test_no_resources_means_the_default_one() -> None:
    assert LockConfig(resources={}).stores_by_resource() == {"default": ("flock",)}


def test_every_resource_reads_as_a_tuple_of_stores() -> None:
    reference = ConnectionReference(object, "q")
    config = LockConfig(
        resources={
            "one": "in-memory",
            "many": ["redis://a", "redis://b"],
            "service": reference,
            "none": [],
        },
    )

    assert config.stores_by_resource() == {
        "one": ("in-memory",),
        "many": ("redis://a", "redis://b"),
        "service": (reference,),
        "none": (),
    }


def test_a_resource_needs_a_name() -> None:
    with pytest.raises(InvalidArgumentError, match="non-empty name"):
        _ = LockConfig(resources={"": "flock"})


@pytest.mark.parametrize("entry", [42, None, ["flock", 3]])
def test_a_store_must_be_a_string_or_a_reference(entry: object) -> None:
    with pytest.raises(InvalidArgumentError, match='for the "r" resource'):
        # The refusal is the point.
        _ = LockConfig(resources={"r": entry})  # pyright: ignore[reportArgumentType]  # ty: ignore[invalid-argument-type]
