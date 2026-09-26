"""The xtr-lock bundle: a lock factory per configured resource.

An application listing :class:`LockBundle` gets a
:class:`~xtr_lock.lock_factory.LockFactory` for every resource in its
:class:`LockConfig`, qualified by the resource's name, and the ``"default"``
one without a qualifier. Each resource's store is a
:class:`~xtr_lock.persisting_store_interface.PersistingStoreInterface`
qualified the same way. When the logging bundle is active, a ``"lock"``
channel is added to it and every lock logs there.

Nothing is opened until a factory is first asked for: no directory created,
no server reached. Boot checks the configuration without opening anything —
every DSN names a store, every referenced connection is registered — so a
mistake fails the application at startup rather than at its first lock. A
connection the bundle opened from a DSN is closed when the container is.
"""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import final

from typing_extensions import override
from xtr_dependency_injection import (
    Bundle,
    ContainerBuilder,
    ServiceConfigurator,
    as_bundle,
    bundle_active,
    required_bundle,
)
from xtr_logging_contracts import LoggerInterface
from xtr_service_contracts import ContainerInterface

from xtr_lock.exception import InvalidArgumentError
from xtr_lock.lock_factory import LockFactory
from xtr_lock.persisting_store_interface import PersistingStoreInterface
from xtr_lock.store.combined_store import CombinedStore
from xtr_lock.store.flock_store import FlockStore
from xtr_lock.store.redis_store import RedisStore
from xtr_lock.store.store_factory import StoreFactory
from xtr_lock.strategy.consensus_strategy import ConsensusStrategy

from .connection_reference import ConnectionReference
from .lock_config import DEFAULT_RESOURCE, LockConfig, StoreEntry

__all__ = ["LockBundle"]

LOCK_CHANNEL = "lock"
"""The logging channel locks write to."""

_FLOCK = "flock"


def _add_lock_channel(config: object) -> object:
    """Add the ``"lock"`` channel to the logging config, unless it is there already.

    Only ever called with the logging bundle active, so its package — and
    the struct library its config is built on — can be imported here.
    """
    import msgspec  # noqa: PLC0415 — see above.
    from xtr_logging.bundle import LoggingConfig  # noqa: PLC0415 — see above.

    if not isinstance(config, LoggingConfig) or LOCK_CHANNEL in config.channels:
        return config

    return msgspec.structs.replace(config, channels=(*config.channels, LOCK_CHANNEL))


@final
@required_bundle("xtr_logging.bundle:LoggingBundle", ignore_on_invalid=True)
@as_bundle("lock", config=LockConfig)
class LockBundle(Bundle[LockConfig]):
    """Turns a :class:`LockConfig` into a store and a lock factory per resource."""

    @override
    def prepend_extension(self, builder: ContainerBuilder) -> None:
        """When ``logging`` is active, add the ``lock`` channel to its config."""
        if bundle_active(builder, "logging"):
            builder.prepend_extension_config("logging", _add_lock_channel)

    @override
    def load_extension(
        self,
        config: LockConfig,
        services: ServiceConfigurator,
        builder: ContainerBuilder,
    ) -> None:
        """Register a store and a lock factory under each resource's name."""
        del builder
        for resource, stores in config.stores_by_resource().items():
            if not stores:
                continue

            _ = services.set(_store_factory(resource), qualifier=resource).set_argument(
                "stores",
                stores,
            )
            _ = services.set(_lock_factory_factory(resource), qualifier=resource)
            if resource == DEFAULT_RESOURCE:
                services.alias(LockFactory, LockFactory, target_qualifier=resource)

    @override
    async def boot(self) -> None:
        """Refuse a store no DSN serves, or a connection nobody registered, before any lock.

        The configuration is read resolved, so a DSN given as ``env(...)`` is
        read here, and a variable that is not set fails the boot.

        Raises:
            InvalidArgumentError: Naming the resource whose store is wrong.
        """
        container = self.container
        if container is None:  # pragma: no cover — the kernel sets this before boot.
            message = "LockBundle.boot ran without a container"
            raise RuntimeError(message)

        config = await container.get(LockConfig)
        for resource, stores in config.stores_by_resource().items():
            for entry in stores:
                _check_store(resource, entry, container)


def _check_store(resource: str, entry: StoreEntry, container: ContainerInterface) -> None:
    if isinstance(entry, ConnectionReference):
        if not container.has(entry.service, entry.qualifier):
            qualifier = "" if entry.qualifier is None else f"[{entry.qualifier!r}]"
            raise InvalidArgumentError(
                f'The "{resource}" lock resource uses {entry.service.__qualname__}{qualifier}, '
                f"which the container does not provide.",
            )
        return

    if entry == _FLOCK:
        return

    try:
        StoreFactory.validate(entry)
    except InvalidArgumentError as error:
        raise InvalidArgumentError(f'The "{resource}" lock resource: {error.reason}') from error


def _store_factory(
    resource: str,
) -> Callable[
    [tuple[StoreEntry, ...], ContainerInterface], AsyncIterator[PersistingStoreInterface]
]:
    """Build the factory of ``resource``'s store, closing what it opened when the container closes.

    One function per resource, so each carries its own name in the
    container's report.
    """

    async def store(
        stores: tuple[StoreEntry, ...],
        container: ContainerInterface,
    ) -> AsyncIterator[PersistingStoreInterface]:
        built = [await _build_store(entry, container) for entry in stores]
        try:
            if len(built) == 1:
                yield built[0]
            else:
                combined = CombinedStore(built, ConsensusStrategy())
                logger = await _lock_logger(container)
                if logger is not None:
                    combined.set_logger(logger)
                yield combined
        finally:
            for opened in built:
                if isinstance(opened, RedisStore):
                    await opened.aclose()

    store.__name__ = f"lock_store_{resource}"
    store.__qualname__ = store.__name__

    return store


def _lock_factory_factory(resource: str) -> Callable[[ContainerInterface], object]:
    """Build the factory of ``resource``'s :class:`LockFactory`."""

    async def lock_factory(container: ContainerInterface) -> LockFactory:
        factory = LockFactory(await container.get(PersistingStoreInterface, resource))
        logger = await _lock_logger(container)
        if logger is not None:
            factory.set_logger(logger)

        return factory

    lock_factory.__name__ = f"lock_factory_{resource}"
    lock_factory.__qualname__ = lock_factory.__name__

    return lock_factory


async def _build_store(
    entry: StoreEntry, container: ContainerInterface
) -> PersistingStoreInterface:
    """Build one store: the project's own lock directory, a DSN, or a referenced connection."""
    if isinstance(entry, ConnectionReference):
        connection = await container.get(entry.service, entry.qualifier)

        return StoreFactory.create_store(connection)

    if entry == _FLOCK:
        return FlockStore(_project_lock_path(container))

    return StoreFactory.create_store(entry)


def _project_lock_path(container: ContainerInterface) -> Path:
    """Return a directory under the temporary one that is this project's alone.

    Two projects on one machine would otherwise share lock files for every
    resource they happen to name alike.
    """
    project_dir = (
        str(container.get_parameter("kernel.project_dir"))
        if container.has_parameter("kernel.project_dir")
        else ""
    )
    digest = hashlib.sha256(project_dir.encode()).hexdigest()[:16]

    return Path(tempfile.gettempdir()) / "xtr-lock" / digest


async def _lock_logger(container: ContainerInterface) -> LoggerInterface | None:
    if not container.has(LoggerInterface, LOCK_CHANNEL):
        return None

    return await container.get(LoggerInterface, LOCK_CHANNEL)
