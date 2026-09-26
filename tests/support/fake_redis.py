"""A Redis client that runs no Lua: it answers scripts from a callback, and says NOSCRIPT first."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, cast, final

from redis.exceptions import NoScriptError

if TYPE_CHECKING:
    from collections.abc import Callable

    from redis.asyncio import Redis

__all__ = ["FakeRedis"]


@final
class FakeRedis:
    """Loads scripts by digest and answers ``evalsha`` through ``reply(script, keys_and_args)``.

    Like a server just started, it knows no script until one is loaded.
    ``evaluated`` records ``(script, keys_and_args)`` for every call that ran.
    """

    def __init__(self, reply: Callable[[str, tuple[object, ...]], object]) -> None:
        self._reply = reply
        self.scripts: dict[str, str] = {}
        self.evaluated: list[tuple[str, tuple[object, ...]]] = []
        self.no_script_errors = 0
        self.closed = False

    def as_client(self) -> Redis:
        """Return this fake typed as the client a store takes."""
        return cast("Redis", cast("object", self))

    async def evalsha(self, sha: str, numkeys: int, *keys_and_args: object) -> object:
        assert numkeys == 1
        script = self.scripts.get(sha)
        if script is None:
            self.no_script_errors += 1
            raise NoScriptError("NOSCRIPT No matching script. Please use EVAL.")

        self.evaluated.append((script, keys_and_args))
        return self._reply(script, keys_and_args)

    async def script_load(self, script: str) -> str:
        digest = hashlib.sha1(script.encode(), usedforsecurity=False).hexdigest()
        self.scripts[digest] = script
        return digest

    async def aclose(self) -> None:
        self.closed = True

    def runs(self, fragment: str) -> list[tuple[object, ...]]:
        """Return the arguments of every evaluated script containing ``fragment``."""
        return [arguments for script, arguments in self.evaluated if fragment in script]
