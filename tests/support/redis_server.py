"""Where the Redis server the integration tests run against is, or a skip when there is none.

Set ``REDIS_DSN`` (for instance ``redis://localhost:6379/15``) to run them.
Every test uses resources of its own and deletes them, so the database is
never flushed.
"""

from __future__ import annotations

import os

import pytest

__all__ = ["redis_dsn"]


def redis_dsn() -> str:
    """Return the server's DSN, or skip the test."""
    dsn = os.environ.get("REDIS_DSN")
    if not dsn:
        pytest.skip("REDIS_DSN is not set")

    return dsn
