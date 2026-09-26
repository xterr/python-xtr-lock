from __future__ import annotations

from xtr_lock import InvalidArgumentError, InvalidTtlError


def test_it_carries_the_refused_ttl() -> None:
    error = InvalidTtlError(-1.5)

    assert error.ttl == -1.5
    assert str(error) == "a lock lifetime must be strictly positive, got -1.5 seconds"
    assert isinstance(error, InvalidArgumentError)
