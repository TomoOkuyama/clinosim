"""Issue #3242: admission orders carry the order set they were written in.

The ED note of a via-ED admission lists the initial order set (the ED
workup and first treatment) and must leave out the home-medication
continuation, ward-care orders written with the admission (catheter, bed
rest, diet, precautions) and later treatment. The simulator records that
provenance on ``Order.order_set`` instead of the narrative parsing order ids
or intent text.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim.modules._shared import ORDER_SET_ADMISSION_CARE, ORDER_SET_ADMISSION_INITIAL
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.order.engine import admission_care_supportive_types, place_admission_orders, place_imaging_orders
from clinosim.simulator.medication_pipeline import apply_drug_safety_gate_to_orders
from clinosim.types.allergy import Allergy
from clinosim.types.encounter import Order, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADM = datetime(2024, 4, 1, 20, 0)
_ASPIRIN = "387458008"
_DISEASES = Path("clinosim/modules/disease/reference_data")


def _protocol() -> dict:
    return {
        "order_protocols": {
            "admission_orders": {
                "labs": [{"test": "CBC", "urgency": "stat"}, {"test": "Troponin_I", "urgency": "stat"}],
                "supportive": [
                    {"type": "IV_fluid", "detail": "NS 80 mL/h"},
                    {"type": "urinary_catheter", "detail": "Foley catheter for perioperative period"},
                    {"type": "bed_rest", "detail": "Bed rest"},
                ],
                "imaging": [{"test": "Chest_Xray", "urgency": "stat"}],
            }
        },
        "drugs": {"first_line": {"us": [{"drug": "Aspirin", "dose": "325mg PO once"}]}},
    }


def _by_display(orders: list[Order]) -> dict[str, str]:
    return {o.display_name: o.order_set for o in orders}


def test_initial_workup_and_first_treatment_are_the_initial_order_set() -> None:
    orders = place_admission_orders(_protocol(), "P1", "ENC-1", _ADM, "us", np.random.default_rng(1))
    sets = _by_display(orders)
    assert sets["CBC"] == ORDER_SET_ADMISSION_INITIAL
    assert sets["Troponin_I"] == ORDER_SET_ADMISSION_INITIAL
    assert sets["Aspirin"] == ORDER_SET_ADMISSION_INITIAL
    assert sets["Chest_Xray"] == ORDER_SET_ADMISSION_INITIAL
    assert sets["IV_fluid: NS 80 mL/h"] == ORDER_SET_ADMISSION_INITIAL


def test_ward_care_orders_are_the_admission_care_set() -> None:
    orders = place_admission_orders(_protocol(), "P1", "ENC-1", _ADM, "us", np.random.default_rng(1))
    sets = _by_display(orders)
    assert sets["urinary_catheter: Foley catheter for perioperative period"] == ORDER_SET_ADMISSION_CARE
    assert sets["bed_rest: Bed rest"] == ORDER_SET_ADMISSION_CARE


def test_order_set_moves_no_draw() -> None:
    """The tag is written at creation without a draw: the order times are the
    ones a second run with the same seed places."""
    a = place_admission_orders(_protocol(), "P1", "ENC-1", _ADM, "us", np.random.default_rng(7))
    b = place_admission_orders(_protocol(), "P1", "ENC-1", _ADM, "us", np.random.default_rng(7))
    assert [(o.order_id, o.ordered_datetime) for o in a] == [(o.order_id, o.ordered_datetime) for o in b]


def test_substitute_for_an_initial_order_stays_in_the_initial_set() -> None:
    order = Order(
        order_id="ORD-ENC-1-ADM-M01",
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        display_name="Ibuprofen 400mg",
        ordered_datetime=_ADM,
        order_set=ORDER_SET_ADMISSION_INITIAL,
    )
    patient = PatientProfile(patient_id="PT-1", age=40, sex="F")
    patient.allergies = [Allergy(allergy_id="1", allergen_code=_ASPIRIN, category="medication")]  # type: ignore[arg-type]
    out = apply_drug_safety_gate_to_orders(
        [order], patient=patient, encounter_id="ENC-1", ordered_datetime=_ADM, country="us"
    )
    assert [(o.display_name, o.order_set) for o in out] == [("Acetaminophen", ORDER_SET_ADMISSION_INITIAL)]


def test_every_admission_care_type_is_a_supportive_type_some_disease_writes() -> None:
    written: set[str] = set()
    for path in _DISEASES.glob("*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        for sup in ((data.get("order_protocols") or {}).get("admission_orders") or {}).get("supportive") or []:
            written.add(str(sup.get("type", "")))
    unknown = admission_care_supportive_types() - written
    assert not unknown, f"admission care types no disease writes: {sorted(unknown)}"


def test_admission_day_disease_imaging_is_initial_and_later_imaging_is_not() -> None:
    protocol = load_disease_protocol("cerebral_infarction")
    counter: dict[str, int] = {"I": 0}
    (ct,) = place_imaging_orders(protocol, "ENC-1", "P1", _ADM, 0, "moderate", np.random.default_rng(1), counter)
    (mr,) = place_imaging_orders(protocol, "ENC-1", "P1", _ADM, 1, "moderate", np.random.default_rng(1), counter)
    assert (ct.imaging_modality, ct.order_set) == ("CT", ORDER_SET_ADMISSION_INITIAL)
    assert (mr.imaging_modality, mr.order_set) == ("MR", "")
