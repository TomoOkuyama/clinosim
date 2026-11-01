"""Regression tests for ``ucum_prose`` (UCUM unit as written in prose)."""

from clinosim.codes.ucum import ucum_prose


def test_pure_annotation_returns_empty():
    assert ucum_prose("{INR}") == ""
    assert ucum_prose("{score}") == ""


def test_composite_with_trailing_annotation_strips_clause():
    assert ucum_prose("mL/min/{1.73_m2}") == "mL/min"


def test_ucum_special_bracket_stripped():
    # Phase 1d-69: `mm[Hg]` reads as a placeholder in prose; the
    # blood-gas emit path calls this helper so `PaCO2 46.4 mm[Hg]`
    # renders as `PaCO2 46.4 mmHg`.
    assert ucum_prose("mm[Hg]") == "mmHg"
    assert ucum_prose("cm[H2O]") == "cmH2O"
    assert ucum_prose("[in_i]") == "in_i"


def test_plain_units_passthrough():
    assert ucum_prose("mg/dL") == "mg/dL"
    assert ucum_prose("U/L") == "U/L"
    assert ucum_prose("%") == "%"


def test_empty_input():
    assert ucum_prose("") == ""
    assert ucum_prose(None) == ""
    assert ucum_prose("   ") == ""
