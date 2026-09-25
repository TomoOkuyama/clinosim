"""Regression tests for ``_format_lab_unit_for_prose``."""

from clinosim.modules.document.narrative.template_generator import (
    _format_lab_unit_for_prose,
)


def test_pure_annotation_returns_empty():
    assert _format_lab_unit_for_prose("{INR}") == ""
    assert _format_lab_unit_for_prose("{score}") == ""


def test_composite_with_trailing_annotation_strips_clause():
    assert _format_lab_unit_for_prose("mL/min/{1.73_m2}") == "mL/min"


def test_ucum_special_bracket_stripped():
    # Phase 1d-69: `mm[Hg]` reads as a placeholder in prose; the
    # blood-gas emit path calls this helper so `PaCO2 46.4 mm[Hg]`
    # renders as `PaCO2 46.4 mmHg`.
    assert _format_lab_unit_for_prose("mm[Hg]") == "mmHg"
    assert _format_lab_unit_for_prose("cm[H2O]") == "cmH2O"
    assert _format_lab_unit_for_prose("[in_i]") == "in_i"


def test_plain_units_passthrough():
    assert _format_lab_unit_for_prose("mg/dL") == "mg/dL"
    assert _format_lab_unit_for_prose("U/L") == "U/L"
    assert _format_lab_unit_for_prose("%") == "%"


def test_empty_input():
    assert _format_lab_unit_for_prose("") == ""
    assert _format_lab_unit_for_prose(None) == ""
    assert _format_lab_unit_for_prose("   ") == ""
