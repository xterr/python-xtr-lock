"""Configuration for :class:`~xtr_lock.bundle.lock_bundle.LockBundle`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias, cast

from xtr_lock.exception import InvalidArgumentError

from .connection_reference import ConnectionReference

__all__ = ["DEFAULT_RESOURCE", "LockConfig", "StoreEntry"]

DEFAULT_RESOURCE = "default"
"""The resource whose factory is provided without a qualifier."""

StoreEntry: TypeAlias = str | ConnectionReference
"""One store: a DSN or keyword :class:`~xtr_lock.store.StoreFactory` reads, or a connection."""


def _default_resources() -> dict[str, StoreEntry | Sequence[StoreEntry]]:
    return {DEFAULT_RESOURCE: "flock"}


@dataclass(frozen=True, slots=True)
class LockConfig:
    """Which lock resources exist, and which stores keep each one's locks.

    Every resource becomes a :class:`~xtr_lock.lock_factory.LockFactory`
    qualified by its name, the one named ``"default"`` also without a
    qualifier. A resource with several stores keeps each lock in all of them
    and counts it held once a majority agree.

    A store is one of:

    - ``"flock"`` — files in a directory of the system's temporary directory
      set aside for this project;
    - any DSN :meth:`~xtr_lock.store.StoreFactory.create_store` reads —
      ``"flock:///var/lock/app"``, ``"in-memory"``, ``"null"``,
      ``"redis://host:6379"`` and the like — including ``env(...)``;
    - a :class:`ConnectionReference` to a client the container provides.

    ```python
    LockConfig(
        resources={
            "default": "flock",
            "invoices": ["redis://a:6379", "redis://b:6379", "redis://c:6379"],
        }
    )
    ```

    Attributes:
        resources: Each resource's store, or stores. An empty mapping means
            the default; a resource given no store at all is skipped.
    """

    resources: Mapping[str, StoreEntry | Sequence[StoreEntry]] = field(
        default_factory=_default_resources,
    )

    def __post_init__(self) -> None:
        """Refuse a resource that is not named, or a store that is neither a string nor a reference.

        Raises:
            InvalidArgumentError: When the configuration cannot be read.
        """
        for name, entries in self.resources.items():
            if not isinstance(name, str) or not name:  # pyright: ignore[reportUnnecessaryIsInstance] -- configs are written by hand; the annotation is not enforced
                raise InvalidArgumentError(f"a lock resource needs a non-empty name, got {name!r}")
            for entry in _entries(entries):
                if not isinstance(entry, (str, ConnectionReference)):  # pyright: ignore[reportUnnecessaryIsInstance] -- as above
                    raise InvalidArgumentError(
                        f'A lock store must be a string or a ConnectionReference, got "{entry!r}" '
                        f'for the "{name}" resource.',
                    )

    def stores_by_resource(self) -> dict[str, tuple[StoreEntry, ...]]:
        """Return each resource's stores as a tuple; the default resource when none is set."""
        resources = self.resources or _default_resources()

        return {name: _entries(entries) for name, entries in resources.items()}


def _entries(entries: StoreEntry | Sequence[StoreEntry]) -> tuple[StoreEntry, ...]:
    # Anything but a list or a tuple is one store, and validation says whether it is one.
    if isinstance(entries, (list, tuple)):
        return tuple(entries)

    return (cast("StoreEntry", entries),)
