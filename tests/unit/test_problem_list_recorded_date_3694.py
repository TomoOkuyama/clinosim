"""Issue #3694: a problem-list Condition is dated at the patient's first recording."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.builder import _first_seen_by_patient
from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions, record_first_start

pytestmark = pytest.mark.unit


def _record(start: str, enc_id: str, admit_source: str = "outp") -> dict:
    return {
        "patient": {
            "patient_id": "P1",
            "sex": "M",
            "chronic_conditions": [{"code": "E11.9", "onset_date": "2018-08-07"}],
        },
        "encounters": [
            {
                "encounter_id": enc_id,
                "encounter_type": "outpatient",
                "admission_datetime": start,
                "attending_physician_id": "DR-1",
                "admit_source": admit_source,
            }
        ],
        "clinical_diagnosis": {"admission_diagnosis_code": "J06.9", "admission_diagnosis_system": "icd-10-cm"},
        "orders": [],
    }


def _problem_list_dates(rec: dict, first_seen: str) -> list[str]:
    return [
        c["recordedDate"]
        for c in _build_conditions(rec, "P1", "US", first_seen)
        if any(cat.get("coding", [{}])[0].get("code") == "problem-list-item" for cat in c.get("category", []))
    ]


def test_first_seen_is_the_earliest_start_regardless_of_record_order() -> None:
    recs = [
        _record("2026-10-26T10:24:00", "E3"),
        _record("2026-01-23T09:00:00", "E1"),
        _record("2026-04-30T08:00:00", "E2"),
    ]
    assert _first_seen_by_patient(iter(recs)) == {"P1": "2026-01-23T09:00:00"}


@pytest.mark.parametrize("rec_start", ["2026-10-26T10:24:00", "2026-01-23T09:00:00"])
def test_recorded_date_is_the_first_visit_whichever_record_is_emitted(rec_start: str) -> None:
    dates = _problem_list_dates(_record(rec_start, "EX"), "2026-01-23T09:00:00")
    assert dates and all(d.startswith("2026-01-23T09:00:00") for d in dates)


def test_single_record_patient_and_missing_first_seen_unchanged() -> None:
    rec = _record("2026-10-26T10:24:00", "E3")
    assert all(d.startswith("2026-10-26T10:24:00") for d in _problem_list_dates(rec, ""))
    assert all(d.startswith("2026-10-26T10:24:00") for d in _problem_list_dates(rec, "2026-10-26T10:24:00"))


def test_onset_year_is_not_used_as_recorded_date() -> None:
    assert all(
        not d.startswith("2018")
        for d in _problem_list_dates(_record("2026-10-26T10:24:00", "E3"), "2026-01-23T09:00:00")
    )


def test_via_ed_stay_starts_at_the_ed_arrival() -> None:
    rec = _record("2026-03-24T10:37:00", "E1", admit_source="emd")
    assert record_first_start(rec) < "2026-03-24T10:37:00"
