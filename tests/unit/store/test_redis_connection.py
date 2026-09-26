from __future__ import annotations

import importlib.util
import sys

import pytest
from redis.asyncio import Redis

from xtr_lock import InvalidArgumentError
from xtr_lock.store import (
    REDIS_SCHEMES,
    create_redis_client,
    is_redis_client,
    is_redis_dsn,
    redis_installed,
)

pytestmark = pytest.mark.anyio

MISSING = 'install "some-package[redis]"'


@pytest.mark.parametrize(
    ("dsn", "connection"),
    [
        ("redis://localhost:6379/2", "Connection"),
        ("rediss://localhost:6379", "SSLConnection"),
        ("VALKEY://localhost:6379", "Connection"),
        ("valkeys://localhost:6379", "SSLConnection"),
        ("unix:///tmp/redis.sock", "UnixDomainSocketConnection"),
    ],
)
async def test_a_dsn_makes_a_client_of_its_scheme_without_connecting(
    dsn: str,
    connection: str,
) -> None:
    client = create_redis_client(dsn, missing=MISSING)

    assert isinstance(client, Redis)
    assert client.connection_pool.connection_class.__name__ == connection
    await client.aclose()


def test_a_scheme_that_is_not_redis_is_refused_naming_it_and_nothing_else() -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        _ = create_redis_client("mysql://user:secret@db/app", missing=MISSING)

    assert raised.value.reason.startswith('"mysql" is not a Redis scheme')
    assert "secret" not in raised.value.reason


def test_without_the_client_library_the_callers_reason_is_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "redis.asyncio", None)

    with pytest.raises(InvalidArgumentError) as raised:
        _ = create_redis_client("redis://localhost", missing=MISSING)

    assert raised.value.reason == MISSING


@pytest.mark.parametrize(
    ("dsn", "is_redis"),
    [
        ("redis://a", True),
        ("VALKEYS://a", True),
        ("unix:///s", True),
        ("flock", False),
        ("http://a", False),
    ],
)
def test_it_recognises_redis_dsns(dsn: str, is_redis: bool) -> None:
    assert is_redis_dsn(dsn) is is_redis


async def test_it_recognises_a_client_only_once_the_library_is_loaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = create_redis_client("redis://localhost", missing=MISSING)

    assert is_redis_client(client)
    assert not is_redis_client(object())
    monkeypatch.delitem(sys.modules, "redis.asyncio")
    assert not is_redis_client(client)
    await client.aclose()


def test_it_knows_whether_the_library_is_installed(monkeypatch: pytest.MonkeyPatch) -> None:
    assert redis_installed()

    monkeypatch.setattr(importlib.util, "find_spec", _no_spec)

    assert not redis_installed()


def test_every_scheme_maps_to_one_the_client_reads() -> None:
    assert set(REDIS_SCHEMES.values()) == {"redis", "rediss", "unix"}


def _no_spec(name: str) -> None:
    del name
