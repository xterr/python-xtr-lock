"""The xtr-dependency-injection bundle for xtr-lock."""

from __future__ import annotations

from .connection_reference import ConnectionReference
from .lock_bundle import LOCK_CHANNEL, LockBundle
from .lock_config import DEFAULT_RESOURCE, LockConfig, StoreEntry

__all__ = [
    "DEFAULT_RESOURCE",
    "LOCK_CHANNEL",
    "ConnectionReference",
    "LockBundle",
    "LockConfig",
    "StoreEntry",
]
