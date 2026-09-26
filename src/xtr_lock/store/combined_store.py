"""A store that holds each lock in several stores, and counts it held when enough agree."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, final, runtime_checkable

from typing_extensions import override
from xtr_clock import MonotonicClock
from xtr_logging_contracts import EXCEPTION_KEY, LoggerAware

from xtr_lock.exception import InvalidArgumentError, LockConflictedError
from xtr_lock.persisting_store_interface import PersistingStoreInterface
from xtr_lock.shared_lock_store_interface import SharedLockStoreInterface

from .expiring_store_mixin import ExpiringStoreMixin

if TYPE_CHECKING:
    from collections.abc import Iterable

    from xtr_clock import ClockInterface

    from xtr_lock.key import Key
    from xtr_lock.strategy import StrategyInterface

__all__ = ["CombinedStore"]


@runtime_checkable
class _Closable(Protocol):
    """A store holding something to close, such as a connection it opened."""

    async def aclose(self) -> None: ...


@final
class CombinedStore(LoggerAware, SharedLockStoreInterface, ExpiringStoreMixin):
    """Holds each lock in every one of several stores, and lets a strategy decide.

    With independent servers and a
    :class:`~xtr_lock.strategy.ConsensusStrategy`, a lock survives any
    minority of them failing; with a
    :class:`~xtr_lock.strategy.UnanimousStrategy`, it is held only where all
    of them hold it. The stores are asked in order, and asking stops as soon
    as the strategy can no longer be met. A lock that falls short is taken
    back out of every store before the conflict is reported.

    A lifetime is a deadline, not a duration handed to each store: each store
    gets what is left of it when its turn comes, so the lock never outlives
    the moment it was meant to end.

    Reading falls back to writing on any store that cannot share.

    :meth:`aclose` closes every store that has something to close, such as a
    Redis store that opened its own connection.
    """

    _stores: tuple[PersistingStoreInterface, ...]
    _strategy: StrategyInterface
    _clock: ClockInterface

    def __init__(
        self,
        stores: Iterable[PersistingStoreInterface],
        strategy: StrategyInterface,
        *,
        clock: ClockInterface | None = None,
    ) -> None:
        """Keep every lock in each of ``stores``.

        Args:
            stores: The stores to keep each lock in, asked in this order.
            strategy: How many of them must agree.
            clock: What the lifetime deadline is measured on. ``None``
                counts on a monotonic clock.

        Raises:
            InvalidArgumentError: When something in ``stores`` is not a store.
        """
        self._stores = tuple(stores)
        for store in self._stores:
            if not isinstance(store, PersistingStoreInterface):  # pyright: ignore[reportUnnecessaryIsInstance] -- the annotation is not enforced at runtime; a caller may pass anything
                raise InvalidArgumentError(
                    f'The store must implement "PersistingStoreInterface". '
                    f'Got "{type(store).__qualname__}".',
                )
        self._strategy = strategy
        self._clock = clock if clock is not None else MonotonicClock("UTC")

    @override
    async def save(self, key: Key) -> None:
        """Take the lock for writing in every store, until the strategy is met or cannot be."""
        success_count = 0
        failure_count = 0
        stores_count = len(self._stores)

        for store in self._stores:
            try:
                await store.save(key)
                success_count += 1
            except Exception as error:  # noqa: BLE001 — a store failing for any reason is a vote against, and is logged.
                self.logger.debug(
                    'One store failed to save the "{resource}" lock.',
                    {"resource": str(key), "store": store, EXCEPTION_KEY: error},
                )
                failure_count += 1

            if not self._strategy.can_be_met(failure_count, stores_count):
                break

        await self._settle(key, success_count, failure_count)

    @override
    async def save_read(self, key: Key) -> None:
        """Take the lock for reading in every store, for writing where a store cannot share."""
        success_count = 0
        failure_count = 0
        stores_count = len(self._stores)

        for store in self._stores:
            try:
                if isinstance(store, SharedLockStoreInterface):
                    await store.save_read(key)
                else:
                    await store.save(key)
                success_count += 1
            except Exception as error:  # noqa: BLE001 — a store failing for any reason is a vote against, and is logged.
                self.logger.debug(
                    'One store failed to save the "{resource}" lock.',
                    {"resource": str(key), "store": store, EXCEPTION_KEY: error},
                )
                failure_count += 1

            if not self._strategy.can_be_met(failure_count, stores_count):
                break

        await self._settle(key, success_count, failure_count)

    @override
    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        """Extend the lock in every store, each up to the same deadline ``ttl`` seconds away."""
        success_count = 0
        failure_count = 0
        stores_count = len(self._stores)
        expire_at = self._now() + ttl

        for store in self._stores:
            try:
                adjusted_ttl = expire_at - self._now()
                if adjusted_ttl <= 0.0:
                    self.logger.debug(
                        'Stores took too long to put off the expiration of the "{resource}" lock.',
                        {"resource": str(key), "store": store, "ttl": ttl},
                    )
                    key.reduce_lifetime(0)
                    break

                await store.put_off_expiration(key, adjusted_ttl)
                success_count += 1
            except Exception as error:  # noqa: BLE001 — a store failing for any reason is a vote against, and is logged.
                self.logger.debug(
                    'One store failed to put off the expiration of the "{resource}" lock.',
                    {"resource": str(key), "store": store, EXCEPTION_KEY: error},
                )
                failure_count += 1

            if not self._strategy.can_be_met(failure_count, stores_count):
                break

        await self._check_not_expired(key)

        if self._strategy.is_met(success_count, stores_count):
            return

        self.logger.notice(
            'Failed to define the expiration for the "{resource}" lock. Quorum has not been met.',
            {"resource": str(key), "success": success_count, "failure": failure_count},
        )

        # Take back whatever the stores that succeeded now hold.
        await self.delete(key)

        raise LockConflictedError(str(key))

    @override
    async def delete(self, key: Key) -> None:
        """Let go of the lock in every store, whichever of them fail."""
        for store in self._stores:
            try:
                await store.delete(key)
            except Exception as error:  # noqa: BLE001 — every store must be asked; a failure is logged.
                self.logger.notice(
                    'One store failed to delete the "{resource}" lock.',
                    {"resource": str(key), "store": store, EXCEPTION_KEY: error},
                )

    @override
    async def exists(self, key: Key) -> bool:
        """Ask the stores in turn, until the strategy is met or cannot be."""
        success_count = 0
        failure_count = 0
        stores_count = len(self._stores)

        for store in self._stores:
            try:
                if await store.exists(key):
                    success_count += 1
                else:
                    failure_count += 1
            except Exception as error:  # noqa: BLE001 — a store failing for any reason is a vote against, and is logged.
                self.logger.debug(
                    'One store failed to check the "{resource}" lock.',
                    {"resource": str(key), "store": store, EXCEPTION_KEY: error},
                )
                failure_count += 1

            if self._strategy.is_met(success_count, stores_count):
                return True
            if not self._strategy.can_be_met(failure_count, stores_count):
                return False

        return False

    async def aclose(self) -> None:
        """Close every store that has something to close, and leave the rest alone.

        Raises:
            ExceptionGroup: What the stores that failed to close raised, once
                every store has been asked.
        """
        errors: list[Exception] = []
        for store in self._stores:
            if not isinstance(store, _Closable):
                continue
            try:
                await store.aclose()
            except Exception as error:  # noqa: BLE001 — every store is closed; the failures are raised together below.
                errors.append(error)

        if errors:
            raise ExceptionGroup("some of the combined stores failed to close", errors)

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({list(self._stores)!r}, {self._strategy!r})"

    async def _settle(self, key: Key, success_count: int, failure_count: int) -> None:
        """Refuse an expired lock, then keep the lock or take it back out of every store."""
        await self._check_not_expired(key)

        if self._strategy.is_met(success_count, len(self._stores)):
            return

        self.logger.info(
            'Failed to store the "{resource}" lock. Quorum has not been met.',
            {"resource": str(key), "success": success_count, "failure": failure_count},
        )

        # Take back whatever the stores that succeeded now hold.
        await self.delete(key)

        raise LockConflictedError(str(key))

    def _now(self) -> float:
        return self._clock.now().timestamp()
