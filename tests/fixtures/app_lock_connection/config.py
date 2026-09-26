"""Locks kept on a Redis client the application registers itself."""

from __future__ import annotations

from redis.asyncio import Redis
from xtr_dependency_injection import Reference, configure

from xtr_lock.bundle import LockConfig

from .services import LOCKS


@configure
def lock() -> LockConfig:
    return LockConfig(resources={"default": Reference(Redis, LOCKS)})
