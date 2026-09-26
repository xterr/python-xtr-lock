"""Builds a store from a DSN, a keyword, or a connection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, final

from xtr_lock.exception import InvalidArgumentError

from .flock_store import FlockStore
from .in_memory_store import InMemoryStore
from .null_store import NullStore
from .redis_connection import is_redis_client, is_redis_dsn, redis_installed
from .redis_store import RedisStore

if TYPE_CHECKING:
    from xtr_lock.persisting_store_interface import PersistingStoreInterface

__all__ = ["StoreFactory"]

_FLOCK_PREFIX: Final = "flock://"


@final
class StoreFactory:
    """Turns what a configuration names into a store.

    | Given | Store |
    |---|---|
    | ``"flock"`` | :class:`FlockStore` in the system's temporary directory |
    | ``"flock:///var/lock/app"`` | :class:`FlockStore` in that directory |
    | ``"in-memory"`` | a new :class:`InMemoryStore` |
    | ``"null"`` | :class:`NullStore` |
    | ``"redis://…"``, ``"rediss://…"``, ``"unix://…"`` | :class:`RedisStore` owning a connection |
    | ``"valkey://…"``, ``"valkeys://…"`` | the same, read as ``redis`` / ``rediss`` |
    | an asyncio Redis client | :class:`RedisStore` on that client |
    """

    __slots__ = ()

    @staticmethod
    def create_store(connection: object) -> PersistingStoreInterface:
        """Build the store ``connection`` names.

        Raises:
            InvalidArgumentError: When no store serves ``connection``. The
                message names its scheme or type only, never credentials.
        """
        if is_redis_client(connection):
            return RedisStore(connection)

        if not isinstance(connection, str):
            raise InvalidArgumentError(
                f'Unsupported connection: "{type(connection).__qualname__}".',
            )

        StoreFactory.validate(connection)

        if connection == "flock":
            return FlockStore()
        if connection.startswith(_FLOCK_PREFIX):
            return FlockStore(connection.removeprefix(_FLOCK_PREFIX))
        if is_redis_dsn(connection):
            return RedisStore.from_url(connection)
        if connection == "in-memory":
            return InMemoryStore()

        # The only thing validate() lets through that is not handled above.
        return NullStore()

    @staticmethod
    def validate(connection: str) -> None:
        """Refuse a DSN no store serves, without building a store or connecting to anything.

        Raises:
            InvalidArgumentError: When no store serves ``connection``, or it
                needs an extra that is not installed. The message names its
                scheme only, never credentials.
        """
        if connection in ("flock", "in-memory", "null") or connection.startswith(_FLOCK_PREFIX):
            return

        if is_redis_dsn(connection):
            if not redis_installed():
                raise InvalidArgumentError(RedisStore.MISSING_CLIENT)
            return

        scheme, separator, _ = connection.partition(":")
        described = f"{scheme}:" if separator else connection

        raise InvalidArgumentError(f'Unsupported connection: "{described}".')
