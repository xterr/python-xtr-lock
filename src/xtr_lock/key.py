"""The identity of a lock, and the state its store keeps on it."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast, final

from typing_extensions import override
from xtr_clock import MonotonicClock

from .exception import InvalidArgumentError, UnserializableKeyError

if TYPE_CHECKING:
    from collections.abc import Hashable

    from xtr_clock import ClockInterface

__all__ = ["Key"]

_DEFAULT_CLOCK: Final = MonotonicClock("UTC")
"""Counts forward whatever the wall clock does, so a correction never stretches a lifetime."""


@final
class Key:
    """Names a resource and carries whatever a store needs to remember about holding it.

    Two keys for the same resource are two different holders: a store tells
    them apart by the state it stashes on each — a random token, an open
    file — never by the resource name alone. Reusing the same key is
    therefore how a holder says "this is still me".

    The key also tracks when the lock it stands for expires. Every store that
    sets a lifetime can only shorten it (:meth:`reduce_lifetime`), so a lock
    held in several places lives no longer than the shortest-lived of them.
    A lifetime is a duration, so it is measured on a monotonic clock unless
    another is given: setting the system time back cannot keep a lock alive.
    """

    # A lock keeps what it shares with the other locks of one holder against a
    # weak reference to the key, so the key still goes away with its last user.
    # The interpreter fills __weakref__ itself; there is nothing to initialise.
    __slots__ = (
        "__weakref__",  # pyright: ignore[reportUninitializedInstanceVariable]
        "_clock",
        "_expiring_time",
        "_resource",
        "_serializable",
        "_state",
    )

    _resource: str
    _clock: ClockInterface
    _expiring_time: float | None
    _state: dict[Hashable, object]
    _serializable: bool

    def __init__(self, resource: str, *, clock: ClockInterface | None = None) -> None:
        """Name ``resource``.

        Args:
            resource: What the lock protects. Any string; stores that need a
                narrower alphabet derive one from it.
            clock: Where the lifetime is measured. ``None`` counts on a
                monotonic clock; hand in a frozen one to test expiry.
        """
        self._resource = resource
        self._clock = clock if clock is not None else _DEFAULT_CLOCK
        self._expiring_time = None
        self._state = {}
        self._serializable = True

    def has_state(self, state_key: Hashable) -> bool:
        """Tell whether a store has stashed something under ``state_key``."""
        return state_key in self._state

    def set_state(self, state_key: Hashable, state: object) -> None:
        """Stash ``state`` under ``state_key``, replacing what was there.

        Each store uses its own class as ``state_key``, so two stores working
        on the same key never overwrite each other.
        """
        self._state[state_key] = state

    def remove_state(self, state_key: Hashable) -> None:
        """Forget what was stashed under ``state_key``; nothing there is fine."""
        _ = self._state.pop(state_key, None)

    def get_state(self, state_key: Hashable) -> object:
        """Return what was stashed under ``state_key``.

        Raises:
            KeyError: When nothing was stashed there.
        """
        return self._state[state_key]

    def mark_unserializable(self) -> None:
        """Refuse to be pickled from now on.

        Called by a store that keeps something on the key only this process
        can use. There is no way back: the thing may be gone, but the key
        cannot know that.
        """
        self._serializable = False

    def reset_lifetime(self) -> None:
        """Forget the expiry, so the next store to set one starts from nothing."""
        self._expiring_time = None

    def reduce_lifetime(self, ttl: float) -> None:
        """Expire in ``ttl`` seconds, unless the key already expires sooner.

        Only ever shortens: a lock several stores hold expires with the first
        of them to let it go.
        """
        new_time = self._now() + ttl
        if self._expiring_time is None or self._expiring_time > new_time:
            self._expiring_time = new_time

    def get_remaining_lifetime(self) -> float | None:
        """Return the seconds left before expiry, negative once past, ``None`` when unset."""
        return None if self._expiring_time is None else self._expiring_time - self._now()

    def is_expired(self) -> bool:
        """Tell whether an expiry is set and has passed."""
        return self._expiring_time is not None and self._expiring_time <= self._now()

    def _now(self) -> float:
        return self._clock.now().timestamp()

    @override
    def __getstate__(self) -> dict[str, object]:
        """Return what a pickle carries: the resource, the expiry and the stores' state.

        The clock stays behind; an unpickled key counts on the monotonic one.

        Raises:
            UnserializableKeyError: When a store marked the key as holding
                something only this process can use.
        """
        if not self._serializable:
            raise UnserializableKeyError(self._resource)

        return {
            "resource": self._resource,
            "expiring_time": self._expiring_time,
            "state": dict(self._state),
        }

    def __setstate__(self, data: dict[str, object]) -> None:
        """Rebuild a key from what :meth:`__getstate__` returned.

        The resource must come back as a plain string: a pickle is untrusted
        input, and anything else could run code the moment a store turns it
        into one.

        Raises:
            InvalidArgumentError: When the resource is not a string.
        """
        resource = data.get("resource")
        if type(resource) is not str:
            raise InvalidArgumentError(
                f"a pickled key must carry its resource as a str, got {type(resource).__name__}",
            )
        expiring_time = data.get("expiring_time")
        state = data.get("state")

        self._resource = resource
        self._clock = _DEFAULT_CLOCK
        self._expiring_time = (
            float(expiring_time) if isinstance(expiring_time, (int, float)) else None
        )
        self._state = dict(cast("dict[Hashable, object]", state)) if isinstance(state, dict) else {}
        self._serializable = True

    @override
    def __str__(self) -> str:
        """Return the resource, which is what a key reads as everywhere."""
        return self._resource

    @override
    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._resource!r})"
