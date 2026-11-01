"""Health-checkup results use canonical lab names, one item definition and the
shared reference-range YAML (Issue #2300)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.locale.loader import lab_code, load_reference_ranges
from clinosim.modules.health_checkup.engine import _interp_for, checkup_lab_names
from clinosim.modules.observation.engine import LAB_UNITS

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"


def test_items_are_canonical_lab_names() -> None:
    assert checkup_lab_names() == ["BMI", "SBP", "DBP", "HbA1c", "LDL"]
    assert all(name in LAB_UNITS for name in checkup_lab_names())


def test_ldl_uses_the_same_code_as_every_other_ldl_result() -> None:
    assert lab_code("LDL", "JP") == ("jlac10", "3F077")
    assert lab_code("LDL", "US") == ("loinc", "13457-7")


def test_body_measurements_have_a_loinc_secondary_code() -> None:
    assert lab_code("BMI", "US") == ("loinc", "39156-5")
    assert lab_code("SBP", "US") == ("loinc", "8480-6")
    assert lab_code("DBP", "US") == ("loinc", "8462-4")


def test_checkup_criteria_come_from_the_reference_range_yaml() -> None:
    ranges = load_reference_ranges("JP")["checkup_ranges"]
    assert set(ranges) == set(checkup_lab_names())
    assert _interp_for("HbA1c", 5.6) == ("H", ranges["HbA1c"]["text"])
    assert _interp_for("LDL", 119.9)[0] == "N"


def test_the_item_set_is_defined_once() -> None:
    literal = '"18262-6"'
    offenders = [str(p.relative_to(_ROOT)) for p in _ROOT.rglob("*.py") if literal in p.read_text(encoding="utf-8")]
    assert not offenders
