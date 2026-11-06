"""Issue #2752: a continuous-infusion rate keeps its per-time unit and is stated as a rate."""

from __future__ import annotations

import pytest

from clinosim.modules.order.engine import parse_dose_string
from clinosim.modules.output.fhir_r4.lib.dosage import build_dosage_instruction, is_rate_unit

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("text", "qty", "unit"),
    [
        ("Norepinephrine 0.05-0.3ug/kg/min IV drip", 0.3, "ug/kg/min"),
        ("Heparin 18 units/kg/h IV", 18.0, "units/kg/h"),
        ("Nicardipine 5mg/h IV", 5.0, "mg/h"),
        ("Diltiazem 0.25mg/kg IV bolus then 5-15mg/h", 0.25, "mg/kg"),  # the leading bolus is the dose
        ("Ceftriaxone 2g IV daily", 2.0, "g"),
    ],
)
def test_the_dose_parser_keeps_the_rate_unit(text: str, qty: float, unit: str) -> None:
    parsed = parse_dose_string(text)
    assert (parsed["dose_quantity"], parsed["dose_unit"]) == (qty, unit)


def test_rate_units() -> None:
    assert is_rate_unit("ug/kg/min") and is_rate_unit("mg/h") and is_rate_unit("mL/hr")
    assert not is_rate_unit("mg/kg") and not is_rate_unit("mg")


def test_a_rate_is_stated_as_rate_quantity() -> None:
    order = {
        "display_name": "Norepinephrine 0.05-0.3ug/kg/min IV drip",
        "dose_quantity": 0.3,
        "dose_unit": "ug/kg/min",
        "route": "IV",
        "frequency": "DRIP",
    }
    dar = (build_dosage_instruction(order) or {}).get("doseAndRate") or [{}]
    assert "doseQuantity" not in dar[0]
    assert dar[0]["rateQuantity"]["code"] == "ug/kg/min" and dar[0]["rateQuantity"]["value"] == 0.3


def test_an_administration_of_an_infusion_states_its_rate() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin

    mar = {
        "drug_name": "Norepinephrine",
        "dose": "",
        "route": "IV",
        "status": "given",
        "scheduled_datetime": "2025-03-01T09:00:00",
    }
    parent = {"dose_quantity": 0.3, "dose_unit": "ug/kg/min", "frequency": "DRIP"}
    dosage = _build_medication_admin(mar, "P1", 1, country="US", encounter_id="E1", parent_order=parent)["dosage"]
    assert "dose" not in dosage
    assert dosage["rateQuantity"]["code"] == "ug/kg/min" and dosage["rateQuantity"]["value"] == 0.3
