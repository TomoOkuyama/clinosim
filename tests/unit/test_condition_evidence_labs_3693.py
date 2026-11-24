"""Issue #3693: the principal diagnosis cites laboratory results only when the record has them."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions
from clinosim.modules.output.fhir_r4.conditions.conditions import _record_has_lab_results as has_labs

pytestmark = pytest.mark.unit


def _record(orders: list[dict]) -> dict:
    return {
        "patient": {"sex": "F", "chronic_conditions": []},
        "encounters": [
            {
                "encounter_id": "ENC-1",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-03-01T09:00:00",
                "attending_physician_id": "DR-1",
            }
        ],
        "clinical_diagnosis": {
            "admission_diagnosis_code": "J06.9",
            "admission_diagnosis_system": "icd-10-cm",
            "discharge_diagnosis_code": "J06.9",
        },
        "orders": orders,
    }


_LAB = {"order_type": "lab", "display_name": "CBC", "result": {"value": 1}}


def _principal_evidence(orders: list[dict], country: str) -> str:
    conds = [c for c in _build_conditions(_record(orders), "P1", country) if c.get("evidence")]
    texts = [c["evidence"][0]["code"][0]["text"] for c in conds]
    assert texts
    return texts[0]


def test_has_lab_results() -> None:
    assert has_labs(_record([_LAB]))
    assert not has_labs(_record([]))
    assert not has_labs(_record([{"order_type": "lab", "display_name": "CBC", "result": None}]))
    assert not has_labs(_record([{"order_type": "lab", "display_name": "Type_and_screen", "result": {"a": 1}}]))
    assert not has_labs(_record([{"order_type": "medication", "result": {"a": 1}}]))


@pytest.mark.parametrize(
    ("country", "with_labs", "without_labs"),
    [
        ("US", "Clinical presentation and supporting laboratory results", "Clinical presentation"),
        ("JP", "臨床所見および検査結果", "臨床所見"),
    ],
)
def test_principal_condition_evidence_follows_the_labs(country: str, with_labs: str, without_labs: str) -> None:
    assert _principal_evidence([_LAB], country) == with_labs
    assert _principal_evidence([], country) == without_labs
