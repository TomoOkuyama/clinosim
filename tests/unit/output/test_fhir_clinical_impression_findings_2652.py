"""Issue #2652: a ClinicalImpression carries its summary, findings and problem."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.conditions.clinical_impression import _bb_clinical_impressions
from clinosim.modules.output.fhir_r4.conditions.primary_ref import primary_condition_ref
from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs

pytestmark = pytest.mark.unit


def _lab(i: int, name: str, value: float, flag: str, when: str) -> dict:
    return {
        "order_id": f"O{i}",
        "encounter_id": "ENC-1",
        "patient_id": "pt-1",
        "order_type": "lab",
        "order_code": name,
        "display_name": name,
        "urgency": "routine",
        "clinical_intent": "",
        "ordered_datetime": when,
        "ordered_by": "doc1",
        "status": "resulted",
        "panel_key": "",
        "result": {"result_datetime": when, "lab_name": name, "value": value, "unit": "mmol/L", "flag": flag},
    }


def _ctx(country: str = "us") -> SimpleNamespace:
    impressions = [
        {
            "impression_id": f"ci-ENC-1-{d}",
            "encounter_id": "ENC-1",
            "date": f"2025-03-0{d + 1}T09:00:00",
            "day_index": d,
            "description": f"Day {d + 1}",
            "practitioner_id": "DR-1",
        }
        for d in range(2)
    ]
    record = {
        "extensions": {"clinical_impressions": impressions},
        "patient": {},
        "encounters": [{"encounter_id": "ENC-1", "admission_datetime": "2025-03-01T09:00:00"}],
        "clinical_diagnosis": {"discharge_diagnosis_code": "E87.5"},
        "orders": [
            _lab(0, "K", 5.9, "H", "2025-03-01T10:00:00"),
            _lab(1, "Na", 139.0, "", "2025-03-01T10:00:00"),
            _lab(2, "K", 4.4, "", "2025-03-02T06:30:00"),
        ],
    }
    return SimpleNamespace(
        record=record, country=country, patient_id="pt-1", primary_enc_id="ENC-1", patient_sex="", patient_data={}
    )


def test_an_impression_names_its_problem_and_the_days_abnormal_results() -> None:
    ctx = _ctx()
    day1, day2 = _bb_clinical_impressions(ctx)
    obs = {o["identifier"][0]["value"]: o["id"] for o in _bb_labs(ctx)}
    problem = {"reference": f"Condition/{primary_condition_ref(ctx.record, 'pt-1', 'ENC-1')}"}
    assert day1["problem"] == [problem] and day2["problem"] == [problem]
    assert day1["finding"] == [{"itemReference": {"reference": f"Observation/{obs['ENC-1-0000']}"}}]
    assert "K 5.9" in day1["summary"] and "[H]" in day1["summary"]
    assert "finding" not in day2
    assert day2["summary"]  # a day without abnormal results still states so


def test_a_japanese_summary_is_in_japanese() -> None:
    day1, _ = _bb_clinical_impressions(_ctx("jp"))
    assert "参照範囲外" in day1["summary"]
