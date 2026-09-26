"""Redis clients from DSNs: the schemes read, and the client made, for every package needing one.

Lock stores and cache pools reach Redis the same way, so the DSN rules live
here once: ``redis://`` and ``rediss://``, a ``unix://`` socket, and
``valkey://`` / ``valkeys://`` read as the first two. A client is made to
connect on first use, so building one never touches the network.
"""

from __future__ import annotations

import importlib.util
import sys
from typing import TYPE_CHECKING, Final, TypeGuard

from xtr_lock.exception import InvalidArgumentError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from redis.asyncio import Redis

__all__ = [
    "REDIS_SCHEMES",
    "create_redis_client",
    "is_redis_client",
    "is_redis_dsn",
    "redis_installed",
]

REDIS_SCHEMES: Final[Mapping[str, str]] = {
    "redis": "redis",
    "rediss": "rediss",
    "valkey": "redis",
    "valkeys": "rediss",
    "unix": "unix",
}
"""Each accepted scheme, and the one the client is given for it."""


def is_redis_dsn(dsn: str) -> bool:
    """Tell whether ``dsn`` has one of :data:`REDIS_SCHEMES`, in any case."""
    scheme, separator, _ = dsn.partition(":")
    return bool(separator) and scheme.lower() in REDIS_SCHEMES


def redis_installed() -> bool:
    """Tell whether the Redis client library can be imported, without importing it."""
    return importlib.util.find_spec("redis") is not None


def create_redis_client(dsn: str, *, missing: str) -> Redis:
    """Return an asyncio client for ``dsn`` that connects on first use.

    Args:
        dsn: A DSN with one of :data:`REDIS_SCHEMES`.
        missing: What to say when the client library is not installed — which
            extra of which package to install.

    Raises:
        InvalidArgumentError: When the scheme is not a Redis one — naming the
            scheme only, never credentials — or the client library is not
            installed, with ``missing`` as its reason.
    """
    scheme, separator, rest = dsn.partition(":")
    target = REDIS_SCHEMES.get(scheme.lower()) if separator else None
    if target is None:
        raise InvalidArgumentError(
            f'"{scheme}" is not a Redis scheme; expected one of {", ".join(REDIS_SCHEMES)}.',
        )

    try:
        from redis.asyncio import Redis  # noqa: PLC0415 — the redis extra is optional.
    except ImportError as error:
        raise InvalidArgumentError(missing) from error

    # Only the keyword arguments are untyped, and none are passed.
    return Redis.from_url(f"{target}:{rest}")  # pyright: ignore[reportUnknownMemberType]


def is_redis_client(connection: object) -> TypeGuard[Redis]:
    """Tell whether ``connection`` is an asyncio Redis client, without importing the library."""
    # Without the client library imported, nothing can be one of its clients.
    if "redis.asyncio" not in sys.modules:
        return False

    from redis.asyncio import Redis as Client  # noqa: PLC0415 — the redis extra is optional.

    return isinstance(connection, Client)
