from __future__ import annotations

import pickle
from typing import cast, final

import pytest
from xtr_clock import Clock, MockClock

from xtr_lock import InvalidArgumentError, Key, UnserializableKeyError


def test_it_reads_as_its_resource() -> None:
    key = Key("invoice-42")

    assert str(key) == "invoice-42"
    assert repr(key) == "Key('invoice-42')"


def test_state_is_kept_per_state_key() -> None:
    key = Key("r")

    key.set_state("a", 1)
    key.set_state("b", 2)
    key.remove_state("a")
    key.remove_state("missing")

    assert not key.has_state("a")
    assert key.has_state("b")
    assert key.get_state("b") == 2
    with pytest.raises(KeyError):
        _ = key.get_state("a")


def test_a_fresh_key_has_no_lifetime() -> None:
    key = Key("r")

    assert key.get_remaining_lifetime() is None
    assert not key.is_expired()


def test_reduce_lifetime_only_ever_shortens() -> None:
    clock = MockClock("2026-01-01 00:00:00")
    key = Key("r", clock=clock)

    key.reduce_lifetime(10)
    key.reduce_lifetime(30)
    assert key.get_remaining_lifetime() == 10

    key.reduce_lifetime(4)
    assert key.get_remaining_lifetime() == 4


def test_reset_lifetime_forgets_the_expiry() -> None:
    key = Key("r")
    key.reduce_lifetime(-1)

    key.reset_lifetime()

    assert key.get_remaining_lifetime() is None
    assert not key.is_expired()


def test_it_expires_when_the_clock_reaches_the_deadline() -> None:
    clock = MockClock("2026-01-01 00:00:00")
    key = Key("r", clock=clock)
    key.reduce_lifetime(5)

    clock.sleep(4.999)
    assert not key.is_expired()

    clock.sleep(0.001)
    assert key.is_expired()
    assert key.get_remaining_lifetime() == pytest.approx(0)

    clock.sleep(1)
    assert key.get_remaining_lifetime() == pytest.approx(-1)


def test_without_a_clock_it_counts_monotonically_whatever_clock_is_in_force() -> None:
    clock = MockClock("2026-01-01 00:00:00")
    key = Key("r")

    with Clock.using(clock):
        key.reduce_lifetime(5)
        clock.sleep(6)

        assert not key.is_expired()
        remaining = key.get_remaining_lifetime()
        assert remaining is not None
        assert 4 < remaining <= 5


@pytest.mark.parametrize(
    ("ttls", "expected"),
    [
        ([-0.1], True),
        ([0.1, -0.1], True),
        ([-0.1, 0.1], True),
        ([], False),
        ([0.1], False),
        ([-0.1, None], False),
    ],
)
def test_expiration(ttls: list[float | None], expected: bool) -> None:
    key = Key("r")

    for ttl in ttls:
        if ttl is None:
            key.reset_lifetime()
        else:
            key.reduce_lifetime(ttl)

    assert key.is_expired() is expected


def test_serialize() -> None:
    key = Key("r")
    key.reduce_lifetime(60)
    key.set_state("store", "token")

    copy = cast("Key", pickle.loads(pickle.dumps(key)))  # noqa: S301 — the pickle was made here.

    assert str(copy) == "r"
    assert copy.get_state("store") == "token"
    remaining = copy.get_remaining_lifetime()
    assert remaining is not None
    assert 59 < remaining <= 60


def test_an_unserializable_key_refuses_to_be_pickled() -> None:
    key = Key("r")

    key.mark_unserializable()

    with pytest.raises(UnserializableKeyError) as raised:
        _ = pickle.dumps(key)
    assert raised.value.resource == "r"


def test_unserialize_rejects_a_resource_that_is_not_a_plain_string() -> None:
    @final
    class Sneaky(str):
        __slots__ = ()

    key = Key("r")

    for resource in (Sneaky("r"), 42, None):
        with pytest.raises(InvalidArgumentError, match="must carry its resource as a str"):
            key.__setstate__({"resource": resource})


def test_unserialize_tolerates_missing_optional_fields() -> None:
    key = Key("old")

    key.__setstate__({"resource": "r"})

    assert str(key) == "r"
    assert key.get_remaining_lifetime() is None
    assert not key.has_state("anything")
