"""FHIR shared-library text comes from catalogs and code tables, not Japanese
literals in Python (Issue #2402)."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import clinosim
from clinosim.modules.output.fhir_r4.lib.dosage import _resolve_patient_instruction_ja
from clinosim.modules.output.fhir_r4.lib.ecs_extensions import build_ecs_department_extension
from clinosim.modules.output.fhir_r4.lib.reference_data import _SEVERITY_JP

pytestmark = pytest.mark.unit

_LIB = Path(clinosim.__file__).parent / "modules/output/fhir_r4/lib"
_JP = re.compile(r"[぀-ヿ一-鿿]")


def test_no_japanese_literal_in_fhir_lib() -> None:
    hits = {}
    for path in sorted(_LIB.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {id(n.value) for n in ast.walk(tree) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        lines = [
            n.lineno
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and _JP.search(n.value)
        ]
        if lines:
            hits[path.name] = lines
    assert not hits, hits


def test_values_unchanged() -> None:
    assert _SEVERITY_JP["moderate"] == {"code": "MO", "display": "中度"}
    assert build_ecs_department_extension()["valueCodeableConcept"]["text"] == "総合診療科"
    assert _resolve_patient_instruction_ja("経口", "1日2回", None) == _resolve_patient_instruction_ja(
        "経口", "bid", None
    )
    assert "朝・夕" in _resolve_patient_instruction_ja("経口", "bid", None)
