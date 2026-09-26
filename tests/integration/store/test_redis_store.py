"""The Redis store against a real server: the shared conformance suite, and its own guarantees."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.support.redis_server import redis_dsn
from tests.support.store_conformance import (
    AbstractStoreTests,
    ExpiringStoreTests,
    SharedLockStoreTests,
)
from xtr_lock import Key, Lock, LockConflictedError, RedisStore

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = pytest.mark.anyio


class TestRedisStore(AbstractStoreTests, ExpiringStoreTests, SharedLockStoreTests):
    @pytest.fixture
    def store(self, redis_client: Redis) -> RedisStore:
        return RedisStore(redis_client)


async def test_a_plain_string_under_the_key_is_a_conflict(
    redis_client: Redis,
    resource: str,
) -> None:
    _ = await redis_client.set(resource, "someone else", px=5000)

    with pytest.raises(LockConflictedError):
        await RedisStore(redis_client).save(Key(resource))

    _ = await redis_client.delete(resource)


async def test_write_member_is_not_owned_by_the_key_that_names_it(
    redis_client: Redis,
    resource: str,
) -> None:
    store = RedisStore(redis_client)
    key1 = Key(resource)
    await store.save(key1)

    key2 = Key(resource)
    key2.set_state(RedisStore, "__write__")

    assert not await store.exists(key2)
    await store.delete(key1)


async def test_write_member_does_not_grant_a_second_write_lock(
    redis_client: Redis,
    resource: str,
) -> None:
    store = RedisStore(redis_client)
    key1 = Key(resource)
    await store.save(key1)

    key2 = Key(resource)
    key2.set_state(RedisStore, "__write__")

    with pytest.raises(LockConflictedError):
        await store.save(key2)
    await store.delete(key1)


async def test_write_member_cannot_be_deleted_by_another_key(
    redis_client: Redis,
    resource: str,
) -> None:
    store = RedisStore(redis_client)
    key1 = Key(resource)
    await store.save(key1)

    key2 = Key(resource)
    key2.set_state(RedisStore, "__write__")
    await store.delete(key2)

    assert await store.exists(key1)
    with pytest.raises(LockConflictedError):
        await store.save_read(Key(resource))
    await store.delete(key1)


async def test_the_key_disappears_once_its_last_holder_lets_go(
    redis_client: Redis,
    resource: str,
) -> None:
    store = RedisStore(redis_client)
    key = Key(resource)
    await store.save(key)
    await store.delete(key)

    remaining = await redis_client.exists(resource)

    assert remaining == 0


async def test_a_lock_takes_its_own_lifetime_over_the_initial_one(
    redis_client: Redis,
    resource: str,
) -> None:
    lock = Lock(Key(resource), RedisStore(redis_client, initial_ttl=300), ttl=2)

    assert await lock.acquire()
    ttl_ms = await redis_client.pttl(resource)

    assert 0 < ttl_ms <= 2000
    await lock.release()


async def test_from_url_owns_and_closes_its_connection(resource: str) -> None:
    store = RedisStore.from_url(redis_dsn())
    key = Key(resource)

    await store.save(key)
    assert await store.exists(key)
    await store.delete(key)
    await store.aclose()


async def test_the_prefix_names_the_redis_key(redis_client: Redis, resource: str) -> None:
    store = RedisStore(redis_client, prefix="xtr-lock-prefixed:")
    key = Key(resource)

    await store.save(key)

    assert await redis_client.exists(f"xtr-lock-prefixed:{resource}") == 1
    assert await redis_client.exists(resource) == 0
    await store.delete(key)
