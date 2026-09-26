"""A store that keeps locks on a Redis server, so any process that reaches it can share a lock."""

from __future__ import annotations

import base64
import hashlib
import math
import secrets
from typing import TYPE_CHECKING, Final, Protocol, cast, final
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from typing_extensions import override
from xtr_clock import Clock

from xtr_lock.exception import (
    InvalidArgumentError,
    InvalidTtlError,
    LockConflictedError,
    LockStorageError,
)
from xtr_lock.shared_lock_store_interface import SharedLockStoreInterface

from .expiring_store_mixin import ExpiringStoreMixin

if TYPE_CHECKING:
    from collections.abc import Awaitable, Sequence

    from redis.asyncio import Redis
    from xtr_clock import ClockInterface

    from xtr_lock.key import Key

__all__ = ["RedisStore"]

_WRITE_MEMBER: Final = "__write__"
"""The member that marks a write lock; never handed out as a holder's token."""

_TIME_PROBE_KEY: Final = "xtr_lock_check_support_time"

_PREFIX_OPTION: Final = "prefix"

_TIME_REFUSALS: Final = (
    "commands not allowed after non deterministic",
    "is not allowed from script",
)

_SERVER_NOW: Final = """
    local now = redis.call("TIME")
    now = now[1] * 1000 + math.floor(now[2] / 1000)
"""

_CLIENT_NOW: Final = """
    local now = tonumber(ARGV[1])
    now = math.floor(now * 1000)
"""

_TIME_PROBE: Final = """
    local now = redis.call("TIME")
    redis.call("SET", KEYS[1], "1", "PX", 1)

    return 1
"""

_SAVE: Final = """
    local key = KEYS[1]
    local uniqueToken = ARGV[2]
    local ttl = tonumber(ARGV[3])

    -- a plain string under the key is a lock this store does not own
    if redis.call("TYPE", key).ok == "string" then
        return false
    end

    {now}

    -- forget the holders whose lifetime ran out
    redis.call("ZREMRANGEBYSCORE", key, "-inf", now)

    -- already held by this token
    if redis.call("ZSCORE", key, uniqueToken) then
        -- held for reading alongside other readers: no promotion
        if not redis.call("ZSCORE", key, "__write__")
            and redis.call("ZCOUNT", key, "-inf", "+inf") > 1 then
            return false
        end
    elseif redis.call("ZCOUNT", key, "-inf", "+inf") > 0 then
        return false
    end

    redis.call("ZADD", key, now + ttl, uniqueToken)
    redis.call("ZADD", key, now + ttl, "__write__")

    -- keep the key as long as its longest-lived holder
    local maxExpiration = redis.call("ZREVRANGE", key, 0, 0, "WITHSCORES")[2]
    redis.call("PEXPIREAT", key, maxExpiration)

    return true
"""

_SAVE_READ: Final = """
    local key = KEYS[1]
    local uniqueToken = ARGV[2]
    local ttl = tonumber(ARGV[3])

    -- a plain string under the key is a lock this store does not own
    if redis.call("TYPE", key).ok == "string" then
        return false
    end

    {now}

    -- forget the holders whose lifetime ran out
    redis.call("ZREMRANGEBYSCORE", key, "-inf", now)

    -- not held by this token, and someone holds it for writing
    if not redis.call("ZSCORE", key, uniqueToken) and redis.call("ZSCORE", key, "__write__") then
        return false
    end

    redis.call("ZADD", key, now + ttl, uniqueToken)
    redis.call("ZREM", key, "__write__")

    -- keep the key as long as its longest-lived holder
    local maxExpiration = redis.call("ZREVRANGE", key, 0, 0, "WITHSCORES")[2]
    redis.call("PEXPIREAT", key, maxExpiration)

    return true
"""

_PUT_OFF_EXPIRATION: Final = """
    local key = KEYS[1]
    local uniqueToken = ARGV[2]
    local ttl = tonumber(ARGV[3])

    -- a plain string under the key is a lock this store does not own
    if redis.call("TYPE", key).ok == "string" then
        return false
    end

    {now}

    -- not held by this token
    if not redis.call("ZSCORE", key, uniqueToken) then
        return false
    end

    redis.call("ZADD", key, now + ttl, uniqueToken)
    -- held for writing: the write marker lives as long
    if redis.call("ZSCORE", key, "__write__") then
        redis.call("ZADD", key, now + ttl, "__write__")
    end

    -- keep the key as long as its longest-lived holder
    local maxExpiration = redis.call("ZREVRANGE", key, 0, 0, "WITHSCORES")[2]
    redis.call("PEXPIREAT", key, maxExpiration)

    return true
"""

_DELETE: Final = """
    local key = KEYS[1]
    local uniqueToken = ARGV[1]

    -- a plain string under the key is a lock this store does not own
    if redis.call("TYPE", key).ok == "string" then
        return false
    end

    -- not held by this token
    if not redis.call("ZSCORE", key, uniqueToken) then
        return false
    end

    redis.call("ZREM", key, uniqueToken)
    redis.call("ZREM", key, "__write__")

    local maxExpiration = redis.call("ZREVRANGE", key, 0, 0, "WITHSCORES")[2]
    if nil ~= maxExpiration then
        redis.call("PEXPIREAT", key, maxExpiration)
    end

    return true
"""

_EXISTS: Final = """
    local key = KEYS[1]
    local uniqueToken = ARGV[2]

    -- a plain string under the key is a lock this store does not own
    if redis.call("TYPE", key).ok == "string" then
        return false
    end

    {now}

    -- forget the holders whose lifetime ran out
    redis.call("ZREMRANGEBYSCORE", key, "-inf", now)

    if redis.call("ZSCORE", key, uniqueToken) then
        return true
    end

    return false
"""

_SCHEMES: Final = {
    "redis": "redis",
    "rediss": "rediss",
    "valkey": "redis",
    "valkeys": "rediss",
    "unix": "unix",
}


class _ScriptingClient(Protocol):
    """The two calls this store makes, typed as the asyncio client answers them.

    The client's own annotations cover its blocking twin too, so every reply
    is typed as possibly not awaitable.
    """

    def evalsha(
        self, sha: str, numkeys: int, /, *keys_and_args: str | float
    ) -> Awaitable[object]: ...

    def script_load(self, script: str, /) -> Awaitable[str]: ...


@final
class RedisStore(SharedLockStoreInterface, ExpiringStoreMixin):
    """Keeps locks on a Redis server, with a lifetime the server enforces.

    Each resource is a sorted set named after it: one member per holder,
    scored with the moment its hold expires, plus a marker member while the
    holder writes. Every change is one script, so it happens whole on the
    server. The server's own clock decides expiry when scripts may read it;
    otherwise this process's clock is sent along.

    A lock is stored with :attr:`initial_ttl` of life, which the lock's own
    lifetime then replaces. A lock is never held forever: a holder that dies
    loses it when the lifetime runs out.

    The Redis key is the resource, after :attr:`prefix` — set one when the
    database is shared with anything else.

    Works with Valkey too. One server, not a cluster.
    """

    __slots__ = (
        "_clock",
        "_initial_ttl",
        "_owns_connection",
        "_prefix",
        "_redis",
        "_support_time",
    )

    _redis: Redis
    _initial_ttl: float
    _prefix: str
    _clock: ClockInterface
    _support_time: bool | None
    _owns_connection: bool

    def __init__(
        self,
        redis: Redis,
        initial_ttl: float = 300.0,
        *,
        prefix: str = "",
        clock: ClockInterface | None = None,
    ) -> None:
        """Keep locks on the server ``redis`` talks to.

        The client stays the caller's to close.

        Args:
            redis: An asyncio client.
            initial_ttl: How long a lock lives once stored, before the lock's
                own lifetime is set, in seconds.
            prefix: Put in front of every resource to make its Redis key.
            clock: What this process sends as the time, when the server
                cannot read its own. ``None`` reads the clock in force.

        Raises:
            InvalidTtlError: When ``initial_ttl`` is not strictly positive.
        """
        if initial_ttl <= 0:
            raise InvalidTtlError(initial_ttl)

        self._redis = redis
        self._initial_ttl = initial_ttl
        self._prefix = prefix
        self._clock = clock if clock is not None else Clock()
        self._support_time = None
        self._owns_connection = False

    @classmethod
    def from_url(
        cls,
        dsn: str,
        initial_ttl: float = 300.0,
        *,
        clock: ClockInterface | None = None,
    ) -> RedisStore:
        """Connect to the server ``dsn`` names, on first use, and own the connection.

        Close the store with :meth:`aclose` when done.

        Args:
            dsn: ``redis://``, ``rediss://``, ``unix://``, or ``valkey://`` and
                ``valkeys://``, which read as the first two. A ``prefix``
                query option (``redis://host?prefix=app:``) sets
                :attr:`prefix`; every other option goes to the client.
            initial_ttl: See :meth:`__init__`.
            clock: See :meth:`__init__`.

        Raises:
            InvalidArgumentError: When the scheme is not one of those, or the
                ``redis`` extra is not installed.
        """
        _, prefix = _split_prefix(dsn)
        store = cls(cls.create_connection(dsn), initial_ttl, prefix=prefix, clock=clock)
        store._owns_connection = True

        return store

    @staticmethod
    def create_connection(dsn: str) -> Redis:
        """Return an asyncio client for ``dsn`` that connects on first use.

        A ``prefix`` option in the DSN is this store's, not the client's, and
        is left out.

        Raises:
            InvalidArgumentError: When the scheme is not a Redis one, or the
                ``redis`` extra is not installed.
        """
        dsn, _ = _split_prefix(dsn)
        scheme, separator, rest = dsn.partition(":")
        target = _SCHEMES.get(scheme.lower()) if separator else None
        if target is None:
            raise InvalidArgumentError(
                f'"{scheme}" is not a Redis scheme; expected one of {", ".join(_SCHEMES)}.',
            )

        try:
            from redis.asyncio import Redis  # noqa: PLC0415 — the redis extra is optional.
        except ImportError as error:
            raise InvalidArgumentError(
                'A Redis lock store needs the redis client; install "xtr-lock[redis]".',
            ) from error

        # Only the keyword arguments are untyped, and none are passed.
        return Redis.from_url(f"{target}:{rest}")  # pyright: ignore[reportUnknownMemberType]

    @property
    def initial_ttl(self) -> float:
        """How long a lock lives once stored, before the lock's own lifetime is set."""
        return self._initial_ttl

    @property
    def prefix(self) -> str:
        """What is put in front of every resource to make its Redis key."""
        return self._prefix

    async def aclose(self) -> None:
        """Close the connection, when :meth:`from_url` opened it; otherwise do nothing."""
        if self._owns_connection:
            await self._redis.aclose()

    @override
    async def save(self, key: Key) -> None:
        """Take the lock for writing; the only reader may promote itself."""
        key.reduce_lifetime(self._initial_ttl)
        script = _SAVE.replace("{now}", await self._now_code())
        if not await self._evaluate(
            script,
            self._name(key),
            [self._now(), _unique_token(key), _milliseconds(self._initial_ttl)],
        ):
            raise LockConflictedError(str(key))

        await self._check_not_expired(key)

    @override
    async def save_read(self, key: Key) -> None:
        """Take the lock for reading; the writer may demote itself."""
        key.reduce_lifetime(self._initial_ttl)
        script = _SAVE_READ.replace("{now}", await self._now_code())
        if not await self._evaluate(
            script,
            self._name(key),
            [self._now(), _unique_token(key), _milliseconds(self._initial_ttl)],
        ):
            raise LockConflictedError(str(key))

        await self._check_not_expired(key)

    @override
    async def put_off_expiration(self, key: Key, ttl: float) -> None:
        """Keep the lock for another ``ttl`` seconds."""
        key.reduce_lifetime(ttl)
        script = _PUT_OFF_EXPIRATION.replace("{now}", await self._now_code())
        if not await self._evaluate(
            script,
            self._name(key),
            [self._now(), _unique_token(key), _milliseconds(ttl)],
        ):
            raise LockConflictedError(str(key))

        await self._check_not_expired(key)

    @override
    async def delete(self, key: Key) -> None:
        """Let go of whatever ``key`` holds; a key holding nothing is fine."""
        _ = await self._evaluate(_DELETE, self._name(key), [_unique_token(key)])

    @override
    async def exists(self, key: Key) -> bool:
        """Tell whether ``key`` holds the lock, for reading or writing, and has not expired."""
        script = _EXISTS.replace("{now}", await self._now_code())

        return bool(
            await self._evaluate(script, self._name(key), [self._now(), _unique_token(key)]),
        )

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._redis!r}, initial_ttl={self._initial_ttl!r})"

    async def _evaluate(
        self,
        script: str,
        resource: str,
        args: Sequence[str | int | float],
    ) -> object:
        """Run ``script`` by its digest, loading it first when the server does not know it.

        Raises:
            LockStorageError: When the server answers with an error.
        """
        from redis.exceptions import (  # noqa: PLC0415 — the redis extra is optional; a client exists only once it is installed.
            NoScriptError,
            ResponseError,
        )

        client = cast("_ScriptingClient", self._redis)
        digest = hashlib.sha1(script.encode(), usedforsecurity=False).hexdigest()
        try:
            try:
                return await client.evalsha(digest, 1, resource, *args)
            except NoScriptError:
                _ = await client.script_load(script)
                return await client.evalsha(digest, 1, resource, *args)
        except ResponseError as error:
            raise LockStorageError(str(error)) from error

    async def _now_code(self) -> str:
        """Return the script lines that set ``now``, from the server's clock when it can."""
        if self._support_time is None:
            try:
                probe_key = f"{self._prefix}{_TIME_PROBE_KEY}"
                self._support_time = await self._evaluate(_TIME_PROBE, probe_key, []) == 1
            except LockStorageError as error:
                if not any(refusal in error.reason for refusal in _TIME_REFUSALS):
                    raise
                self._support_time = False

        return _SERVER_NOW if self._support_time else _CLIENT_NOW

    def _now(self) -> float:
        return self._clock.now().timestamp()

    def _name(self, key: Key) -> str:
        return f"{self._prefix}{key}"


def _split_prefix(dsn: str) -> tuple[str, str]:
    """Return ``dsn`` without its ``prefix`` option, and that option's value.

    A DSN without the option comes back untouched.
    """
    parts = urlsplit(dsn)
    options = parse_qsl(parts.query, keep_blank_values=True)
    prefixes = [value for name, value in options if name == _PREFIX_OPTION]
    if not prefixes:
        return dsn, ""

    kept = urlencode([(name, value) for name, value in options if name != _PREFIX_OPTION])

    return urlunsplit(parts._replace(query=kept)), prefixes[-1]


def _unique_token(key: Key) -> str:
    """Return the token that identifies ``key`` as a holder, making one the first time.

    The write marker is never a token, whatever a key was given.
    """
    if not key.has_state(RedisStore) or key.get_state(RedisStore) == _WRITE_MEMBER:
        key.set_state(RedisStore, base64.b64encode(secrets.token_bytes(32)).decode("ascii"))

    return str(key.get_state(RedisStore))


def _milliseconds(seconds: float) -> int:
    return math.ceil(seconds * 1000)
