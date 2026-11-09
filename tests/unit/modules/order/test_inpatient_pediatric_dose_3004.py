"""Inpatient children are dosed by weight (Issue #3004).

Inpatient medication orders, maintenance fluids and discharge prescriptions
for a minor are re-dosed from the weight charted at admission, as ED orders
are: oseltamivir 2 mg/kg (max 75 mg), acetaminophen 15 mg/kg, maintenance
fluids by the Holliday-Segar 4-2-1 rule — never more than the written adult
dose or rate.
"""

from __future__ import annotations

import pytest

from clinosim.modules.order.engine import enrich_medication_order
from clinosim.modules.order.pediatric_dose import (
    maintenance_fluid_ml_per_h,
    pediatric_dose_text,
    redose_order_for_child,
)
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit

_SEVEN_YEARS = 7 * 12


def _order(name: str, dose_str: str = "", drug_id: str = "") -> Order:
    o = Order(order_id="ORD-1", order_type=OrderType.MEDICATION, display_name=name, drug_id=drug_id)
    enrich_medication_order(o, dose_str=dose_str)
    return o


def test_an_18_9_kg_childs_inpatient_oseltamivir_is_38_mg() -> None:
    o = _order("Oseltamivir", "75mg PO BID", drug_id="oseltamivir")
    redose_order_for_child(o, _SEVEN_YEARS, 18.9)
    assert (o.dose_quantity, o.dose_unit, o.frequency) == (38.0, "mg", "BID")


def test_a_supportive_order_is_redosed_in_its_name_too() -> None:
    name = "antipyretic: Acetaminophen 500mg PO q6h PRN temp >= 38.5"
    o = _order(name, name.split(": ", 1)[1])
    redose_order_for_child(o, _SEVEN_YEARS, 18.9)
    assert o.dose_quantity == 284.0
    assert o.display_name == "antipyretic: Acetaminophen 284mg PO q6h PRN temp >= 38.5"


@pytest.mark.parametrize(("weight", "rate"), [(8.0, 32), (18.9, 58), (30.0, 70)])
def test_maintenance_fluids_follow_holliday_segar(weight: float, rate: int) -> None:
    assert maintenance_fluid_ml_per_h(weight) == rate
    o = _order("IV_fluid: NS 80-125 mL/h", "NS 80-125 mL/h")
    redose_order_for_child(o, _SEVEN_YEARS, weight)
    assert (o.dose_quantity, o.dose_unit) == (float(rate), "mL/h")
    assert o.display_name == f"IV_fluid: NS {rate} mL/h"


def test_the_written_adult_dose_or_rate_is_a_ceiling() -> None:
    o = _order("Oseltamivir", "75mg PO BID", drug_id="oseltamivir")
    redose_order_for_child(o, 16 * 12, 62.0)
    assert o.dose_quantity == 75.0
    fluid = _order("IV_fluid: NS 80-125 mL/h", "NS 80-125 mL/h")
    redose_order_for_child(fluid, 16 * 12, 70.0)  # Holliday-Segar 110 mL/h
    assert fluid.dose_quantity == 110.0
    small = _order("IV_fluid: NS 80 mL/h", "NS 80 mL/h")
    redose_order_for_child(small, 16 * 12, 70.0)
    assert small.dose_quantity == 80.0


def test_redosing_is_idempotent_and_leaves_adults_alone() -> None:
    o = _order("Oseltamivir", "75mg PO BID", drug_id="oseltamivir")
    redose_order_for_child(o, _SEVEN_YEARS, 18.9)
    redose_order_for_child(o, _SEVEN_YEARS, 18.9)
    assert o.dose_quantity == 38.0
    adult = _order("Oseltamivir", "75mg PO BID", drug_id="oseltamivir")
    redose_order_for_child(adult, 40 * 12, 60.0)
    assert adult.dose_quantity == 75.0


def test_a_per_kg_or_non_mg_order_is_unchanged() -> None:
    o = _order("Amoxicillin", "45mg/kg PO BID", drug_id="amoxicillin")
    before = (o.dose_quantity, o.dose_unit)
    redose_order_for_child(o, _SEVEN_YEARS, 18.9)
    assert (o.dose_quantity, o.dose_unit) == before


def test_a_discharge_prescription_dose_is_redosed() -> None:
    assert pediatric_dose_text("Oseltamivir", "75mg PO BID", _SEVEN_YEARS, 18.9) == "38mg PO BID"
    assert pediatric_dose_text("Oseltamivir", "75mg PO BID", 40 * 12, 60.0) == "75mg PO BID"
    # Cefazolin 25 mg/kg since Issue #3082; an unlisted drug keeps its dose.
    assert pediatric_dose_text("Cefazolin", "1g IV q8h", _SEVEN_YEARS, 18.9) == "472mg IV q8h"
    assert pediatric_dose_text("Amoxicillin", "1g PO", _SEVEN_YEARS, 18.9) == "1g PO"


def test_a_childs_epinephrine_and_cetirizine_are_weight_based() -> None:
    from clinosim.modules.order.pediatric_dose import pediatric_order_name

    assert pediatric_order_name("Epinephrine 0.3mg IM", 6 * 12, 17.2) == "Epinephrine 0.17mg IM"
    assert pediatric_order_name("Cetirizine 10mg", 6 * 12, 17.2) == "Cetirizine 4.3mg"


def test_a_country_override_applies_to_inpatient_orders() -> None:
    us = _order("Ibuprofen", "400mg PO q6h", drug_id="ibuprofen")
    jp = _order("Ibuprofen", "200mg PO TID", drug_id="ibuprofen")
    redose_order_for_child(us, 8 * 12, 25.0, "US")
    redose_order_for_child(jp, 8 * 12, 25.0, "JP")
    assert (us.dose_quantity, jp.dose_quantity) == (250.0, 100.0)
