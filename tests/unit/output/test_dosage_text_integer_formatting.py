"""Issue #781 (part of META #774): `dosageInstruction[].text` renders
integer-valued dose floats without a trailing `.0` — `4mg` not `4.0mg`.

`doseQuantity.value` (JSON number) is unaffected — both `4.0` and `4`
serialize identically. Only the human-readable `text` field is
reformatted."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.common import build_dosage_instruction

pytestmark = pytest.mark.unit


def _order(dose_qty, dose_unit, freq="qd", route="PO"):
    return {
        "dose_quantity": dose_qty,
        "dose_unit": dose_unit,
        "frequency": freq,
        "route": route,
    }


@pytest.mark.parametrize(
    "qty,unit,expected_dose_str",
    [
        (4.0, "mg", "4mg"),
        (500.0, "mg", "500mg"),
        (1.0, "g", "1g"),
        (200.0, "mL", "200mL"),
        (40.0, "mg", "40mg"),
        (4, "mg", "4mg"),  # int (no .0 to strip)
    ],
)
def test_integer_valued_dose_drops_trailing_zero(qty, unit, expected_dose_str):
    d = build_dosage_instruction(_order(qty, unit), country="US")
    assert d is not None
    text = d.get("text", "")
    assert expected_dose_str in text, f"expected {expected_dose_str!r} in text {text!r}"
    # doseQuantity numeric value preserved as-is (JSON number, not human text)
    dq = d["doseAndRate"][0]["doseQuantity"]
    assert dq["value"] == qty
    assert dq["unit"] == unit


@pytest.mark.parametrize(
    "qty,unit,expected_dose_str",
    [
        (0.4, "mg", "0.4mg"),
        (12.5, "mg", "12.5mg"),
        (2.5, "mL", "2.5mL"),
    ],
)
def test_non_integer_dose_preserves_decimal(qty, unit, expected_dose_str):
    d = build_dosage_instruction(_order(qty, unit), country="US")
    assert d is not None
    assert expected_dose_str in d.get("text", "")


def test_jp_locale_also_drops_dot_zero():
    d = build_dosage_instruction(_order(4.0, "mg"), country="JP")
    assert d is not None
    # Both 経口 (route localized) and 4mg (integer) present
    text = d.get("text", "")
    assert "4mg" in text
    assert "4.0mg" not in text
