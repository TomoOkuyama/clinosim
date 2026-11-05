"""Issue #2653: an imaging order is completed once its study is performed."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.service_request import _bb_service_requests

pytestmark = pytest.mark.unit


def _order(order_id: str) -> dict:
    return {
        "order_id": order_id,
        "encounter_id": "enc1",
        "patient_id": "pt1",
        "order_type": "imaging",
        "order_code": "Chest_Xray",
        "display_name": "Chest_Xray",
        "urgency": "stat",
        "clinical_intent": "",
        "ordered_datetime": "2025-03-01T10:00:00",
        "ordered_by": "doc1",
        "status": "placed",
    }


def _ctx(studies: list[dict], discharged: bool) -> SimpleNamespace:
    enc = {"encounter_id": "enc1", "admission_datetime": "2025-03-01T09:00:00"}
    if discharged:
        enc.update(discharge_datetime="2025-03-04T11:00:00", status="completed")
    return SimpleNamespace(
        record={
            "orders": [_order("O-done"), _order("O-never")],
            "extensions": {"imaging": studies},
            "encounters": [enc],
        },
        country="us",
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
    )


def _status(ctx) -> dict[str, str]:
    return {sr["identifier"][0]["value"]: sr["status"] for sr in _bb_service_requests(ctx)}


def test_a_performed_study_completes_its_order() -> None:
    study = {
        "study_id": "imgst-1",
        "order_id": "O-done",
        "status": "available",
        "started_datetime": "2025-03-01T10:40:00",
    }
    assert _status(_ctx([study], discharged=False)) == {"O-done": "completed", "O-never": "active"}


def test_an_order_never_performed_by_discharge_is_revoked() -> None:
    study = {
        "study_id": "imgst-1",
        "order_id": "O-done",
        "status": "available",
        "started_datetime": "2025-03-01T10:40:00",
    }
    assert _status(_ctx([study], discharged=True)) == {"O-done": "completed", "O-never": "revoked"}
