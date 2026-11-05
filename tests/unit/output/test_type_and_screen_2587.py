"""Issue #2587: the blood group results belong to a type-and-screen order."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.blood_type import _bb_blood_type
from clinosim.modules.output.fhir_r4.labs.service_request import order_to_sr_id

pytestmark = pytest.mark.unit

_TS = {
    "order_id": "ORD-ENC-1-L01",
    "encounter_id": "ENC-1",
    "patient_id": "P1",
    "order_type": "lab",
    "display_name": "Type_and_screen",
    "ordered_datetime": "2025-03-01T10:00:00",
    "status": "resulted",
    "result": {"result_datetime": "2025-03-01T10:50:00", "lab_name": "Type_and_screen", "value": "Negative"},
}


def _ctx(orders: list[dict]) -> SimpleNamespace:
    record = {
        "orders": orders,
        "encounters": [
            {"encounter_id": "ENC-1", "encounter_type": "inpatient", "admission_datetime": "2025-03-01T09:00:00"}
        ],
    }
    return SimpleNamespace(
        record=record,
        patient_data={"blood_type": "A", "rh_factor": "+"},
        patient_id="P1",
        country="US",
        primary_enc_id="ENC-1",
    )


def test_a_typed_stay_bases_its_blood_group_results_on_the_order() -> None:
    out = _bb_blood_type(_ctx([_TS]))
    sr = f"ServiceRequest/{order_to_sr_id(_TS, {})}"
    obs = [r for r in out if r["resourceType"] == "Observation"]
    codes = {o["code"]["coding"][0]["code"] for o in obs if o.get("basedOn")}
    assert codes == {"883-9", "10331-7", "890-4"}
    assert all(o["basedOn"] == [{"reference": sr}] for o in obs if o.get("basedOn"))
    report = next(r for r in out if r["resourceType"] == "DiagnosticReport")
    assert report["code"]["coding"][0]["code"] == "34532-2" and report["basedOn"] == [{"reference": sr}]
    assert len(report["result"]) == 3


def test_a_typing_from_history_is_not_a_new_laboratory_result() -> None:
    out = _bb_blood_type(_ctx([]))
    assert out and all(r["resourceType"] == "Observation" for r in out)
    assert all("basedOn" not in o for o in out)
    assert not any(
        c.get("code") == "laboratory" for o in out for cat in o.get("category", []) for c in cat.get("coding", [])
    )
