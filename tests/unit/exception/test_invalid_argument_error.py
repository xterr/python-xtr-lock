from __future__ import annotations

from xtr_lock import InvalidArgumentError


def test_it_carries_the_reason_and_is_a_value_error() -> None:
    error = InvalidArgumentError("no directory")

    assert error.reason == "no directory"
    assert str(error) == "no directory"
    assert isinstance(error, ValueError)
