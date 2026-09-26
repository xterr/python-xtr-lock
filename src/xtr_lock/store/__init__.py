"""Where locks are kept: in memory, in files, on a Redis server, nowhere, or in several at once."""

from __future__ import annotations

from .combined_store import CombinedStore
from .expiring_store_mixin import ExpiringStoreMixin
from .flock_store import FlockStore
from .in_memory_store import InMemoryStore
from .null_store import NullStore
from .redis_connection import (
    REDIS_SCHEMES,
    create_redis_client,
    is_redis_client,
    is_redis_dsn,
    redis_installed,
)
from .redis_store import RedisStore
from .store_factory import StoreFactory

__all__ = [
    "REDIS_SCHEMES",
    "CombinedStore",
    "ExpiringStoreMixin",
    "FlockStore",
    "InMemoryStore",
    "NullStore",
    "RedisStore",
    "StoreFactory",
    "create_redis_client",
    "is_redis_client",
    "is_redis_dsn",
    "redis_installed",
]
