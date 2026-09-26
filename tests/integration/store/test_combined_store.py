"""The combined store over real Redis stores: lifetimes are enforced, and a quorum decides."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.support.store_conformance import (
    AbstractStoreTests,
    ExpiringStoreTests,
    SharedLockStoreTests,
)
from xtr_lock import (
    CombinedStore,
    ConsensusStrategy,
    InMemoryStore,
    Key,
    LockConflictedError,
    RedisStore,
    UnanimousStrategy,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

pytestmark = pytest.mark.anyio


class TestCombinedStoreOverRedis(AbstractStoreTests, ExpiringStoreTests, SharedLockStoreTests):
    @pytest.fixture
    def store(self, redis_client: Redis) -> CombinedStore:
        return CombinedStore([RedisStore(redis_client)], UnanimousStrategy())


async def test_a_majority_holds_the_lock_when_one_store_is_taken(
    redis_client: Redis,
    resource: str,
) -> None:
    taken = InMemoryStore()
    await taken.save(Key(resource))
    stores = [RedisStore(redis_client), taken, InMemoryStore()]
    first = Key(resource)

    await CombinedStore(stores, ConsensusStrategy()).save(first)

    with pytest.raises(LockConflictedError):
        await CombinedStore(stores, ConsensusStrategy()).save(Key(resource))

    await CombinedStore(stores, ConsensusStrategy()).delete(first)
