"""Configuration for :class:`~xtr_lock.bundle.lock_bundle.LockBundle`."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeAlias

from xtr_dependency_injection import Reference, one_or_many

from xtr_lock.exception import InvalidArgumentError

__all__ = ["DEFAULT_RESOURCE", "LockConfig", "StoreEntry"]

DEFAULT_RESOURCE = "default"
"""The resource whose factory is provided without a qualifier."""

StoreEntry: TypeAlias = str | Reference
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

    - ``"flock"`` — files in ``lock`` under the kernel's ``share_dir``, a
      directory of the system's temporary one set aside for this project;
    - any DSN :meth:`~xtr_lock.store.StoreFactory.create_store` reads —
      ``"flock:///var/lock/app"``, ``"in-memory"``, ``"null"``,
      ``"redis://host:6379"`` and the like — including ``env(...)``;
    - a :class:`Reference` to a client the container provides.

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
            for entry in one_or_many(entries):
                if not isinstance(entry, (str, Reference)):  # pyright: ignore[reportUnnecessaryIsInstance] -- as above
                    raise InvalidArgumentError(
                        f'A lock store must be a string or a Reference, got "{entry!r}" '
                        f'for the "{name}" resource.',
                    )

    def stores_by_resource(self) -> dict[str, tuple[StoreEntry, ...]]:
        """Return each resource's stores as a tuple; the default resource when none is set."""
        resources = self.resources or _default_resources()

        return {name: one_or_many(entries) for name, entries in resources.items()}
