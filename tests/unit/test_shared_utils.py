"""Unit tests for clinosim.modules._shared dict/dataclass dual-access helpers."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from clinosim.modules._shared import get_attr_or_key, get_or_create_container, set_attr_or_key


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


# ---------------------------------------------------------------------------
# set_attr_or_key — write-side counterpart to get_attr_or_key. Replaces the
# `if isinstance(rec, dict): rec["x"]=... else: rec.x=...` branching pattern
# scattered across enrichers (2026-07-02 grand design review, dual-access
# sweep write side).
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_set_attr_or_key_on_dict():
    d = {}
    set_attr_or_key(d, "k", 1)
    assert d == {"k": 1}


@pytest.mark.unit
def test_set_attr_or_key_on_dataclass():
    @dataclass
    class _S:
        x: int = 0
    s = _S()
    set_attr_or_key(s, "x", 42)
    assert s.x == 42


# ---------------------------------------------------------------------------
# get_or_create_container — fetches (or, for the dict path, lazily creates) a
# nested mutable dict/list field so the caller can mutate it in place
# (obj["x"] = value / obj.append(item) / obj.extend(items)) without needing
# further isinstance branching. Dataclass fields always exist via
# default_factory, so no creation is needed on that path.
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_get_or_create_container_dict_creates_missing():
    d = {}
    ext = get_or_create_container(d, "extensions", dict)
    ext["device"] = ["x"]
    assert d == {"extensions": {"device": ["x"]}}


@pytest.mark.unit
def test_get_or_create_container_dict_reuses_existing():
    d = {"orders": [1]}
    orders = get_or_create_container(d, "orders", list)
    orders.append(2)
    assert d == {"orders": [1, 2]}


@pytest.mark.unit
def test_get_or_create_container_dataclass_reuses_field():
    @dataclass
    class _S:
        orders: list = field(default_factory=list)
    s = _S(orders=[1])
    orders = get_or_create_container(s, "orders", list)
    orders.append(2)
    assert s.orders == [1, 2]


@pytest.mark.unit
def test_get_or_create_container_composes_for_nested_extensions():
    d = {}
    ext = get_or_create_container(d, "extensions", dict)
    abx = get_or_create_container(ext, "antibiotic", list)
    abx.extend(["regimen1"])
    assert d == {"extensions": {"antibiotic": ["regimen1"]}}
