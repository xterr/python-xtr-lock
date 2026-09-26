from __future__ import annotations

import pytest
from redis.asyncio import Redis
from redis.exceptions import ResponseError
from xtr_clock import MockClock

from tests.support.fake_redis import FakeRedis
from xtr_lock import (
    InvalidArgumentError,
    InvalidTtlError,
    Key,
    LockConflictedError,
    LockExpiredError,
    LockStorageError,
    RedisStore,
)

pytestmark = pytest.mark.anyio

_PROBE = 'redis.call("SET", KEYS[1], "1", "PX", 1)'
_SERVER_TIME = 'local now = redis.call("TIME")\n    now = now[1]'
_CLIENT_TIME = "local now = tonumber(ARGV[1])"


def _server(answer: object = True, *, probe: object = 1) -> FakeRedis:
    """A server whose scripts may read its clock, and which answers every lock script ``answer``."""

    def reply(script: str, arguments: tuple[object, ...]) -> object:
        del arguments
        if _PROBE in script:
            if isinstance(probe, BaseException):
                raise probe
            return probe
        if isinstance(answer, BaseException):
            raise answer
        return answer

    return FakeRedis(reply)


@pytest.mark.parametrize("ttl", [0, -1])
def test_invalid_ttl(ttl: float) -> None:
    with pytest.raises(InvalidTtlError):
        _ = RedisStore(_server().as_client(), ttl)


async def test_a_script_the_server_does_not_know_is_loaded_then_run() -> None:
    fake = _server()
    store = RedisStore(fake.as_client())

    await store.save(Key("r"))

    assert fake.no_script_errors == 2  # the clock probe, then the save
    assert len(fake.runs("ZADD")) == 1


async def test_save_sends_the_clock_the_token_and_the_initial_ttl_in_milliseconds() -> None:
    fake = _server()
    clock = MockClock("2026-01-01 00:00:00")
    store = RedisStore(fake.as_client(), 1.2345, clock=clock)
    key = Key("r", clock=clock)

    await store.save(key)

    ((resource, now, token, ttl),) = fake.runs('redis.call("ZADD", key, now + ttl, "__write__")')
    assert (resource, now, ttl) == ("r", clock.now().timestamp(), 1235)
    assert token == key.get_state(RedisStore)
    assert key.get_remaining_lifetime() == pytest.approx(1.2345)


async def test_the_servers_clock_is_used_when_scripts_may_read_it() -> None:
    fake = _server(probe=1)

    assert await RedisStore(fake.as_client()).exists(Key("r"))

    (script, _) = fake.evaluated[-1]
    assert _SERVER_TIME in script
    assert _CLIENT_TIME not in script


@pytest.mark.parametrize(
    "refusal",
    [
        "ERR Write commands not allowed after non deterministic commands",
        "ERR This Redis command is not allowed from script script",
    ],
)
async def test_this_process_clock_is_sent_when_the_server_refuses_its_own(refusal: str) -> None:
    fake = _server(probe=ResponseError(refusal))
    store = RedisStore(fake.as_client())

    await store.save(Key("r"))
    await store.save(Key("other"))

    lock_scripts = [script for script, _ in fake.evaluated if _PROBE not in script]
    assert all(_CLIENT_TIME in script for script in lock_scripts)
    assert len(lock_scripts) == 2


async def test_any_other_probe_error_is_a_storage_error() -> None:
    fake = _server(probe=ResponseError("ERR out of memory"))

    with pytest.raises(LockStorageError, match="out of memory") as raised:
        await RedisStore(fake.as_client()).save(Key("r"))

    assert isinstance(raised.value.__cause__, ResponseError)


async def test_a_refused_save_is_a_conflict() -> None:
    with pytest.raises(LockConflictedError):
        await RedisStore(_server(answer=None).as_client()).save(Key("r"))


async def test_a_refused_read_save_is_a_conflict() -> None:
    with pytest.raises(LockConflictedError):
        await RedisStore(_server(answer=None).as_client()).save_read(Key("r"))


async def test_a_refused_extension_is_a_conflict() -> None:
    with pytest.raises(LockConflictedError):
        await RedisStore(_server(answer=None).as_client()).put_off_expiration(Key("r"), 5)


async def test_a_server_error_is_a_storage_error() -> None:
    fake = _server(answer=ResponseError("WRONGTYPE Operation against a key"))

    with pytest.raises(LockStorageError, match="WRONGTYPE"):
        await RedisStore(fake.as_client()).save(Key("r"))


async def test_a_save_that_outlived_its_lifetime_is_taken_back() -> None:
    clock = MockClock("2026-01-01 00:00:00")

    def reply(script: str, arguments: tuple[object, ...]) -> object:
        del arguments
        if "ZADD" in script and "__write__" in script:
            clock.sleep(301)
        return 1

    fake = FakeRedis(reply)
    store = RedisStore(fake.as_client(), clock=clock)

    with pytest.raises(LockExpiredError):
        await store.save(Key("r", clock=clock))

    assert len(fake.runs('redis.call("ZREM", key, uniqueToken)')) == 1


async def test_delete_and_exists_run_their_scripts() -> None:
    fake = _server(answer=0)
    store = RedisStore(fake.as_client())
    key = Key("r")

    await store.delete(key)

    assert not await store.exists(key)
    ((resource, token),) = fake.runs('redis.call("ZREM", key, uniqueToken)')
    assert (resource, token) == ("r", key.get_state(RedisStore))


async def test_the_write_marker_is_never_used_as_a_token() -> None:
    fake = _server()
    key = Key("r")
    key.set_state(RedisStore, "__write__")

    _ = await RedisStore(fake.as_client()).exists(key)

    assert key.get_state(RedisStore) != "__write__"


@pytest.mark.parametrize(
    ("dsn", "expected"),
    [
        ("redis://localhost:6379/3", {"host": "localhost", "port": 6379, "db": 3}),
        ("valkey://cache:6380", {"host": "cache", "port": 6380}),
        ("unix:///tmp/redis.sock", {"path": "/tmp/redis.sock"}),  # noqa: S108 — only parsed.
    ],
)
async def test_from_url_reads_the_dsn(dsn: str, expected: dict[str, object]) -> None:
    store = RedisStore.from_url(dsn)
    client = store._redis

    kwargs = client.connection_pool.connection_kwargs
    assert {name: kwargs.get(name) for name in expected} == expected
    await store.aclose()


async def test_valkeys_reads_as_a_tls_connection() -> None:
    store = RedisStore.from_url("valkeys://cache:6380")

    assert store._redis.connection_pool.connection_class.__name__ == "SSLConnection"
    await store.aclose()


def test_from_url_refuses_another_scheme_without_echoing_the_dsn() -> None:
    with pytest.raises(InvalidArgumentError) as raised:
        _ = RedisStore.from_url("memcached://user:secret@host")

    assert "secret" not in str(raised.value)
    assert '"memcached"' in str(raised.value)


async def test_aclose_closes_only_a_connection_the_store_opened() -> None:
    fake = _server()
    lent = RedisStore(fake.as_client())

    await lent.aclose()

    assert not fake.closed

    owned = RedisStore(fake.as_client())
    owned._owns_connection = True
    await owned.aclose()

    assert fake.closed


async def test_from_url_builds_an_asyncio_client() -> None:
    store = RedisStore.from_url("redis://localhost:6379")

    assert isinstance(store._redis, Redis)
    await store.aclose()


async def test_the_prefix_goes_in_front_of_every_redis_key() -> None:
    fake = _server()
    store = RedisStore(fake.as_client(), prefix="app:")
    key = Key("r")

    await store.save(key)
    await store.put_off_expiration(key, 5)
    _ = await store.exists(key)
    await store.delete(key)

    names = [arguments[0] for _, arguments in fake.evaluated]
    assert names == [
        "app:xtr_lock_check_support_time",
        "app:r",
        "app:r",
        "app:r",
        "app:r",
    ]
    assert store.prefix == "app:"


async def test_a_conflict_names_the_resource_not_the_redis_key() -> None:
    store = RedisStore(_server(answer=None).as_client(), prefix="app:")

    with pytest.raises(LockConflictedError) as raised:
        await store.save(Key("r"))

    assert raised.value.resource == "r"


async def test_from_url_takes_the_prefix_out_of_the_dsn() -> None:
    store = RedisStore.from_url("redis://localhost:6379/2?prefix=app%3Alocks%3A&socket_timeout=3")

    kwargs = store._redis.connection_pool.connection_kwargs
    assert store.prefix == "app:locks:"
    assert "prefix" not in kwargs
    assert (kwargs.get("db"), kwargs.get("socket_timeout")) == (2, 3.0)
    await store.aclose()


async def test_without_a_prefix_option_there_is_no_prefix() -> None:
    store = RedisStore.from_url("redis://localhost:6379")

    assert store.prefix == ""
    await store.aclose()


async def test_create_connection_never_hands_the_prefix_to_the_client() -> None:
    client = RedisStore.create_connection("unix:///tmp/redis.sock?prefix=x&db=4")

    kwargs = client.connection_pool.connection_kwargs
    assert "prefix" not in kwargs
    assert (kwargs.get("path"), kwargs.get("db")) == ("/tmp/redis.sock", 4)  # noqa: S108 — as above.
    await client.aclose()
