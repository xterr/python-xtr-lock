from __future__ import annotations

from xtr_lock import Key
from xtr_lock.store._holder_token import holder_token


def test_a_key_keeps_its_token() -> None:
    key = Key("invoice")

    assert holder_token(key, "store") == holder_token(key, "store")


def test_two_keys_have_different_tokens() -> None:
    assert holder_token(Key("invoice"), "store") != holder_token(Key("invoice"), "store")


def test_a_reserved_value_is_never_handed_out() -> None:
    key = Key("invoice")
    key.set_state("store", "__write__")

    assert holder_token(key, "store", reserved="__write__") != "__write__"
