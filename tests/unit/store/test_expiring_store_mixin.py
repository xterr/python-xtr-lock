from __future__ import annotations

from abc import ABCMeta
from typing import final

import pytest
from typing_extensions import override

from xtr_lock import ExpiringStoreMixin, Key, LockExpiredError

pytestmark = pytest.mark.anyio


@final
class DeletingStore(ExpiringStoreMixin):
    def __init__(self, error: Exception | None = None) -> None:
        self.deleted: list[str] = []
        self._error = error

    @override
    async def delete(self, key: Key) -> None:
        self.deleted.append(str(key))
        if self._error is not None:
            raise self._error

    async def check(self, key: Key) -> None:
        await self._check_not_expired(key)


async def test_a_key_without_expiry_passes() -> None:
    store = DeletingStore()

    await store.check(Key("r"))

    assert store.deleted == []


async def test_a_key_with_time_left_passes() -> None:
    store = DeletingStore()
    key = Key("r")
    key.reduce_lifetime(60)

    await store.check(key)

    assert store.deleted == []


async def test_an_expired_key_is_deleted_and_reported() -> None:
    store = DeletingStore()
    key = Key("r")
    key.reduce_lifetime(0)

    with pytest.raises(LockExpiredError) as raised:
        await store.check(key)

    assert store.deleted == ["r"]
    assert raised.value.resource == "r"


async def test_a_failing_delete_does_not_hide_the_expiry() -> None:
    store = DeletingStore(RuntimeError("down"))
    key = Key("r")
    key.reduce_lifetime(0)

    with pytest.raises(LockExpiredError):
        await store.check(key)


def test_a_store_without_delete_cannot_be_built() -> None:
    class Incomplete(ExpiringStoreMixin, metaclass=ABCMeta):
        pass

    with pytest.raises(TypeError, match="abstract"):
        # The refusal is the point.
        _ = Incomplete()  # pyright: ignore[reportAbstractUsage]  # ty: ignore[call-non-callable]
