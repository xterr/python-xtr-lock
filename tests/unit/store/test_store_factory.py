from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from redis.asyncio import Redis

from xtr_lock import (
    FlockStore,
    InMemoryStore,
    InvalidArgumentError,
    NullStore,
    PersistingStoreInterface,
    RedisStore,
    StoreFactory,
)

if TYPE_CHECKING:
    from importlib.machinery import ModuleSpec

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize(
    ("connection", "expected"),
    [
        ("flock", FlockStore),
        ("in-memory", InMemoryStore),
        ("null", NullStore),
    ],
)
def test_create_store(connection: str, expected: type[PersistingStoreInterface]) -> None:
    assert type(StoreFactory.create_store(connection)) is expected


def test_flock_with_a_path_uses_that_directory(tmp_path: Path) -> None:
    store = StoreFactory.create_store(f"flock://{tmp_path}/locks")

    assert isinstance(store, FlockStore)
    assert store.lock_path == Path(f"{tmp_path}/locks")


@pytest.mark.parametrize(
    "dsn",
    [
        "redis://localhost:6379",
        "rediss://localhost:6380",
        "valkey://localhost:6379",
        "valkeys://localhost:6380",
        "unix:///var/run/redis.sock",
    ],
)
async def test_a_redis_dsn_makes_a_store_owning_its_connection(dsn: str) -> None:
    store = StoreFactory.create_store(dsn)

    assert isinstance(store, RedisStore)
    assert store._owns_connection
    await store.aclose()


async def test_a_redis_client_makes_a_store_on_that_client() -> None:
    client = Redis()

    store = StoreFactory.create_store(client)

    assert isinstance(store, RedisStore)
    assert store._redis is client
    assert not store._owns_connection
    await client.aclose()


def test_an_unsupported_object_names_its_type() -> None:
    with pytest.raises(InvalidArgumentError, match='Unsupported connection: "object"'):
        _ = StoreFactory.create_store(object())


@pytest.mark.parametrize(
    ("dsn", "described"),
    [
        ("mysql://user:secret@db/app", "mysql:"),
        ("semaphore", "semaphore"),
        ("my_redis_service", "my_redis_service"),
    ],
)
def test_an_unsupported_dsn_names_its_scheme_only(dsn: str, described: str) -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        _ = StoreFactory.create_store(dsn)

    assert str(raised.value) == f'Unsupported connection: "{described}".'


@pytest.mark.parametrize(
    "dsn",
    ["flock", "flock:///var/lock", "in-memory", "null", "redis://h", "valkeys://h", "unix:///s"],
)
def test_validate_accepts_what_create_store_builds(dsn: str) -> None:
    StoreFactory.validate(dsn)


def test_validate_refuses_an_unsupported_dsn_naming_its_scheme_only() -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        StoreFactory.validate("postgres://user:secret@db/app")

    assert str(raised.value) == 'Unsupported connection: "postgres:".'


def test_validate_refuses_a_redis_dsn_without_the_redis_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_find_spec = importlib.util.find_spec

    def without_redis(name: str, package: str | None = None) -> ModuleSpec | None:
        return None if name == "redis" else real_find_spec(name, package)

    monkeypatch.setattr(importlib.util, "find_spec", without_redis)

    with pytest.raises(InvalidArgumentError, match=r'install "xtr-lock\[redis\]"'):
        StoreFactory.validate("redis://localhost")
