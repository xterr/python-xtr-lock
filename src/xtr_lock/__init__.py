"""Exclusive and shared locks around resources, in whatever store fits.

A :class:`~xtr_lock.lock_factory.LockFactory` built around a store hands out
:class:`~xtr_lock.lock.Lock` objects, one per resource. The store decides
who else a lock excludes: tasks in this process
(:class:`~xtr_lock.store.InMemoryStore`), processes on this machine
(:class:`~xtr_lock.store.FlockStore`), anything that reaches a Redis server
(:class:`~xtr_lock.store.RedisStore`), or a quorum of several stores
(:class:`~xtr_lock.store.CombinedStore`).

```python
factory = LockFactory(FlockStore())

async with factory.create_lock("reports:nightly"):
    ...
```

Every call that touches a store is awaited.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

from .blocking_shared_lock_store_interface import BlockingSharedLockStoreInterface
from .blocking_store_interface import BlockingStoreInterface
from .exception import (
    InvalidArgumentError,
    InvalidTtlError,
    LockAcquiringError,
    LockConflictedError,
    LockError,
    LockExpiredError,
    LockReleasingError,
    LockStorageError,
    UnserializableKeyError,
)
from .key import Key
from .lock import Lock
from .lock_factory import DEFAULT_TTL, LockFactory
from .lock_interface import LockInterface
from .no_lock import NoLock
from .persisting_store_interface import PersistingStoreInterface
from .shared_lock_interface import SharedLockInterface
from .shared_lock_store_interface import SharedLockStoreInterface
from .store import (
    CombinedStore,
    ExpiringStoreMixin,
    FlockStore,
    InMemoryStore,
    NullStore,
    RedisStore,
    StoreFactory,
)
from .strategy import ConsensusStrategy, StrategyInterface, UnanimousStrategy

try:
    __version__ = version("xtr-lock")
except PackageNotFoundError:  # pragma: no cover
    # Running from a source tree or a vendored copy, with no installed
    # metadata to read. Having no version is better than refusing to import.
    __version__ = "0+unknown"

__all__ = [
    "DEFAULT_TTL",
    "BlockingSharedLockStoreInterface",
    "BlockingStoreInterface",
    "CombinedStore",
    "ConsensusStrategy",
    "ExpiringStoreMixin",
    "FlockStore",
    "InMemoryStore",
    "InvalidArgumentError",
    "InvalidTtlError",
    "Key",
    "Lock",
    "LockAcquiringError",
    "LockConflictedError",
    "LockError",
    "LockExpiredError",
    "LockFactory",
    "LockInterface",
    "LockReleasingError",
    "LockStorageError",
    "NoLock",
    "NullStore",
    "PersistingStoreInterface",
    "RedisStore",
    "SharedLockInterface",
    "SharedLockStoreInterface",
    "StoreFactory",
    "StrategyInterface",
    "UnanimousStrategy",
    "UnserializableKeyError",
    "__version__",
]
