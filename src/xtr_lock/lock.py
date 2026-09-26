"""The lock: one key, one store, and the rules for taking, extending and letting go."""

from __future__ import annotations

import asyncio
import secrets
from contextlib import suppress
from typing import TYPE_CHECKING, Final, NoReturn, Self, final
from weakref import WeakKeyDictionary

from typing_extensions import override
from xtr_clock import Clock
from xtr_logging_contracts import EXCEPTION_KEY, LoggerAware

from .blocking_shared_lock_store_interface import BlockingSharedLockStoreInterface
from .blocking_store_interface import BlockingStoreInterface
from .exception import (
    InvalidArgumentError,
    LockAcquiringError,
    LockConflictedError,
    LockExpiredError,
    LockReleasingError,
)
from .shared_lock_interface import SharedLockInterface
from .shared_lock_store_interface import SharedLockStoreInterface

if TYPE_CHECKING:
    from types import TracebackType

    from xtr_clock import ClockInterface

    from .key import Key
    from .persisting_store_interface import PersistingStoreInterface

__all__ = ["Lock"]

_RETRY_DELAY_MS: Final = 100
_RETRY_JITTER_MS: Final = 10


@final
class _Holder:
    """What every lock acting for one key shares: whose turn it is, and whether it holds."""

    __slots__ = ("dirty", "turn")

    def __init__(self) -> None:
        self.turn = asyncio.Lock()
        self.dirty = False


_HOLDERS: Final[WeakKeyDictionary[Key, _Holder]] = WeakKeyDictionary()


def _holder_for(key: Key) -> _Holder:
    holder = _HOLDERS.get(key)
    if holder is None:
        holder = _HOLDERS[key] = _Holder()

    return holder


@final
class Lock(LoggerAware, SharedLockInterface):
    """Takes, extends and lets go of the lock a :class:`~xtr_lock.key.Key` names, in a store.

    Build one through :class:`~xtr_lock.lock_factory.LockFactory` rather than
    by hand, so the store, the clock and the logger come from one place.

    Asked to wait, a lock uses the store's own way of waiting when it has
    one, and otherwise retries every tenth of a second, give or take ten
    milliseconds so that two waiters do not retry in step.

    Given a lifetime, a lock sets it the moment it is taken, and a lock whose
    lifetime ran out while it was being stored is let go again and reported
    rather than returned as held.

    The key is the holder. Every lock made for one key — this one, shared
    between tasks, or another made from the same key — acts for that one
    holder: acquiring what the holder already holds succeeds at once, and
    one release lets go for all of them. What they do to the store takes
    turns, so two tasks never interleave half-done operations on one holder.
    To exclude another task, give it a lock of its own.

    An acquire that is cancelled — by a timeout, say — takes back whatever
    the store may have stored for it, unless the holder already held the
    lock before it started.

    ``async with lock:`` waits for the lock and lets it go on the way out;
    a lock is never let go just because it is no longer referenced.

    A lock cannot be pickled: it holds a store, and possibly an open file,
    that mean nothing anywhere else.
    """

    _key: Key
    _store: PersistingStoreInterface
    _ttl: float | None
    _clock: ClockInterface
    _holder: _Holder

    def __init__(
        self,
        key: Key,
        store: PersistingStoreInterface,
        ttl: float | None = None,
        *,
        clock: ClockInterface | None = None,
    ) -> None:
        """Lock the resource ``key`` names, in ``store``.

        Args:
            key: The holder's identity. Reuse it to act as the same holder.
            store: Where the lock is kept.
            ttl: The longest the lock is expected to be held, in seconds;
                ``None`` or zero sets no lifetime.
            clock: What a retrying wait sleeps on. ``None`` sleeps on the
                clock in force.
        """
        self._key = key
        self._store = store
        self._ttl = ttl
        self._clock = clock if clock is not None else Clock()
        self._holder = _holder_for(key)

    @override
    async def acquire(self, blocking: bool = False) -> bool:
        """Take the lock for writing; see :meth:`LockInterface.acquire`."""
        async with self._holder.turn:
            return await self._take(blocking, None)

    @override
    async def acquire_read(self, blocking: bool = False) -> bool:
        """Take the lock for reading; see :meth:`SharedLockInterface.acquire_read`."""
        async with self._holder.turn:
            store = self._store
            if isinstance(store, SharedLockStoreInterface):
                return await self._take(blocking, store)

            self._key.reset_lifetime()
            self.logger.debug(
                "Store does not support read locks, falling back to a write lock.",
                self._context(),
            )

            return await self._take(blocking, None)

    @override
    async def refresh(self, ttl: float | None = None) -> None:
        """Push the expiry back; see :meth:`LockInterface.refresh`."""
        async with self._holder.turn:
            await self._refresh(ttl)

    @override
    async def is_acquired(self) -> bool:
        """Ask the store, and remember the answer; see :meth:`LockInterface.is_acquired`."""
        async with self._holder.turn:
            return await self._is_acquired()

    @override
    async def release(self) -> None:
        """Let the lock go, and check it is gone; see :meth:`LockInterface.release`."""
        async with self._holder.turn:
            await self._release()

    @override
    def is_expired(self) -> bool:
        """Tell whether the lifetime ran out; see :meth:`LockInterface.is_expired`."""
        return self._key.is_expired()

    @override
    def get_remaining_lifetime(self) -> float | None:
        """Return the seconds left; see :meth:`LockInterface.get_remaining_lifetime`."""
        return self._key.get_remaining_lifetime()

    @override
    async def __aenter__(self) -> Self:
        """Wait for the lock, and hold it for the ``async with`` block."""
        _ = await self.acquire(blocking=True)

        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Let the lock go, when the holder took it and the store says it still holds it."""
        async with self._holder.turn:
            if not self._holder.dirty or not await self._is_acquired():
                return

            await self._release()

    @override
    def __reduce__(self) -> NoReturn:
        """Refuse to be pickled: a lock holds a store that means nothing anywhere else."""
        raise TypeError(f"cannot pickle {type(self).__name__} objects")

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self._key)!r}, {self._store!r})"

    async def _take(self, blocking: bool, shared: SharedLockStoreInterface | None) -> bool:
        """Take the lock for writing, or for reading when ``shared`` is the store to read from."""
        key = self._key
        key.reset_lifetime()
        held_before = self._holder.dirty
        try:
            if shared is None:
                await (self._wait_and_save() if blocking else self._store.save(key))
                self._holder.dirty = True
                self.logger.debug('Successfully acquired the "{resource}" lock.', self._context())
            else:
                await (self._wait_and_save_read(shared) if blocking else shared.save_read(key))
                self._holder.dirty = True
                self.logger.debug(
                    'Successfully acquired the "{resource}" lock for reading.',
                    self._context(),
                )

            await self._settle()
        except asyncio.CancelledError:
            if not held_before:
                await self._abandon()
            raise
        except LockConflictedError:
            self._holder.dirty = False
            self.logger.info(
                'Failed to acquire the "{resource}" lock. Someone else already acquired the lock.',
                self._context(),
            )
            if blocking:
                raise

            return False
        except Exception as error:
            self.logger.notice(
                'Failed to acquire the "{resource}" lock.',
                self._context(error),
            )
            raise LockAcquiringError(str(self._key), "failed to acquire the lock") from error

        return True

    async def _refresh(self, ttl: float | None) -> None:
        if ttl is None:
            ttl = self._ttl
        if not ttl:
            raise InvalidArgumentError("You have to define an expiration duration.")

        try:
            self._key.reset_lifetime()
            await self._store.put_off_expiration(self._key, ttl)
            self._holder.dirty = True

            await self._fail_if_expired()

            self.logger.debug(
                'Expiration defined for "{resource}" lock for "{ttl}" seconds.',
                {**self._context(), "ttl": ttl},
            )
        except LockConflictedError:
            self._holder.dirty = False
            self.logger.notice(
                'Failed to define an expiration for the "{resource}" lock, '
                "someone else acquired the lock.",
                self._context(),
            )
            raise
        except Exception as error:
            self.logger.notice(
                'Failed to define an expiration for the "{resource}" lock.',
                self._context(error),
            )
            raise LockAcquiringError(
                str(self._key),
                "failed to define an expiration",
            ) from error

    async def _is_acquired(self) -> bool:
        self._holder.dirty = await self._store.exists(self._key)

        return self._holder.dirty

    async def _release(self) -> None:
        try:
            await self._delete()
            await self._fail_if_still_held()
        except LockReleasingError:
            self.logger.notice('Failed to release the "{resource}" lock.', self._context())
            raise

        self.logger.debug('Successfully released the "{resource}" lock.', self._context())

    async def _wait_and_save(self) -> None:
        store = self._store
        if isinstance(store, BlockingStoreInterface):
            await store.wait_and_save(self._key)
            return

        while True:
            try:
                await store.save(self._key)
            except LockConflictedError:
                await self._clock.sleep_async(_retry_delay())
            else:
                return

    async def _wait_and_save_read(self, store: SharedLockStoreInterface) -> None:
        if isinstance(store, BlockingSharedLockStoreInterface):
            await store.wait_and_save_read(self._key)
            return

        while True:
            try:
                await store.save_read(self._key)
            except LockConflictedError:
                await self._clock.sleep_async(_retry_delay())
            else:
                return

    async def _delete(self) -> None:
        try:
            await self._store.delete(self._key)
        except LockReleasingError:
            raise
        except Exception as error:
            raise LockReleasingError(str(self._key), "failed to release the lock") from error

        self._holder.dirty = False

    async def _fail_if_still_held(self) -> None:
        """Refuse to trust a delete: a store may have acknowledged one that never landed."""
        if await self._store.exists(self._key):
            raise LockReleasingError(
                str(self._key),
                "failed to release the lock, the resource is still locked",
            )

    async def _settle(self) -> None:
        """Set the lifetime the lock was made with, then refuse a lock already expired."""
        if self._ttl:
            await self._refresh(None)

        await self._fail_if_expired()

    async def _fail_if_expired(self) -> None:
        if not self._key.is_expired():
            return

        # Letting go may fail too; the expiry is what the caller needs to hear about.
        with suppress(Exception):
            await self._release()

        raise LockExpiredError(str(self._key))

    async def _abandon(self) -> None:
        """Take back what a cancelled acquire may have stored, whatever else is cancelled.

        The store may have kept the lock before the cancellation arrived, and
        nobody would ever release it. Deleting a lock that was never stored is
        harmless: a store only ever lets go of what this holder holds.
        """
        self._holder.dirty = False
        with suppress(Exception):
            await asyncio.shield(self._store.delete(self._key))

    def _context(self, error: Exception | None = None) -> dict[str, object]:
        context: dict[str, object] = {"resource": str(self._key)}
        if error is not None:
            context[EXCEPTION_KEY] = error

        return context


def _retry_delay() -> float:
    """Return a tenth of a second, give or take ten milliseconds."""
    jitter = secrets.randbelow(2 * _RETRY_JITTER_MS + 1) - _RETRY_JITTER_MS

    return (_RETRY_DELAY_MS + jitter) / 1000
