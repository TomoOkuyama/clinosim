"""A child's IV fluid bolus is sized by weight (Issue #2977).

ED protocols write an adult fixed bolus ("IV normal saline 1000mL"). A child
gets 20 mL/kg of the weight charted at the visit (PALS 2020), never more
than the written adult volume, in the order and its administration.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.order.engine import enrich_medication_order
from clinosim.modules.order.pediatric_dose import pediatric_order_name
from clinosim.modules.order.placed_order_mar import administrations_for
from clinosim.modules.population.encounter_anthropometry import encounter_weight_kg
from clinosim.simulator.emergency import ed_pediatric_dose_name
from clinosim.types.encounter import Order, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def test_a_10_kg_childs_gastroenteritis_bolus_is_200_ml() -> None:
    assert pediatric_order_name("IV normal saline 1000mL", 24, 10.0, country="US") == "IV normal saline 200mL"


def test_a_volume_in_litres_is_rewritten_in_ml() -> None:
    assert pediatric_order_name("IV normal saline 1L", 72, 18.0, country="US") == "IV normal saline 360mL"


def test_the_bolus_never_exceeds_the_written_adult_volume() -> None:
    assert pediatric_order_name("IV normal saline 1000mL", 180, 62.0, country="US") == "IV normal saline 1000mL"
    assert pediatric_order_name("IV normal saline 500mL", 120, 32.0, country="US") == "IV normal saline 500mL"


def test_lactated_ringer_is_weight_based_too() -> None:
    assert pediatric_order_name("IV lactated Ringer 1000mL", 36, 14.0, country="US") == "IV lactated Ringer 280mL"


def test_adults_and_unsized_fluid_orders_are_unchanged() -> None:
    assert pediatric_order_name("IV normal saline 1000mL", 240, 70.0, country="US") == "IV normal saline 1000mL"
    assert pediatric_order_name("IV normal saline", 24, 10.0, country="US") == "IV normal saline"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_the_ed_order_and_its_administration_carry_the_weight_based_volume(country: str) -> None:
    child = PatientProfile(
        patient_id="POP-002995", sex="M", date_of_birth=date(2023, 6, 1), age=0, height_cm=62.0, weight_kg=6.2
    )
    visit = SimpleNamespace(encounter_id="ENC-002977-ED", admission_datetime=datetime(2025, 9, 1, 10, 30))
    weight = encounter_weight_kg(child, visit.encounter_id, visit.admission_datetime, country)
    name = ed_pediatric_dose_name("IV normal saline 1000mL", child, visit, visit.admission_datetime, country)
    assert name == f"IV normal saline {round(20 * weight)}mL"

    order = Order(order_id="ORD-1", order_type=OrderType.MEDICATION, display_name=name, route="IV", frequency="ONCE")
    enrich_medication_order(order)
    assert (order.dose_quantity, order.dose_unit) == (float(round(20 * weight)), "mL")
    (mar,) = administrations_for(order, [visit.admission_datetime], "RN-1")
    assert mar.dose.startswith(f"{float(round(20 * weight))}mL")
    assert float(mar.dose.split("mL")[0]) / weight <= 20.0 + 0.5 / weight
