"""A weight-based prescription states the absolute dose to give (Issue #2991)."""

from __future__ import annotations

import pytest

from clinosim.modules.order.absolute_dose import absolute_dose
from clinosim.modules.output.fhir_r4.lib.dosage import build_dosage_instruction
from clinosim.modules.output.fhir_r4.medications.medications import _build_discharge_rx_dosage

pytestmark = pytest.mark.unit

_CHILD = (85.0, 12.0)  # height_cm, weight_kg


def _amoxicillin_order() -> dict:
    # pediatric_schedule.yaml: AAP AOM 80-90 mg/kg/day in 2 divided doses,
    # i.e. 45 mg/kg per dose BID.
    return {
        "display_name": "Amoxicillin 45mg/kg",
        "dose_quantity": 45.0,
        "dose_unit": "mg/kg",
        "route": "PO",
        "frequency": "BID",
        "frequency_per_day": 2,
    }


@pytest.mark.parametrize("country", ["US", "JP"])
def test_amoxicillin_45_mg_per_kg_for_12_kg_is_540_mg_bid(country: str) -> None:
    dosage = build_dosage_instruction(_amoxicillin_order(), country=country, body=_CHILD)
    qty = dosage["doseAndRate"][0]["doseQuantity"]
    assert (qty["value"], qty["unit"]) == (540.0, "mg")
    assert dosage["timing"]["repeat"]["frequency"] == 2
    assert "540mg" in dosage["text"] and "45mg/kg" in dosage["text"]


def test_without_a_weight_the_dose_is_left_as_written() -> None:
    dosage = build_dosage_instruction(_amoxicillin_order(), country="US")
    assert dosage["doseAndRate"][0]["doseQuantity"]["unit"] == "mg/kg"


def test_a_rate_keeps_its_rate() -> None:
    order = {"display_name": "Heparin drip", "dose_quantity": 18.0, "dose_unit": "U/kg/h", "route": "IV"}
    dosage = build_dosage_instruction(order, country="US", body=(170.0, 70.0))
    assert "rateQuantity" in dosage["doseAndRate"][0]


def test_vancomycin_20_mg_per_kg_iv_daily() -> None:
    order = {
        "display_name": "Vancomycin 20mg/kg IV DAILY",
        "dose_quantity": 20.0,
        "dose_unit": "mg/kg",
        "route": "IV",
        "frequency": "DAILY",
    }
    qty = build_dosage_instruction(order, country="US", body=(170.0, 70.0))["doseAndRate"][0]["doseQuantity"]
    assert (qty["value"], qty["unit"]) == (1400.0, "mg")


def test_the_written_maximum_caps_the_dose() -> None:
    assert absolute_dose(0.9, "mg/kg", 175.0, 110.0, text="Alteplase 0.9 mg/kg IV (max 90mg)") == (90.0, "mg")
    assert absolute_dose(0.9, "mg/kg", 175.0, 60.0, text="Alteplase 0.9 mg/kg IV (max 90mg)") == (54.0, "mg")


@pytest.mark.parametrize("country", ["US", "JP"])
def test_a_take_home_prescription_states_the_mg_dose(country: str) -> None:
    item = {"drug_name": "Amoxicillin", "dose": "45mg/kg", "route": "PO", "frequency": "BID"}
    dosage = _build_discharge_rx_dosage(item, "45mg/kg", "PO", "Amoxicillin", "", country, body=_CHILD)
    qty = dosage["doseAndRate"][0]["doseQuantity"]
    assert (qty["value"], qty["unit"]) == (540.0, "mg")
    assert "540mg" in dosage["text"] and "45mg/kg" in dosage["text"]


def test_a_loading_dose_before_an_infusion_is_stated_in_mg() -> None:
    order = {
        "display_name": "Aminophylline 6mg/kg IV loading then 0.5mg/kg/h",
        "dose_quantity": 6.0,
        "dose_unit": "mg/kg",
        "route": "IV",
        "frequency": "CONTINUOUS",
    }
    dar = build_dosage_instruction(order, country="JP", body=(160.0, 50.0))["doseAndRate"][0]
    assert (dar["doseQuantity"]["value"], dar["doseQuantity"]["unit"]) == (300.0, "mg")
