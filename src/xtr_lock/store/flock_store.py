"""A store that locks files, so processes on one machine can share a lock."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import os
import re
import secrets
import sys
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast, final

from typing_extensions import override
from xtr_clock import Clock

from xtr_lock.blocking_shared_lock_store_interface import BlockingSharedLockStoreInterface
from xtr_lock.blocking_store_interface import BlockingStoreInterface
from xtr_lock.exception import InvalidArgumentError, LockConflictedError, LockStorageError

if sys.platform != "win32":
    import fcntl

if TYPE_CHECKING:
    from xtr_clock import ClockInterface

    from xtr_lock.key import Key

__all__ = ["FlockStore"]

_UNSAFE_CHARACTERS: Final = re.compile(r"[^A-Za-z0-9._-]+")
_NAME_LENGTH: Final = 50
_DIGEST_LENGTH: Final = 7
_FILE_MODE: Final = 0o666
_HAS_FILE_LOCKS: Final = importlib.util.find_spec("fcntl") is not None
_FIRST_RETRY: Final = 0.01
_LAST_RETRY: Final = 0.1
_RETRY_JITTER_PERCENT: Final = 10


@final
class FlockStore(BlockingStoreInterface, BlockingSharedLockStoreInterface):
    """Holds each lock as an advisory lock on a file of its own.

    Every resource maps to one file under the lock directory, and every key
    opens its own descriptor on it, so two keys conflict whether they live in
    two processes or in the same one. The operating system lets go of the
    lock when the descriptor is closed — on :meth:`delete`, or when the
    process ends, however it ends — so a crashed holder never leaves a lock
    behind. Nothing else expires: a lifetime given to the lock is ignored.

    Waiting for a lock tries again without blocking, sooner at first and
    then every tenth of a second, sleeping on the event loop in between: no
    thread is ever parked in the system call, and a wait that is cancelled
    holds nothing. Waiters are not served in the order they arrived — the
    operating system does not promise that either.

    The locks are advisory and local: they bind only processes that use this
    store on the same machine, and a directory on a network file system may
    not honour them at all. POSIX only.
    """

    __slots__ = ("_clock", "_lock_path")

    _lock_path: Path
    _clock: ClockInterface

    def __init__(
        self,
        lock_path: str | os.PathLike[str] | None = None,
        *,
        clock: ClockInterface | None = None,
    ) -> None:
        """Keep lock files in ``lock_path``, created when missing.

        Args:
            lock_path: The directory for the lock files. ``None`` uses the
                system's temporary directory.
            clock: What a wait sleeps on between attempts. ``None`` sleeps
                on the clock in force.

        Raises:
            InvalidArgumentError: When the directory cannot be created or
                written to, or the platform has no file locks.
        """
        if not _HAS_FILE_LOCKS:  # pragma: no cover — the suite runs on POSIX.
            raise InvalidArgumentError("file locks are not available on Windows")

        path = Path(lock_path) if lock_path is not None else Path(tempfile.gettempdir())
        if not path.is_dir():
            with suppress(OSError):
                path.mkdir(mode=0o777, parents=True, exist_ok=True)
            if not path.is_dir():
                raise InvalidArgumentError(
                    f'The FlockStore directory "{path}" does not exist and cannot be created.',
                )
        elif not os.access(path, os.W_OK):
            raise InvalidArgumentError(f'The FlockStore directory "{path}" is not writable.')

        self._lock_path = path
        self._clock = clock if clock is not None else Clock()

    @property
    def lock_path(self) -> Path:
        """The directory the lock files live in."""
        return self._lock_path

    @override
    async def save(self, key: Key) -> None:
        """Take the lock for writing, without waiting."""
        await self._lock(key, read=False, blocking=False)

    @override
    async def save_read(self, key: Key) -> None:
        """Take the lock for reading, without waiting."""
        await self._lock(key, read=True, blocking=False)

    @override
    async def wait_and_save(self, key: Key) -> None:
        """Wait for the lock, then take it for writing."""
        await self._lock(key, read=False, blocking=True)

    @override
    async def wait_and_save_read(self, key: Key) -> None:
        """Wait until no writer holds the lock, then take it for reading."""
        await self._lock(key, read=True, blocking=True)

    @override
    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        """Do nothing: a file lock is held until it is released."""

    @override
    async def delete(self, key: Key) -> None:
        """Let go of the lock and close the descriptor; a key holding nothing is fine."""
        if not key.has_state(FlockStore):
            return

        _, descriptor = _held(key)
        try:
            # Closing lets go on its own; unlocking first only says so sooner.
            with suppress(OSError):
                fcntl.flock(descriptor, fcntl.LOCK_UN | fcntl.LOCK_NB)
            os.close(descriptor)
        finally:
            key.remove_state(FlockStore)

    @override
    async def exists(self, key: Key) -> bool:
        """Tell whether ``key`` holds a descriptor with the lock on it."""
        return key.has_state(FlockStore)

    def file_for(self, key: Key) -> Path:
        """Return the file that holds the lock for ``key``'s resource.

        The name keeps up to fifty characters of the resource, anything
        outside ``A-Za-z0-9._-`` folded to ``-``, and adds a short digest so
        two resources that fold alike still get two files.
        """
        resource = str(key)
        readable = _UNSAFE_CHARACTERS.sub("-", resource)[:_NAME_LENGTH]
        digest = base64.b64encode(hashlib.sha256(resource.encode()).digest()).decode("ascii")

        return self._lock_path / f"xtr.{readable}.{digest[:_DIGEST_LENGTH].replace('/', '_')}.lock"

    async def _lock(self, key: Key, *, read: bool, blocking: bool) -> None:
        descriptor: int | None = None
        if key.has_state(FlockStore):
            held_for_reading, descriptor = _held(key)
            if held_for_reading == read:
                return

        if descriptor is None:
            descriptor = _open(self.file_for(key))

        operation = fcntl.LOCK_SH if read else fcntl.LOCK_EX
        try:
            if blocking:
                await self._wait(descriptor, operation)
            else:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except asyncio.CancelledError:
            _close(descriptor)
            key.remove_state(FlockStore)
            raise
        except BlockingIOError:
            # Switching between reading and writing is not atomic: the lock
            # held before may already be gone, so nothing is kept.
            _close(descriptor)
            key.remove_state(FlockStore)
            raise LockConflictedError(str(key)) from None
        except OSError as error:
            _close(descriptor)
            key.remove_state(FlockStore)
            raise LockStorageError(f"cannot lock {self.file_for(key)}: {error}") from error

        key.set_state(FlockStore, (read, descriptor))
        key.mark_unserializable()

    async def _wait(self, descriptor: int, operation: int) -> None:
        """Try until the lock is taken, backing off from a hundredth to a tenth of a second.

        A failed attempt to switch between reading and writing may already
        have let go of the lock held before; the next attempt takes it anew,
        as a blocking switch would.
        """
        delay = _FIRST_RETRY
        while True:
            try:
                fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
            except BlockingIOError:
                jitter = 1 + secrets.randbelow(_RETRY_JITTER_PERCENT + 1) / 100
                await self._clock.sleep_async(delay * jitter)
                delay = min(delay * 2, _LAST_RETRY)
            else:
                return

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({str(self._lock_path)!r})"


def _held(key: Key) -> tuple[bool, int]:
    """Return how ``key`` holds its lock — for reading or not — and on which descriptor."""
    return cast("tuple[bool, int]", key.get_state(FlockStore))


def _open(path: Path) -> int:
    """Open the lock file, creating it readable and writable by everyone when missing.

    A file another user created may be open to us for reading only, which is
    all a lock needs.

    Raises:
        LockStorageError: When the file cannot be opened or created.
    """
    try:
        try:
            return _open_existing(path)
        except FileNotFoundError:
            pass

        try:
            descriptor = os.open(
                path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, _FILE_MODE
            )
        except FileExistsError:
            # Created by someone else between the two calls.
            return _open_existing(path)

        # The mode given to open() is narrowed by the umask; other users must
        # be able to lock this file too.
        with suppress(OSError):
            os.fchmod(descriptor, _FILE_MODE)
    except OSError as error:
        raise LockStorageError(f"cannot open lock file {path}: {error}") from error

    return descriptor


def _open_existing(path: Path) -> int:
    try:
        return os.open(path, os.O_RDWR | os.O_CLOEXEC)
    except PermissionError:
        return os.open(path, os.O_RDONLY | os.O_CLOEXEC)


def _close(descriptor: int) -> None:
    with suppress(OSError):
        os.close(descriptor)
