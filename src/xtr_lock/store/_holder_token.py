"""The token a key holds a lock by, in a store that tells holders apart by token."""

from __future__ import annotations

import base64
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Hashable

    from xtr_lock.key import Key

__all__ = ["holder_token"]


def holder_token(key: Key, state_key: Hashable, *, reserved: str | None = None) -> str:
    """Return the token that identifies ``key`` as a holder, making one the first time.

    Kept on the key under ``state_key``, so every store of one kind sees the
    same token. ``reserved`` is a value the store uses for something else,
    never handed out as a token.
    """
    if not key.has_state(state_key) or key.get_state(state_key) == reserved:
        key.set_state(state_key, base64.b64encode(secrets.token_bytes(32)).decode("ascii"))

    return str(key.get_state(state_key))
