"""Unit tests for build_ucum_quantity helper (feedback fix PR-A, 2026-07-16).

JP-CLINS eCS profiles (JP_MedicationAdministration_eCS,
JP_MedicationRequest_eCS, JP_Observation_ReferenceRange, ...) declare
Quantity.code with `min=1`. The helper is the single edit point for every
UCUM Quantity emission in the FHIR builders — MR.doseQuantity /
MA.dosage.dose / MA.dosage.rateQuantity / Observation.referenceRange.low +
high all route through it.
"""

from __future__ import annotations

from clinosim.modules.output._fhir_common import build_ucum_quantity


def test_build_ucum_quantity_populates_all_four_fields():
    """value + unit + system + code must all be present when unit is truthy."""
    q = build_ucum_quantity(325.0, "mg")
    assert q == {
        "value": 325.0,
        "unit": "mg",
        "system": "http://unitsofmeasure.org",
        "code": "mg",
    }


def test_build_ucum_quantity_code_matches_unit():
    """FHIR UCUM idiom: `unit` is display, `code` is machine token; for standard
    clinical units the two strings are identical."""
    for unit in ("mL", "g/dL", "mL/h", "mmol/L", "mEq/L", "U/L", "10*9/L"):
        q = build_ucum_quantity(1.0, unit)
        assert q["unit"] == unit
        assert q["code"] == unit


def test_build_ucum_quantity_omits_unit_and_code_on_empty_unit():
    """FHIR R4 ele-1 forbids empty-string element values; when the unit is
    unknown, the helper must omit both `unit` and `code` (value + system stay)."""
    q = build_ucum_quantity(1.0, "")
    assert q == {"value": 1.0, "system": "http://unitsofmeasure.org"}
    assert "unit" not in q
    assert "code" not in q


def test_build_ucum_quantity_preserves_numeric_types():
    """int / float / bool-ish values are passed through as-is (no cast)."""
    assert build_ucum_quantity(325, "mg")["value"] == 325
    assert build_ucum_quantity(325.0, "mg")["value"] == 325.0
    assert build_ucum_quantity(0, "mg")["value"] == 0
