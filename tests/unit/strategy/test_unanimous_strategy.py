from __future__ import annotations

import pytest

from xtr_lock import UnanimousStrategy

# (success, failure, total, expected) — a failure count only matters to can_be_met.


@pytest.mark.parametrize(
    ("success", "failure", "total", "expected"),
    [
        (3, 0, 3, True),
        (2, 1, 3, False),
        (2, 0, 3, False),
        (1, 2, 3, False),
        (1, 1, 3, False),
        (1, 0, 3, False),
        (0, 3, 3, False),
        (0, 2, 3, False),
        (0, 1, 3, False),
        (0, 0, 3, False),
        (2, 0, 2, True),
        (1, 1, 2, False),
        (1, 0, 2, False),
        (0, 2, 2, False),
        (0, 1, 2, False),
        (0, 0, 2, False),
    ],
)
def test_met_on_success(success: int, failure: int, total: int, expected: bool) -> None:
    del failure
    assert UnanimousStrategy().is_met(success, total) is expected


@pytest.mark.parametrize(
    ("success", "failure", "total", "expected"),
    [
        (3, 0, 3, True),
        (2, 1, 3, False),
        (2, 0, 3, True),
        (1, 2, 3, False),
        (1, 1, 3, False),
        (1, 0, 3, True),
        (0, 3, 3, False),
        (0, 2, 3, False),
        (0, 1, 3, False),
        (0, 0, 3, True),
        (2, 0, 2, True),
        (1, 1, 2, False),
        (1, 0, 2, True),
        (0, 2, 2, False),
        (0, 1, 2, False),
        (0, 0, 2, True),
    ],
)
def test_can_be_met(success: int, failure: int, total: int, expected: bool) -> None:
    del success
    assert UnanimousStrategy().can_be_met(failure, total) is expected
