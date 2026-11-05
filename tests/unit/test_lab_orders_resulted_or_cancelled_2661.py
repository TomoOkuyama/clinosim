"""Issue #2661: every lab order is resulted or cancelled by discharge."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.lab_pipeline import _run_lab_result_pipeline
from clinosim.types.encounter import Order, OrderStatus, OrderType

pytestmark = pytest.mark.unit


def test_an_analyte_without_a_modelled_value_is_resulted_from_its_reference_normal() -> None:
    rng = determinism.default_rng(1)
    roster = generate_roster("medium", "US", rng)
    person = PersonRecord(
        person_id="T-1", household_id="H-1", age=60, sex="F", date_of_birth=datetime(1965, 1, 1).date()
    )
    patient = activate_patient(person, rng, load_demographics("US"))
    order = Order(
        order_id="ORD-ENC-1-L01",
        encounter_id="ENC-1",
        patient_id=patient.patient_id,
        order_type=OrderType.LAB,
        display_name="TSH",
        ordered_datetime=datetime(2025, 3, 1, 6, 30),
        status=OrderStatus.PLACED,
    )
    _run_lab_result_pipeline([order], {}, set(), {}, patient, "us", roster, None, None)
    assert order.status == OrderStatus.RESULTED and order.result is not None


def test_an_unresulted_order_of_a_discharged_stay_is_revoked() -> None:
    from types import SimpleNamespace

    orders = [
        {
            "order_id": "O1",
            "encounter_id": "ENC-1",
            "patient_id": "pt1",
            "order_type": "lab",
            "order_code": "Phosphate",
            "display_name": "Phosphate",
            "urgency": "routine",
            "clinical_intent": "",
            "ordered_datetime": "2025-03-01T06:30:00",
            "ordered_by": "doc1",
            "status": "placed",
            "panel_key": "",
            "result": None,
        }
    ]
    enc = {
        "encounter_id": "ENC-1",
        "admission_datetime": "2025-03-01T00:00:00",
        "discharge_datetime": "2025-03-04T10:00:00",
    }
    ctx = SimpleNamespace(
        record={"orders": orders, "encounters": [enc]},
        country="us",
        patient_id="pt1",
        primary_enc_id="ENC-1",
        roster_map={},
        hospital_config={},
        patient_data={},
    )
    [sr] = _bb_service_requests(ctx)
    assert sr["status"] == "revoked"
    ctx.record["encounters"] = [{"encounter_id": "ENC-1", "admission_datetime": "2025-03-01T00:00:00"}]
    [sr] = _bb_service_requests(ctx)
    assert sr["status"] == "active"
