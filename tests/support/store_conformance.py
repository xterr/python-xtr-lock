"""What every store must do, as test classes a store's own tests inherit.

A store's test class inherits :class:`AbstractStoreTests` plus one class per
capability it has, and defines a ``store`` fixture. Every test names its
resources through the ``resource`` fixture, so a store backed by a shared
server sees no leftovers from another test.
"""

from __future__ import annotations

import asyncio
import pickle
from typing import TYPE_CHECKING

import pytest

from xtr_lock import Key, LockConflictedError, LockExpiredError, UnserializableKeyError

if TYPE_CHECKING:
    from xtr_lock import (
        BlockingStoreInterface,
        PersistingStoreInterface,
        SharedLockStoreInterface,
    )

__all__ = [
    "AbstractStoreTests",
    "BlockingStoreTests",
    "ExpiringStoreTests",
    "SharedLockStoreTests",
    "UnserializableKeyTests",
]

_SETTLE = 0.05
"""Long enough for a waiting task to have started waiting."""


class AbstractStoreTests:
    """Saving, checking and deleting, for any store."""

    async def test_save(self, store: PersistingStoreInterface, resource: str) -> None:
        key = Key(resource)

        assert not await store.exists(key)
        await store.save(key)
        assert await store.exists(key)
        await store.delete(key)
        assert not await store.exists(key)

    async def test_save_with_different_resources(
        self,
        store: PersistingStoreInterface,
        resource: str,
    ) -> None:
        key1 = Key(f"{resource}1")
        key2 = Key(f"{resource}2")

        await store.save(key1)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.save(key2)
        assert await store.exists(key1)
        assert await store.exists(key2)

        await store.delete(key1)
        assert not await store.exists(key1)
        assert await store.exists(key2)

        await store.delete(key2)
        assert not await store.exists(key1)
        assert not await store.exists(key2)

    async def test_save_with_different_keys_on_same_resources(
        self,
        store: PersistingStoreInterface,
        resource: str,
    ) -> None:
        key1 = Key(resource)
        key2 = Key(resource)

        await store.save(key1)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        with pytest.raises(LockConflictedError):
            await store.save(key2)

        # The failed attempt must not disturb the lock already held.
        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.delete(key1)
        assert not await store.exists(key1)
        assert not await store.exists(key2)

        await store.save(key2)
        assert not await store.exists(key1)
        assert await store.exists(key2)

        await store.delete(key2)
        assert not await store.exists(key1)
        assert not await store.exists(key2)

    async def test_save_twice(self, store: PersistingStoreInterface, resource: str) -> None:
        key = Key(resource)

        await store.save(key)
        await store.save(key)

        assert await store.exists(key)
        await store.delete(key)

    async def test_delete_isolated(self, store: PersistingStoreInterface, resource: str) -> None:
        key1 = Key(f"{resource}1")
        key2 = Key(f"{resource}2")

        await store.save(key1)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.delete(key2)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.delete(key1)


class ExpiringStoreTests:
    """Lifetimes a store enforces itself. Time-sensitive: ``clock_delay`` may need tuning."""

    clock_delay: float = 0.25
    """Seconds to wait around an expiry: short enough to be quick, long enough not to race."""

    async def test_expiration(self, store: PersistingStoreInterface, resource: str) -> None:
        key = Key(resource)

        await store.save(key)
        await store.put_off_expiration(key, 2 * self.clock_delay)
        assert await store.exists(key)

        await asyncio.sleep(3 * self.clock_delay)
        assert not await store.exists(key)

    async def test_abort_after_expiration(
        self,
        store: PersistingStoreInterface,
        resource: str,
    ) -> None:
        key = Key(resource)

        await store.save(key)
        with pytest.raises(LockExpiredError):
            await store.put_off_expiration(key, 1 / 1_000_000)

    async def test_refresh_lock(self, store: PersistingStoreInterface, resource: str) -> None:
        key = Key(resource)

        await store.save(key)
        await store.put_off_expiration(key, 2 * self.clock_delay)
        await asyncio.sleep(self.clock_delay)
        await store.put_off_expiration(key, 2 * self.clock_delay)
        await asyncio.sleep(1.5 * self.clock_delay)
        assert await store.exists(key)

        await asyncio.sleep(1.5 * self.clock_delay)
        assert not await store.exists(key)

    async def test_set_expiration(self, store: PersistingStoreInterface, resource: str) -> None:
        key = Key(resource)

        await store.save(key)
        await store.put_off_expiration(key, 1)

        remaining = key.get_remaining_lifetime()
        assert remaining is not None
        assert 0 <= remaining <= 1
        await store.delete(key)

    async def test_expired_lock_cleaned(
        self,
        store: PersistingStoreInterface,
        resource: str,
    ) -> None:
        key1 = Key(resource)
        key2 = Key(resource)
        key1.reduce_lifetime(0)

        assert key1.is_expired()
        with pytest.raises(LockExpiredError):
            await store.save(key1)

        assert not await store.exists(key1)

        await store.save(key2)
        assert await store.exists(key2)
        await store.delete(key2)


class BlockingStoreTests:
    """Waiting for a lock without spinning on the event loop."""

    async def test_wait_and_save_waits_for_the_holder(
        self,
        store: BlockingStoreInterface,
        resource: str,
    ) -> None:
        holder = Key(resource)
        waiter = Key(resource)
        await store.save(holder)

        with pytest.raises(LockConflictedError):
            await store.save(waiter)

        waiting = asyncio.create_task(store.wait_and_save(waiter))
        await asyncio.sleep(_SETTLE)
        assert not waiting.done()

        await store.delete(holder)
        await asyncio.wait_for(waiting, timeout=5)

        assert await store.exists(waiter)
        assert not await store.exists(holder)
        await store.delete(waiter)

    async def test_a_cancelled_wait_holds_nothing_once_the_lock_frees(
        self,
        store: BlockingStoreInterface,
        resource: str,
    ) -> None:
        holder = Key(resource)
        waiter = Key(resource)
        await store.save(holder)

        waiting = asyncio.create_task(store.wait_and_save(waiter))
        await asyncio.sleep(_SETTLE)
        _ = waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

        assert not await store.exists(waiter)
        await store.delete(holder)

        latecomer = Key(resource)
        await asyncio.wait_for(_save_eventually(store, latecomer), timeout=5)
        assert await store.exists(latecomer)
        await store.delete(latecomer)


class SharedLockStoreTests:
    """Readers sharing a lock, and moving between reading and writing."""

    async def test_shared_lock_read_first(
        self,
        store: SharedLockStoreInterface,
        resource: str,
    ) -> None:
        key1, key2, key3 = Key(resource), Key(resource), Key(resource)

        await store.save_read(key1)
        assert await store.exists(key1)
        assert not await store.exists(key2)
        assert not await store.exists(key3)

        # Several readers at once.
        await store.save_read(key2)
        assert await store.exists(key1)
        assert await store.exists(key2)
        assert not await store.exists(key3)

        with pytest.raises(LockConflictedError):
            await store.save(key3)

        # The failed attempt must not disturb the locks already held.
        assert await store.exists(key1)
        assert await store.exists(key2)
        assert not await store.exists(key3)

        await store.delete(key1)
        assert not await store.exists(key1)
        assert await store.exists(key2)
        assert not await store.exists(key3)

        await store.delete(key2)
        assert not await store.exists(key1)
        assert not await store.exists(key2)
        assert not await store.exists(key3)

        await store.save(key3)
        assert not await store.exists(key1)
        assert not await store.exists(key2)
        assert await store.exists(key3)

        await store.delete(key3)
        assert not await store.exists(key3)

    async def test_shared_lock_write_first(
        self,
        store: SharedLockStoreInterface,
        resource: str,
    ) -> None:
        key1, key2 = Key(resource), Key(resource)

        await store.save(key1)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        with pytest.raises(LockConflictedError):
            await store.save_read(key2)

        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.delete(key1)
        assert not await store.exists(key1)
        assert not await store.exists(key2)

        await store.save(key2)
        assert not await store.exists(key1)
        assert await store.exists(key2)

        await store.delete(key2)
        assert not await store.exists(key2)

    async def test_shared_lock_release_read_first_write_second_read_third(
        self,
        store: SharedLockStoreInterface,
        resource: str,
    ) -> None:
        key1, key2 = Key(resource), Key(resource)

        await store.save_read(key1)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.delete(key1)
        assert not await store.exists(key1)
        assert not await store.exists(key2)

        await store.save(key1)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        with pytest.raises(LockConflictedError):
            await store.save_read(key2)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.delete(key1)
        assert not await store.exists(key1)
        assert not await store.exists(key2)

    async def test_shared_lock_promote(
        self,
        store: SharedLockStoreInterface,
        resource: str,
    ) -> None:
        key1, key2 = Key(resource), Key(resource)

        await store.save_read(key1)
        await store.save_read(key2)
        assert await store.exists(key1)
        assert await store.exists(key2)

        with pytest.raises(LockConflictedError):
            await store.save(key1)

        await store.delete(key1)
        await store.delete(key2)

    async def test_shared_lock_promote_allowed(
        self,
        store: SharedLockStoreInterface,
        resource: str,
    ) -> None:
        key1, key2 = Key(resource), Key(resource)

        await store.save_read(key1)
        await store.save(key1)

        with pytest.raises(LockConflictedError):
            await store.save_read(key2)
        assert await store.exists(key1)
        assert not await store.exists(key2)

        await store.delete(key1)
        await store.save_read(key2)
        assert not await store.exists(key1)
        assert await store.exists(key2)

        await store.delete(key2)

    async def test_shared_lock_demote(
        self,
        store: SharedLockStoreInterface,
        resource: str,
    ) -> None:
        key1, key2 = Key(resource), Key(resource)

        await store.save(key1)
        await store.save_read(key1)
        await store.save_read(key2)

        assert await store.exists(key1)
        assert await store.exists(key2)

        await store.delete(key1)
        await store.delete(key2)


class UnserializableKeyTests:
    """A key holding what only this process can use refuses to be pickled."""

    async def test_unserializable_key(
        self,
        store: PersistingStoreInterface,
        resource: str,
    ) -> None:
        key = Key(resource)

        await store.save(key)
        assert await store.exists(key)

        with pytest.raises(UnserializableKeyError):
            _ = pickle.dumps(key)

        await store.delete(key)


async def _save_eventually(store: PersistingStoreInterface, key: Key) -> None:
    """Save ``key`` as soon as nothing else holds the lock."""
    while True:
        try:
            await store.save(key)
        except LockConflictedError:
            await asyncio.sleep(0.01)
        else:
            return
