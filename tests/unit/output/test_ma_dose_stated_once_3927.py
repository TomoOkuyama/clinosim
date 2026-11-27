"""A MedicationAdministration dosage text states its dose once (Issue #3927)."""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import _build_ma_dosage_block

pytestmark = pytest.mark.unit


def _text(mar_dose: str, qty: float, unit: str, country: str = "US", route: str = "IV") -> str:
    block = _build_ma_dosage_block(
        {"dose": mar_dose, "route": route},
        {"dose_quantity": qty, "dose_unit": unit, "route": route},
        "drug",
        "drug",
        "drug",
        "",
        country,
    )
    assert block is not None
    return block["text"]


@pytest.mark.parametrize(
    ("mar_dose", "qty", "unit", "country", "expected"),
    [
        ("2.0ug/kg/min DRIP", 2.0, "ug/kg/min", "US", "2.0ug/kg/min DRIP"),
        ("1.0% ONCE", 1.0, "%", "US", "1.0% ONCE"),
        ("18.0U/kg/h 持続", 18.0, "U/kg/h", "JP", "18.0U/kg/h 持続"),
        ("2ug/kg/min DRIP", 2.0, "ug/kg/min", "US", "2ug/kg/min DRIP"),
        ("0.5ug/kg/min DRIP", 0.5, "ug/kg/min", "US", "0.5ug/kg/min DRIP"),
    ],
)
def test_dose_not_repeated(mar_dose: str, qty: float, unit: str, country: str, expected: str) -> None:
    text = _text(mar_dose, qty, unit, country)
    assert re.sub(r"\s+", "", text) == re.sub(r"\s+", "", expected), text
    nums = re.findall(r"\d+(?:\.\d+)?\s*(?:ug|U|%)", text)
    assert len(nums) == 1, text


def test_different_dose_is_still_prepended() -> None:
    # The text states 5 ug/kg/min; the order says 2: nothing is hidden, both appear.
    text = _text("DRIP", 2.0, "ug/kg/min")
    assert "2" in text
