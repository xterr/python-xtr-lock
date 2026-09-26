"""One resource per kind of store the bundle can build."""

from __future__ import annotations

from xtr_dependency_injection import configure, env

from xtr_lock.bundle import LockConfig


@configure
def lock() -> LockConfig:
    return LockConfig(
        resources={
            "default": "flock",
            "memory": "in-memory",
            "quorum": ["in-memory", "in-memory", "in-memory"],
            "off": "null",
            "from_env": env("LOCK_TEST_DSN"),
            "redis": env("LOCK_TEST_REDIS_DSN"),
            "skipped": [],
        },
    )
