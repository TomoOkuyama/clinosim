"""Shared code-registry primitives (Issue #2256)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from clinosim.codes import code_exists, display, lookup, system_key_for_uri
from clinosim.codes.loader import _BUILTIN_URIS

pytestmark = pytest.mark.unit


def test_display_returns_none_on_a_miss() -> None:
    assert display("snomed-ct", "999999999", "ja") is None
    assert lookup("snomed-ct", "999999999", "ja") == "999999999"  # lookup keeps its echo


def test_display_resolves_like_lookup() -> None:
    assert display("snomed-ct", "387713003", "ja") == lookup("snomed-ct", "387713003", "ja")
    assert display("icd-10-cm", "E11.9", "en") == lookup("icd-10-cm", "E11.9", "en")


def test_code_exists() -> None:
    assert code_exists("snomed-ct", "387713003")
    assert not code_exists("snomed-ct", "999999999")
    with pytest.raises(ValueError):
        code_exists("no-such-system", "1")


@pytest.mark.parametrize(("key", "uri"), sorted(_BUILTIN_URIS.items()))
def test_system_key_for_uri_round_trips(key: str, uri: str) -> None:
    assert system_key_for_uri(uri) == key


def test_no_lookup_or_fallback_and_no_private_loader_outside_codes() -> None:
    offenders = []
    for path in Path("clinosim").rglob("*.py"):
        if path.parts[1] == "codes":
            continue
        src = path.read_text(encoding="utf-8")
        if "_load_system" in src:
            offenders.append(f"{path}: _load_system")
        tree = ast.parse(src)
        names = {
            a.asname or a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom) and n.module in ("clinosim.codes", "clinosim.codes.loader")
            for a in n.names
            if a.name == "lookup"
        }
        for n in ast.walk(tree):
            if isinstance(n, ast.BoolOp) and isinstance(n.op, ast.Or):
                first = n.values[0]
                if isinstance(first, ast.Call) and isinstance(first.func, ast.Name) and first.func.id in names:
                    offenders.append(f"{path}:{n.lineno}")
    assert not offenders, offenders
