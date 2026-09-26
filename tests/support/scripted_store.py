"""Stores that answer from a script and record every call, one per store capability.

A lock picks its strategy from which interfaces its store satisfies, so each
capability combination is its own class: the plain store, one that can
wait, one that can share, and one that can wait to share.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Callable

    from xtr_lock import Key

__all__ = [
    "Outcome",
    "ScriptedBlockingSharedStore",
    "ScriptedBlockingStore",
    "ScriptedSharedStore",
    "ScriptedStore",
]

Outcome: TypeAlias = "BaseException | bool | Callable[[Key], object] | None"
"""What a scripted call does: raise, return a value, or run against the key."""


class ScriptedStore:
    """Plays back scripted outcomes per method; with none left, succeeds.

    ``calls`` records ``(method, resource, *arguments)`` in order.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self._outcomes: defaultdict[str, list[Outcome]] = defaultdict(list)

    def script(self, method: str, *outcomes: Outcome) -> None:
        """Queue ``outcomes`` for the next calls to ``method``."""
        self._outcomes[method].extend(outcomes)

    def called(self, method: str) -> list[tuple[object, ...]]:
        """Return the arguments of every call to ``method``."""
        return [call[1:] for call in self.calls if call[0] == method]

    async def save(self, key: Key) -> None:
        _ = self._play("save", key)

    async def delete(self, key: Key) -> None:
        _ = self._play("delete", key)

    async def exists(self, key: Key) -> bool:
        return bool(self._play("exists", key, default=False))

    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        _ = self._play("put_off_expiration", key, ttl)

    def _play(self, method: str, key: Key, *arguments: object, default: object = None) -> object:
        self.calls.append((method, str(key), *arguments))
        queued = self._outcomes[method]
        if not queued:
            return default

        outcome = queued.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return outcome(key)

        return outcome


class ScriptedBlockingStore(ScriptedStore):
    """A scripted store that can wait."""

    async def wait_and_save(self, key: Key) -> None:
        _ = self._play("wait_and_save", key)


class ScriptedSharedStore(ScriptedStore):
    """A scripted store that can share."""

    async def save_read(self, key: Key) -> None:
        _ = self._play("save_read", key)


class ScriptedBlockingSharedStore(ScriptedSharedStore):
    """A scripted store that can wait to share, but not wait to write."""

    async def wait_and_save_read(self, key: Key) -> None:
        _ = self._play("wait_and_save_read", key)
