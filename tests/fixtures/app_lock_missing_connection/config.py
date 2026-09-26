"""A resource pointing at a Redis client the application never registers."""

from __future__ import annotations

from redis.asyncio import Redis
from xtr_dependency_injection import configure

from xtr_lock.bundle import ConnectionReference, LockConfig


@configure
def lock() -> LockConfig:
    return LockConfig(resources={"default": ConnectionReference(Redis, "absent")})
