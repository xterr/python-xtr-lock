"""Makes locks that share one store, one clock and one logger."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from typing_extensions import override
from xtr_logging_contracts import LoggerAware

from .key import Key
from .lock import Lock

if TYPE_CHECKING:
    from xtr_clock import ClockInterface

    from .persisting_store_interface import PersistingStoreInterface
    from .shared_lock_interface import SharedLockInterface

__all__ = ["DEFAULT_TTL", "LockFactory"]

DEFAULT_TTL: Final = 300.0
"""Five minutes: how long a lock is expected to be held unless told otherwise."""


class LockFactory(LoggerAware):
    """Makes :class:`~xtr_lock.lock.Lock` objects on one store.

    The one object an application usually needs: build it once around a
    store, then ask it for a lock per resource. Every lock it makes logs
    through the logger it was given with :meth:`set_logger`.

    ```python
    factory = LockFactory(FlockStore())

    async with factory.create_lock("invoice-42"):
        ...
    ```
    """

    _store: PersistingStoreInterface
    _clock: ClockInterface | None

    def __init__(
        self,
        store: PersistingStoreInterface,
        *,
        clock: ClockInterface | None = None,
    ) -> None:
        """Make locks kept in ``store``.

        Args:
            store: Where every lock this factory makes is kept.
            clock: What lifetimes are measured and waits sleep on. ``None``
                reads the clock in force.
        """
        self._store = store
        self._clock = clock

    def create_lock(self, resource: str, ttl: float | None = DEFAULT_TTL) -> SharedLockInterface:
        """Make a lock on ``resource``, as a new holder.

        Args:
            resource: What the lock protects.
            ttl: The longest the lock is expected to be held, in seconds.
                ``None`` sets no lifetime, so a store whose locks expire
                keeps its own default.
        """
        return self.create_lock_from_key(Key(resource, clock=self._clock), ttl)

    def create_lock_from_key(
        self, key: Key, ttl: float | None = DEFAULT_TTL
    ) -> SharedLockInterface:
        """Make a lock for ``key``, as the holder that key already is.

        Args:
            key: The holder to act as, typically one kept from an earlier
                lock.
            ttl: The longest the lock is expected to be held, in seconds.
        """
        lock = Lock(key, self._store, ttl, clock=self._clock)
        lock.set_logger(self.logger)

        return lock

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._store!r})"
