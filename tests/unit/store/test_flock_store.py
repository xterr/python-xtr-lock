from __future__ import annotations

import asyncio
import base64
import errno
import gc
import hashlib
import os
import stat
import tempfile
from typing import TYPE_CHECKING, Self, cast, final

import pytest
from xtr_clock import MockClock

from tests.support.store_conformance import (
    AbstractStoreTests,
    BlockingSharedLockStoreTests,
    BlockingStoreTests,
    SharedLockStoreTests,
    UnserializableKeyTests,
)
from xtr_lock import (
    BlockingSharedLockStoreInterface,
    BlockingStoreInterface,
    FlockStore,
    InvalidArgumentError,
    Key,
    LockConflictedError,
    LockStorageError,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import tzinfo
    from pathlib import Path

    from xtr_clock import DatePoint

pytestmark = pytest.mark.anyio

_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False


class TestFlockStore(
    AbstractStoreTests,
    BlockingStoreTests,
    BlockingSharedLockStoreTests,
    SharedLockStoreTests,
    UnserializableKeyTests,
):
    @pytest.fixture
    def store(self, tmp_path: Path) -> FlockStore:
        return FlockStore(tmp_path)


def _digest(resource: str) -> str:
    encoded = base64.b64encode(hashlib.sha256(resource.encode()).digest()).decode()

    return encoded[:7].replace("/", "_")


@pytest.mark.skipif(_ROOT, reason="a superuser can create any directory")
def test_construct_when_repository_cannot_be_created(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    _ = blocker.write_text("")

    with pytest.raises(InvalidArgumentError, match="does not exist and cannot be created"):
        _ = FlockStore(blocker / "a" / "b")


@pytest.mark.skipif(_ROOT, reason="a superuser can write anywhere")
def test_construct_when_repository_is_not_writable(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        with pytest.raises(InvalidArgumentError, match="is not writable"):
            _ = FlockStore(locked)
    finally:
        locked.chmod(stat.S_IRWXU)


def test_construct_with_subdir(tmp_path: Path) -> None:
    directory = tmp_path / "a" / "b"

    store = FlockStore(directory)

    assert directory.is_dir()
    assert store.lock_path == directory


def test_it_defaults_to_a_directory_of_this_user_alone_in_the_temporary_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    path = FlockStore().lock_path

    assert path.parent == tmp_path
    assert stat.S_IMODE(path.stat().st_mode) == 0o700


@pytest.mark.skipif(not hasattr(os, "getuid"), reason="file ownership is POSIX")
def test_a_default_directory_of_another_user_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    _ = FlockStore()
    monkeypatch.setattr(os, "getuid", lambda: tmp_path.stat().st_uid + 1)
    (tmp_path / f"xtr-lock-{tmp_path.stat().st_uid + 1}").mkdir()
    (tmp_path / f"xtr-lock-{tmp_path.stat().st_uid + 1}").chmod(0o700)

    with pytest.raises(InvalidArgumentError, match="not a directory of this user"):
        _ = FlockStore()


async def test_a_lock_file_replaced_by_a_symbolic_link_is_not_followed(tmp_path: Path) -> None:
    store = FlockStore(tmp_path / "locks")
    key = Key("invoice")
    await store.save(key)
    await store.delete(key)
    (lock_file,) = (tmp_path / "locks").iterdir()
    target = tmp_path / "elsewhere"
    _ = target.write_text("untouched", encoding="utf-8")
    lock_file.unlink()
    lock_file.symlink_to(target)

    with pytest.raises(LockStorageError):
        await store.save(Key("invoice"))

    assert target.read_text(encoding="utf-8") == "untouched"


async def test_save_sanitize_name(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    resource = '<?py echo "% hello word ! %" ?>'
    key = Key(resource)

    await store.save(key)

    assert (tmp_path / f"xtr.-py-echo-hello-word-.{_digest(resource)}.lock").is_file()
    await store.delete(key)


async def test_save_sanitize_long_name(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    resource = "tests.unit.store.FlockStore" * 100
    key = Key(resource)

    await store.save(key)

    expected = f"xtr.{resource[:50]}.{_digest(resource)}.lock"
    assert (tmp_path / expected).is_file()
    await store.delete(key)


async def test_non_ascii_letters_are_folded_even_when_they_case_fold_to_ascii(
    tmp_path: Path,
) -> None:
    store = FlockStore(tmp_path)
    resource = "\u212aelvin-\u0131"  # KELVIN SIGN and DOTLESS I case-fold to ASCII letters

    assert store.file_for(Key(resource)).name == f"xtr.-elvin--.{_digest(resource)}.lock"


async def test_the_lock_file_is_open_to_other_users(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    key = Key("shared")
    previous = os.umask(0o077)
    try:
        await store.save(key)
    finally:
        _ = os.umask(previous)

    assert stat.S_IMODE(store.file_for(key).stat().st_mode) == 0o666
    await store.delete(key)


async def test_a_file_opened_read_only_still_locks(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    key = Key("read-only")
    path = store.file_for(key)
    path.touch()
    path.chmod(stat.S_IRUSR)
    try:
        await store.save(key)
        assert await store.exists(key)
        await store.delete(key)
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


async def test_a_lock_file_that_cannot_be_opened_is_a_storage_error(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    key = Key("dir")
    store.file_for(key).mkdir()

    with pytest.raises(LockStorageError, match="cannot open lock file"):
        await store.save(key)

    assert not await store.exists(key)


async def test_a_failed_promotion_holds_nothing(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    reader1, reader2 = Key("r"), Key("r")
    await store.save_read(reader1)
    await store.save_read(reader2)

    with pytest.raises(LockConflictedError):
        await store.save(reader1)

    assert not await store.exists(reader1)
    await store.delete(reader2)
    await store.save(Key("r"))


async def test_delete_closes_the_descriptor(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    key = Key("r")
    await store.save(key)
    _, descriptor, _ = cast("tuple[bool, int, object]", key.get_state(store))

    await store.delete(key)

    with pytest.raises(OSError, match="Bad file descriptor"):
        _ = os.fstat(descriptor)


def test_it_waits_natively_for_both_modes(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)

    assert isinstance(store, BlockingStoreInterface)
    assert isinstance(store, BlockingSharedLockStoreInterface)


async def test_a_reader_waiting_to_write_gets_the_lock_once_the_other_reader_leaves(
    tmp_path: Path,
) -> None:
    store = FlockStore(tmp_path)
    reader1, reader2 = Key("r"), Key("r")
    await store.save_read(reader1)
    await store.save_read(reader2)

    promoting = asyncio.create_task(store.wait_and_save(reader1))
    await asyncio.sleep(0.05)
    assert not promoting.done()
    await store.delete(reader2)
    await asyncio.wait_for(promoting, timeout=5)

    with pytest.raises(LockConflictedError):
        await store.save_read(Key("r"))
    await store.delete(reader1)


async def test_a_cancelled_wait_closes_its_descriptor(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    holder, waiter = Key("r"), Key("r")
    await store.save(holder)
    opened: list[int] = []
    real_open = os.open

    def recording_open(path: str | os.PathLike[str], flags: int, mode: int = 0o777) -> int:
        descriptor = real_open(path, flags, mode)
        opened.append(descriptor)
        return descriptor

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(os, "open", recording_open)
        waiting = asyncio.create_task(store.wait_and_save(waiter))
        await asyncio.sleep(0.05)
        _ = waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting

    assert not await store.exists(waiter)
    assert len(opened) == 1
    with pytest.raises(OSError, match="Bad file descriptor"):
        _ = os.fstat(opened[0])
    await store.delete(holder)


@pytest.mark.parametrize("blocking", [False, True])
async def test_a_lock_the_system_refuses_is_a_storage_error(
    tmp_path: Path,
    blocking: bool,
) -> None:
    import fcntl  # noqa: PLC0415 — POSIX only, like the store.

    store = FlockStore(tmp_path)
    key = Key("r")

    def refuse(descriptor: int, operation: int) -> None:
        del descriptor, operation
        raise OSError(errno.ENOLCK, "No locks available")

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(fcntl, "flock", refuse)
        with pytest.raises(LockStorageError, match="No locks available"):
            await (store.wait_and_save(key) if blocking else store.save(key))

    assert not await store.exists(key)


@final
class _RecordingClock:
    """Records every wait, frees the lock after the eighth, and never really sleeps."""

    def __init__(self, on_eighth: Callable[[], Awaitable[None]]) -> None:
        self.slept: list[float] = []
        self._frozen = MockClock("2026-01-01 00:00:00")
        self._on_eighth = on_eighth

    def now(self) -> DatePoint:
        return self._frozen.now()

    def sleep(self, seconds: float) -> None:
        self._frozen.sleep(seconds)

    async def sleep_async(self, seconds: float) -> None:
        self.slept.append(seconds)
        if len(self.slept) == 8:
            await self._on_eighth()
        await self._frozen.sleep_async(seconds)

    def with_timezone(self, timezone: str | tzinfo) -> Self:
        del timezone  # the zone changes nothing this clock records
        return self


async def test_waiting_backs_off_to_a_tenth_of_a_second(tmp_path: Path) -> None:
    holder, waiter = Key("r"), Key("r")
    releasing = FlockStore(tmp_path)
    await releasing.save(holder)
    clock = _RecordingClock(lambda: releasing.delete(holder))
    store = FlockStore(tmp_path, clock=clock)

    await asyncio.wait_for(store.wait_and_save(waiter), timeout=5)

    assert len(clock.slept) == 8
    for slept, base in zip(clock.slept, [0.01, 0.02, 0.04, 0.08, 0.1, 0.1], strict=False):
        assert base <= slept <= base * 1.1
    await store.delete(waiter)


async def test_two_stores_on_two_directories_are_two_locks(tmp_path: Path) -> None:
    first, second = FlockStore(tmp_path / "a"), FlockStore(tmp_path / "b")
    key = Key("r")

    await first.save(key)
    await second.save(key)

    assert await first.exists(key)
    assert await second.exists(key)
    with pytest.raises(LockConflictedError):
        await second.save(Key("r"))
    await first.delete(key)
    assert await second.exists(key)
    await second.delete(key)


async def test_a_key_collected_while_holding_lets_go_of_the_lock(tmp_path: Path) -> None:
    store = FlockStore(tmp_path)
    await store.save(Key("r"))
    _ = gc.collect()

    await store.save(Key("r"))


async def test_putting_off_the_expiration_of_a_lock_not_held_is_a_conflict(
    tmp_path: Path,
) -> None:
    with pytest.raises(LockConflictedError):
        await FlockStore(tmp_path).put_off_expiration(Key("r"), 10)
