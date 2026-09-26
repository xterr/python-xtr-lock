"""Unit tests for :class:`xtr_lock.bundle.LockBundle`."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
import wireup
from redis.asyncio import Redis
from xtr_dependency_injection import Kernel
from xtr_dependency_injection.exception import ServiceResolutionError
from xtr_dependency_injection.integration.wireup import injectables
from xtr_dependency_injection.testing import assert_zero_config
from xtr_logging_contracts import LoggerInterface

from tests.fixtures.app_lock_connection.services import LOCKS
from xtr_lock import (
    CombinedStore,
    ConsensusStrategy,
    FlockStore,
    InMemoryStore,
    InvalidArgumentError,
    LockFactory,
    NullStore,
    PersistingStoreInterface,
    RedisStore,
)
from xtr_lock.bundle import LOCK_CHANNEL, LockBundle

if TYPE_CHECKING:
    from xtr_dependency_injection import BootedKernel

pytestmark = pytest.mark.anyio

APP = "tests.fixtures.app_lock"


def _kernel(tmp_path: Path) -> Kernel:
    return Kernel(
        APP,
        env="test",
        environ={
            "LOCK_TEST_DSN": f"flock://{tmp_path}/from-env",
            "LOCK_TEST_REDIS_DSN": "redis://localhost:6379/15",
        },
    )


async def _store(booted: BootedKernel, resource: str) -> PersistingStoreInterface:
    return await booted.container.get(PersistingStoreInterface, resource)


async def test_zero_config_boots_and_shuts_down() -> None:
    await assert_zero_config(LockBundle)


async def test_the_default_factory_is_provided_with_and_without_a_qualifier(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        unqualified = await booted.container.get(LockFactory)
        qualified = await booted.container.get(LockFactory, "default")

    assert unqualified is qualified


async def test_flock_is_the_projects_own_directory_under_the_temporary_one(
    tmp_path: Path,
) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        store = await _store(booted, "default")
        project_dir = str(booted.container.get_parameter("kernel.project_dir"))

    digest = hashlib.sha256(project_dir.encode()).hexdigest()[:16]
    assert isinstance(store, FlockStore)
    assert store.lock_path == Path(tempfile.gettempdir()) / "xtr" / digest / "lock"


async def test_each_resource_gets_the_store_it_names(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        memory = await _store(booted, "memory")
        off = await _store(booted, "off")
        from_env = await _store(booted, "from_env")
        redis = await _store(booted, "redis")

    assert isinstance(memory, InMemoryStore)
    assert isinstance(off, NullStore)
    assert isinstance(from_env, FlockStore)
    assert from_env.lock_path == tmp_path / "from-env"
    assert isinstance(redis, RedisStore)


async def test_several_stores_make_a_majority_store(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        store = await _store(booted, "quorum")

    assert isinstance(store, CombinedStore)
    assert repr(store) == (
        f"CombinedStore({[InMemoryStore(), InMemoryStore(), InMemoryStore()]!r}, "
        f"{ConsensusStrategy()!r})"
    )


async def test_a_resource_without_stores_is_skipped(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        assert not booted.container.has(LockFactory, "skipped")
        assert not booted.container.has(PersistingStoreInterface, "skipped")


async def test_each_resource_factory_locks_in_its_own_store(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        memory = await booted.container.get(LockFactory, "memory")
        quorum = await booted.container.get(LockFactory, "quorum")

        assert await memory.create_lock("r").acquire()
        assert await quorum.create_lock("r").acquire()
        assert not await memory.create_lock("r").acquire()
        assert not await quorum.create_lock("r").acquire()


async def test_locks_log_to_the_lock_channel(tmp_path: Path) -> None:
    async with await _kernel(tmp_path).boot() as booted:
        factory = await booted.container.get(LockFactory, "memory")
        channel = await booted.container.get(LoggerInterface, LOCK_CHANNEL)

    assert factory.logger is channel


async def test_a_referenced_connection_is_the_one_the_store_uses() -> None:
    async with await Kernel("tests.fixtures.app_lock_connection", env="test").boot() as booted:
        store = await _store(booted, "default")
        client = await booted.container.get(Redis, LOCKS)

    assert isinstance(store, RedisStore)
    assert store._redis is client
    assert not store._owns_connection


async def test_boot_refuses_a_dsn_no_store_serves_without_echoing_it() -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        _ = await Kernel("tests.fixtures.app_lock_bad_dsn", env="test").boot()

    assert str(raised.value) == 'The "reports" lock resource: Unsupported connection: "mysql:".'
    assert "secret" not in str(raised.value)


async def test_boot_refuses_a_connection_the_container_does_not_provide() -> None:
    with pytest.raises(InvalidArgumentError, match=r"uses Redis\['absent'\], which the container"):
        _ = await Kernel("tests.fixtures.app_lock_missing_connection", env="test").boot()


async def test_boot_checks_a_dsn_read_from_the_environment() -> None:
    kernel = Kernel(
        APP,
        env="test",
        environ={"LOCK_TEST_DSN": "bogus://x", "LOCK_TEST_REDIS_DSN": "redis://localhost"},
    )

    with pytest.raises(InvalidArgumentError, match=r'The "from_env" lock resource'):
        _ = await kernel.boot()


async def test_boot_fails_when_a_dsn_variable_is_not_set() -> None:
    kernel = Kernel(APP, env="test", environ={"LOCK_TEST_REDIS_DSN": "redis://localhost"})

    with pytest.raises(ServiceResolutionError) as raised:
        _ = await kernel.boot()

    assert "LOCK_TEST_DSN" in str(raised.value.__cause__)


async def test_the_default_store_works_in_a_plain_wireup_container() -> None:
    container = wireup.create_async_container(injectables=injectables([LockBundle]))
    try:
        store = await container.get(PersistingStoreInterface, "default")
    finally:
        await container.close()

    assert isinstance(store, FlockStore)
    assert store.lock_path.name == "lock"
