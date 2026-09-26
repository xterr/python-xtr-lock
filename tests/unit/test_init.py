from __future__ import annotations

import importlib.metadata

import xtr_lock


def test_every_public_name_is_importable() -> None:
    for name in xtr_lock.__all__:
        assert hasattr(xtr_lock, name), name


def test_the_version_is_the_installed_one() -> None:
    assert xtr_lock.__version__ == importlib.metadata.version("xtr-lock")
