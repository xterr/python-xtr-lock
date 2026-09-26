"""A resource whose DSN no store serves, and carries a password."""

from __future__ import annotations

from xtr_dependency_injection import configure

from xtr_lock.bundle import LockConfig


@configure
def lock() -> LockConfig:
    return LockConfig(resources={"default": "flock", "reports": "mysql://app:secret@db/app"})
