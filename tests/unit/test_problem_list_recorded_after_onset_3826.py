"""Issue #3826: a problem-list Condition is recorded when the record first
carries it, not before.

Issue #3694 dated every problem-list Condition at the patient's first visit.
A chronic disease diagnosed later in the window then had a recordedDate
before its onset (US 30, JP 25 Conditions in a 1-year p=1000 cohort). The
first visit is now taken per condition code, over the records whose patient
snapshot carries the code."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.builder import _first_seen_by_patient
from clinosim.modules.output.fhir_r4.conditions.conditions import _build_conditions

pytestmark = pytest.mark.unit


def _record(start: str, enc_id: str, chronic: list[tuple[str, str]]) -> dict:
    return {
        "patient": {
            "patient_id": "P1",
            "sex": "F",
            "chronic_conditions": [{"code": c, "onset_date": o} for c, o in chronic],
        },
        "encounters": [
            {
                "encounter_id": enc_id,
                "encounter_type": "outpatient",
                "admission_datetime": start,
                "attending_physician_id": "DR-1",
                "admit_source": "outp",
            }
        ],
        "clinical_diagnosis": {"admission_diagnosis_code": "J06.9", "admission_diagnosis_system": "icd-10-cm"},
        "orders": [],
    }


_HTN = ("I10", "2015-03-01")
_DM_NEW = ("E11.9", "2025-10-09")
_RECORDS = [
    _record("2025-08-14T10:18:00", "E1", [_HTN]),
    _record("2025-10-08T10:26:00", "E2", [_HTN]),
    _record("2026-03-24T02:30:00", "E3", [_HTN, _DM_NEW]),
    _record("2026-05-07T09:30:00", "E4", [_HTN, _DM_NEW]),
]


def _recorded(rec: dict, first_seen: dict[str, str]) -> dict[str, str]:
    out = {}
    for c in _build_conditions(rec, "P1", "US", first_seen):
        if any(cat.get("coding", [{}])[0].get("code") == "problem-list-item" for cat in c.get("category", [])):
            out[c["code"]["coding"][0]["code"]] = c["recordedDate"]
    return out


def test_first_seen_is_kept_per_condition_code() -> None:
    first = _first_seen_by_patient(iter(_RECORDS))["P1"]
    assert first[""] == "2025-08-14T10:18:00"
    assert first["I10"] == "2025-08-14T10:18:00"
    assert first["E11.9"] == "2026-03-24T02:30:00"


def test_a_condition_diagnosed_later_is_recorded_at_its_first_record() -> None:
    first = _first_seen_by_patient(iter(_RECORDS))["P1"]
    dates = _recorded(_RECORDS[3], first)
    assert dates["E11.9"].startswith("2026-03-24T02:30:00")
    assert dates["I10"].startswith("2025-08-14T10:18:00")


def test_no_problem_list_condition_is_recorded_before_its_onset() -> None:
    first = _first_seen_by_patient(iter(_RECORDS))["P1"]
    for rec in _RECORDS:
        for code, recorded in _recorded(rec, first).items():
            onset = dict([_HTN, _DM_NEW])[code]
            assert recorded[:10] >= onset, (code, recorded, onset)


def _with_birth(rec: dict, end_date: str) -> dict:
    rec["patient"]["state_periods"] = [
        {"state_type": "pregnancy", "outcome": "delivered", "start_date": "2025-06-01", "end_date": end_date}
    ]
    return rec


def test_a_past_birth_is_recorded_at_the_first_visit_after_the_delivery() -> None:
    recs = [
        _with_birth(_record(s, e, [_HTN]), "2026-02-03")
        for s, e in (
            ("2025-07-01T10:28:00", "E1"),
            ("2026-01-20T09:00:00", "E2"),
            ("2026-02-10T09:15:00", "E3"),
            ("2026-05-01T09:00:00", "E4"),
        )
    ]
    first = _first_seen_by_patient(iter(recs))["P1"]
    assert first["birth:2026-02-03"] == "2026-02-10T09:15:00"
    births = [
        c["recordedDate"]
        for c in _build_conditions(recs[3], "P1", "US", first)
        if str(c.get("id", "")).startswith("cond-past-birth")
    ]
    assert births and all(d.startswith("2026-02-10T09:15:00") for d in births)


def test_a_birth_with_no_later_visit_is_not_yet_history() -> None:
    recs = [
        _with_birth(_record(s, e, [_HTN]), "2026-06-25")
        for s, e in (
            ("2025-07-01T10:28:00", "E1"),
            ("2026-06-03T10:21:00", "E2"),
        )
    ]
    first = _first_seen_by_patient(iter(recs))["P1"]
    assert "birth:2026-06-25" not in first
    for rec in recs:
        ids = [str(c.get("id", "")) for c in _build_conditions(rec, "P1", "US", first)]
        assert not any(i.startswith("cond-past-birth") for i in ids)


def test_without_the_pre_pass_a_past_birth_is_still_emitted() -> None:
    rec = _with_birth(_record("2026-06-03T10:21:00", "E2", [_HTN]), "2026-02-03")
    ids = [str(c.get("id", "")) for c in _build_conditions(rec, "P1", "US", None)]
    assert any(i.startswith("cond-past-birth") for i in ids)


def test_a_record_before_the_delivery_dates_the_birth_after_it() -> None:
    recs = [
        _with_birth(_record(s, e, [_HTN]), "2026-02-03")
        for s, e in (
            ("2025-07-01T10:28:00", "E1"),
            ("2026-02-10T09:15:00", "E2"),
        )
    ]
    first = _first_seen_by_patient(iter(recs))["P1"]
    births = [
        c["recordedDate"]
        for c in _build_conditions(recs[0], "P1", "US", first)
        if str(c.get("id", "")).startswith("cond-past-birth")
    ]
    assert births and all(d.startswith("2026-02-10T09:15:00") for d in births)
