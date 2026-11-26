"""Issue #3865: a weight-based "<bolus>, then <infusion>" drug keeps its per-kg
units, its written maxima and its stated infusion rate.

The US acute-MI heparin regimen "60U/kg bolus (max 4000U), then 12U/kg/h IV
(max 1000U/h)" used to become one absolute "60U IV DAILY" order carrying the
18 U/kg/h infusion default of another indication.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.order.engine import parse_dose_string, protocol_medication_orders
from clinosim.modules.output.fhir_r4.lib.dosage import build_dosage_instruction
from clinosim.simulator.medication_pipeline import _given_dose_text

pytestmark = pytest.mark.unit

_ADM = datetime(2024, 4, 1, 20, 0)
_HEPARIN = "60U/kg bolus (max 4000U), then 12U/kg/h IV (max 1000U/h)"


def _orders(dose: str, drug_id: str = "heparin", country: str = "us") -> list:
    spec = {"drug_id": drug_id, "dose": dose, "route": "IV"}
    return protocol_medication_orders(
        spec,
        order_id="ORD-E1-ADM-F00",
        encounter_id="E1",
        patient_id="P1",
        country=country,
        ordered_datetime=_ADM,
        ordered_by="DR-1",
    )


def test_the_parser_keeps_the_per_kg_unit_and_the_written_maximum() -> None:
    parsed = parse_dose_string(_HEPARIN)
    assert (parsed["dose_quantity"], parsed["dose_unit"]) == (60.0, "U/kg")
    assert parsed["dose_max_quantity"] == 4000.0
    for text, unit in (("80IU/kg bolus", "IU/kg"), ("80 units/kg IV bolus", "units/kg")):
        assert parse_dose_string(text)["dose_unit"] == unit


def test_heparin_is_a_one_time_bolus_and_a_continuous_infusion_at_the_protocol_rate() -> None:
    bolus, infusion = _orders(_HEPARIN)
    assert (bolus.dose_quantity, bolus.dose_unit, bolus.single_dose, bolus.route) == (60.0, "U/kg", True, "IV")
    assert bolus.frequency.lower() == "once" and bolus.dose_max_quantity == 4000.0
    assert (infusion.dose_quantity, infusion.dose_unit, infusion.single_dose) == (12.0, "U/kg/h", False)
    assert infusion.frequency == "CONTINUOUS" and infusion.dose_max_quantity == 1000.0
    assert infusion.route == "IV"
    # the infusion starts with the bolus, not the next day, and follows its verdict in the drug-safety gate
    assert infusion.administer_from is None and infusion.prior_order_id == bolus.order_id


def test_the_infusion_rate_comes_from_the_protocol_before_the_infusion_default() -> None:
    _, infusion = _orders(_HEPARIN)
    dosage = build_dosage_instruction(
        {
            "display_name": "Heparin",
            "dose_quantity": infusion.dose_quantity,
            "dose_unit": infusion.dose_unit,
            "route": "IV",
            "frequency": infusion.frequency,
        },
        country="US",
    )
    rate = dosage["doseAndRate"][0]["rateQuantity"]
    assert (rate["value"], rate["code"]) == (12.0, "U/kg/h")


def test_a_protocol_without_a_stated_rate_keeps_the_infusion_default() -> None:
    orders = _orders("80 U/kg IV bolus then infusion")
    assert len(orders) == 1 and orders[0].dose_unit == "U/kg"
    dosage = build_dosage_instruction(
        {
            "display_name": "Heparin",
            "dose_unit": "U/kg",
            "dose_quantity": 80.0,
            "route": "IV",
            "frequency": "CONTINUOUS",
        },
        country="US",
    )
    assert dosage["doseAndRate"][0]["rateQuantity"]["value"] == 18


def test_a_percent_bolus_followed_by_a_timed_infusion_is_not_split() -> None:
    # cerebral_infarction.yaml: acute_reperfusion alteplase
    orders = _orders("0.9 mg/kg IV (max 90mg), 10% bolus then 60min infusion", drug_id="alteplase")
    assert len(orders) == 1 and orders[0].order_id == "ORD-E1-ADM-F00"
    assert (orders[0].dose_quantity, orders[0].dose_unit, orders[0].dose_max_quantity) == (0.9, "mg/kg", 90.0)
    assert len(_orders("400-800mg IV bolus then infusion", drug_id="amiodarone")) == 1


@pytest.mark.parametrize(
    ("dose", "bolus", "rate", "rate_unit"),
    [
        ("50ug IV bolus, then 50ug/h continuous", 50.0, 50.0, "ug/h"),
        ("80mg IV bolus, then 8mg/h continuous infusion x 72h", 80.0, 8.0, "mg/h"),
        ("Initial bolus 5000IU IV, then 1000IU/h drip (adjust by APTT)", 5000.0, 1000.0, "IU/h"),
        ("80IU/kg bolus, then 18IU/kg/h (adjust by APTT)", 80.0, 18.0, "IU/kg/h"),
    ],
)
def test_other_bolus_then_infusion_protocols_are_split(dose: str, bolus: float, rate: float, rate_unit: str) -> None:
    first, second = _orders(dose, drug_id="octreotide")
    assert (first.dose_quantity, first.single_dose) == (bolus, True)
    assert (second.dose_quantity, second.dose_unit, second.frequency) == (rate, rate_unit, "CONTINUOUS")


def _patient(weight: float) -> SimpleNamespace:
    return SimpleNamespace(weight_kg=weight, height_cm=170.0)


def test_the_administered_bolus_and_rate_are_capped_at_the_written_maximum() -> None:
    bolus, infusion = _orders(_HEPARIN)
    assert _given_dose_text(bolus, _patient(100.0)) == "4000U"  # 60 U/kg x 100 kg = 6000, capped
    assert _given_dose_text(bolus, _patient(50.0)) == "3000U"  # below the cap
    assert _given_dose_text(infusion, _patient(100.0)) == "1000U/h"  # 12 U/kg/h x 100 kg = 1200, capped
    assert _given_dose_text(infusion, _patient(60.0)) == "720U/h"  # below the cap: 12 U/kg/h x 60 kg


def test_the_prescription_states_the_capped_absolute_bolus() -> None:
    bolus, _ = _orders(_HEPARIN)
    order = {
        "display_name": "Heparin",
        "dose_quantity": bolus.dose_quantity,
        "dose_unit": bolus.dose_unit,
        "dose_max_quantity": bolus.dose_max_quantity,
        "route": "IV",
        "frequency": "once",
    }
    heavy = build_dosage_instruction(order, country="US", body=(170.0, 100.0))
    light = build_dosage_instruction(order, country="US", body=(170.0, 50.0))
    assert heavy["doseAndRate"][0]["doseQuantity"]["value"] == 4000.0
    assert light["doseAndRate"][0]["doseQuantity"]["value"] == 3000.0


def test_an_administration_of_the_capped_infusion_states_the_rate_given() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_admin

    mar = {
        "drug_name": "Heparin",
        "dose": "1000U/h",
        "route": "IV",
        "status": "given",
        "scheduled_datetime": "2025-03-01T09:00:00",
    }
    parent = {"dose_quantity": 12.0, "dose_unit": "U/kg/h", "frequency": "CONTINUOUS"}
    dosage = _build_medication_admin(mar, "P1", 1, country="US", encounter_id="E1", parent_order=parent)["dosage"]
    assert (dosage["rateQuantity"]["value"], dosage["rateQuantity"]["code"]) == (1000.0, "U/h")
