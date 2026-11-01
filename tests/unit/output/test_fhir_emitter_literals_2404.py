"""FHIR emitter text comes from catalogs and code tables, not Japanese
literals in Python (Issue #2404). Input matchers stay in code."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

import clinosim

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_FHIR = _ROOT / "modules/output/fhir_r4"
_JP = re.compile(r"[぀-ヿ一-鿿]")
# Keywords matched against chief complaints, ward names and order text.
_MATCHERS = {
    "encounters/encounter.py": {"健康診断", "予防接種", "フォローアップ"},
    "encounters/facility.py": {"回復期"},
    "procedures/immunization.py": {"予防接種", "小児"},
    "procedures/oxygen_therapy.py": {"目標"},
}
# Covered by #2402 / #2403.
_OTHER_ISSUES = ("lib", "labs", "conditions")


def test_no_japanese_literal_in_fhir_emitters() -> None:
    hits = {}
    for path in sorted(_FHIR.rglob("*.py")):
        rel = path.relative_to(_FHIR).as_posix()
        if rel.split("/")[0] in _OTHER_ISSUES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        skip |= {id(c) for r in ast.walk(tree) if isinstance(r, ast.Raise) for c in ast.walk(r)}
        allowed = _MATCHERS.get(rel, set())
        found = [
            (n.lineno, n.value)
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant)
            and isinstance(n.value, str)
            and id(n) not in skip
            and _JP.search(n.value)
            and n.value not in allowed
        ]
        if found:
            hits[rel] = found
    assert not hits, hits


def test_moved_entries_have_both_languages() -> None:
    data = yaml.safe_load((_ROOT / "locale/shared/narrative_phrases.yaml").read_text(encoding="utf-8"))
    for key, entry in data["fhir_emit_text"].items():
        assert entry.get("en") and entry.get("ja"), key
