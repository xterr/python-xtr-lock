"""The application's root bundles: only LockBundle, in every environment."""

from __future__ import annotations

from xtr_lock.bundle import LockBundle

BUNDLES = {LockBundle: {"all": True}}
