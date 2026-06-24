"""Unit tests for `clinosim.modules._shared.get_attr_or_key` — dict/dataclass dual access."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from clinosim.modules._shared import get_attr_or_key


@pytest.mark.unit
def test_get_attr_or_key_from_dict():
    assert get_attr_or_key({"k": 1}, "k") == 1


@pytest.mark.unit
def test_get_attr_or_key_from_object():
    @dataclass
    class _S:
        x: int = 42
    assert get_attr_or_key(_S(), "x") == 42


@pytest.mark.unit
def test_get_attr_or_key_missing_returns_default():
    assert get_attr_or_key({"k": 1}, "missing", "fb") == "fb"

    @dataclass
    class _S:
        x: int = 42
    assert get_attr_or_key(_S(), "missing", "fb") == "fb"


@pytest.mark.unit
def test_get_attr_or_key_none_obj():
    assert get_attr_or_key(None, "k", "fb") == "fb"
