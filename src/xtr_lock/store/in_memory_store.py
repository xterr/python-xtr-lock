"""A store that keeps locks in this process's memory."""

from __future__ import annotations

import base64
import secrets
from typing import TYPE_CHECKING, final

from typing_extensions import override

from xtr_lock.exception import LockConflictedError
from xtr_lock.shared_lock_store_interface import SharedLockStoreInterface

if TYPE_CHECKING:
    from xtr_lock.key import Key

__all__ = ["InMemoryStore"]


@final
class InMemoryStore(SharedLockStoreInterface):
    """Keeps locks in a dictionary, for coordinating tasks inside one process.

    A holder is told apart by a random token the store stashes on its key the
    first time it sees it. Nothing ever expires here: a lock is held until it
    is released, whatever lifetime it was given.

    Every method completes without awaiting anything, so on one event loop
    no two calls interleave. The store is not meant to be shared between
    threads.
    """

    __slots__ = ("_locks", "_read_locks")

    _locks: dict[str, str]
    _read_locks: dict[str, set[str]]

    def __init__(self) -> None:
        """Start with no locks."""
        self._locks = {}
        self._read_locks = {}

    @override
    async def save(self, key: Key) -> None:
        """Take the lock for writing; the only reader may promote itself."""
        resource = str(key)
        token = _unique_token(key)

        holder = self._locks.get(resource)
        if holder is not None:
            if holder == token:
                return

            raise LockConflictedError(resource)

        readers = self._read_locks.get(resource)
        if readers is not None and token in readers and len(readers) == 1:
            del self._read_locks[resource]
            self._locks[resource] = token
            return

        if readers:
            raise LockConflictedError(resource)

        self._locks[resource] = token

    @override
    async def save_read(self, key: Key) -> None:
        """Take the lock for reading; the writer may demote itself."""
        resource = str(key)
        token = _unique_token(key)

        readers = self._read_locks.get(resource)
        if readers is not None:
            readers.add(token)
            return

        holder = self._locks.get(resource)
        if holder is not None:
            if holder != token:
                raise LockConflictedError(resource)

            del self._locks[resource]

        self._read_locks[resource] = {token}

    @override
    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        """Do nothing: a lock in memory is held until it is released."""

    @override
    async def delete(self, key: Key) -> None:
        """Let go of whatever ``key`` holds, for reading or writing."""
        resource = str(key)
        token = _unique_token(key)

        readers = self._read_locks.get(resource)
        if readers is not None:
            readers.discard(token)
            if not readers:
                del self._read_locks[resource]

        if self._locks.get(resource) == token:
            del self._locks[resource]

    @override
    async def exists(self, key: Key) -> bool:
        """Tell whether ``key`` holds the lock, for reading or writing."""
        resource = str(key)
        token = _unique_token(key)

        return token in self._read_locks.get(resource, ()) or self._locks.get(resource) == token

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def _unique_token(key: Key) -> str:
    """Return the token that identifies ``key`` as a holder, making one the first time."""
    if not key.has_state(InMemoryStore):
        key.set_state(InMemoryStore, base64.b64encode(secrets.token_bytes(32)).decode("ascii"))

    return str(key.get_state(InMemoryStore))
