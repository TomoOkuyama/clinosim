"""FHIR lab and condition emitter text comes from catalogs and code tables,
not Japanese literals in Python (Issue #2403)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim
from clinosim.codes import display

pytestmark = pytest.mark.unit

_FHIR = Path(clinosim.__file__).parent / "modules/output/fhir_r4"
_JP = re.compile(r"[぀-ヿ一-鿿]")


@pytest.mark.parametrize("package", ["labs", "conditions"])
def test_no_japanese_literal(package: str) -> None:
    hits = {}
    for path in sorted((_FHIR / package).glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        # Exception messages are log text, not output.
        docs |= {id(c) for r in ast.walk(tree) if isinstance(r, ast.Raise) for c in ast.walk(r)}
        lines = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and _JP.search(n.value)
        ]
        if lines:
            hits[path.name] = lines
    assert not hits, hits


def test_reference_range_meaning_displays_are_canonical() -> None:
    assert display("hl7-referencerange-meaning", "normal", "en") == "Normal Range"
    assert display("hl7-referencerange-meaning", "treatment", "en") == "Treatment Range"
