"""Issue #3465: the next-visit line states the visit the patient is actually
scheduled for, not an interval invented per encounter."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._interval_events import other_encounters
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 3, 1, 10, 0)


def _other(eid, start, kind="outpatient", visit_type="chronic_followup", cond="hypertension", vax=False):
    return {
        "encounter_id": eid,
        "encounter_type": kind,
        "start": start,
        "end": start,
        "diagnosis_code": "I10",
        "admit_source_encounter_id": "",
        "procedures": [],
        "visit_type": visit_type,
        "visit_condition_id": cond,
        "vaccination": vax,
    }


def _ctx(others, visit_type="chronic_followup", cond="hypertension", code="F32.9", immunizations=None, lang="ja"):
    p = PatientProfile(patient_id="pt-3465")
    p.chronic_conditions = [SimpleNamespace(code=code)]
    p.current_medications = []
    p.age = 60
    p.sex = "M"
    enc = SimpleNamespace(
        encounter_id="ENC-THIS",
        admission_datetime=_NOW,
        discharge_datetime=_NOW,
    )
    return NarrativeContext(
        patient=p,
        encounter=enc,
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp",
        visit_type=visit_type,
        visit_condition_id=cond,
        immunizations=immunizations or [],
        interval_encounters=others,
    )


def _line(ctx):
    return TemplateNarrativeGenerator()._compose_follow_up_line(ctx)


def test_next_chronic_visit_of_the_same_condition_gives_the_real_days() -> None:
    ctx = _ctx(
        [
            _other("A", "2026-03-12T10:00:00"),
            _other("B", "2026-04-20T10:00:00"),
            _other("C", "2026-03-05T10:00:00", cond="diabetes"),
            _other("D", "2026-02-20T10:00:00"),
        ]
    )
    assert "11日後" in _line(ctx)
    assert "Next visit: in 11 days" in _line(_ctx(ctx.interval_encounters, lang="en"))


def test_actual_next_visit_wins_over_the_chronic_schedule() -> None:
    ctx = _ctx([_other("A", "2026-03-12T10:00:00")], code="I10")
    assert "11日後" in _line(ctx) and "か月後" not in _line(ctx)


def test_emergency_or_other_series_visit_is_not_the_next_visit() -> None:
    ctx = _ctx([_other("E", "2026-03-04T10:00:00", kind="emergency", visit_type="")], code="I10")
    assert "4か月後" in _line(ctx)


def test_no_next_visit_and_no_schedule_states_none() -> None:
    assert _line(_ctx([_other("P", "2026-02-01T10:00:00")])) == ""


def test_vaccination_visit_reads_the_next_vaccination_visit() -> None:
    ctx = _ctx(
        [
            _other("V2", "2026-03-06T10:00:00", visit_type="", cond="", vax=True),
            _other("W", "2026-03-03T10:00:00", visit_type="pediatric_visit", cond="well_child_infant"),
        ],
        visit_type="",
        cond="",
        immunizations=[SimpleNamespace(encounter_id="ENC-THIS")],
    )
    assert "5日後" in _line(ctx)


def test_other_encounters_carry_the_visit_series() -> None:
    record = {
        "condition_event": {"visit_type": "chronic_followup", "visit_condition_id": "hypertension"},
        "immunizations": [{"encounter_id": "ENC-VAX-1"}],
        "encounters": [
            {"encounter_id": "ENC-1", "encounter_type": "outpatient", "admission_datetime": "2026-03-01T10:00:00"},
            {"encounter_id": "ENC-VAX-1", "encounter_type": "outpatient", "admission_datetime": "2026-03-02T10:00:00"},
        ],
    }
    first, second = other_encounters([record])
    assert (first["visit_type"], first["visit_condition_id"], first["vaccination"]) == (
        "chronic_followup",
        "hypertension",
        False,
    )
    assert (second["visit_type"], second["visit_condition_id"], second["vaccination"]) == ("", "", True)


def test_vaccination_visits_appended_to_the_own_record_are_other_encounters(tmp_path) -> None:
    from clinosim.modules.document.narrative.passes import NarrativePass

    own = {
        "patient": {"patient_id": "POP-1"},
        "immunizations": [{"encounter_id": "ENC-VAX-POP-1-b"}],
        "encounters": [
            {
                "encounter_id": "ENC-POP-1-a",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-03-01T10:00:00",
            },
            {
                "encounter_id": "ENC-VAX-POP-1-b",
                "encounter_type": "outpatient",
                "admission_datetime": "2026-03-20T10:00:00",
            },
        ],
    }
    got = NarrativePass._patient_other_encounters(str(tmp_path), "ENC-POP-1-a.json", own)
    assert {o["encounter_id"] for o in got} == {"ENC-POP-1-a", "ENC-VAX-POP-1-b"}
    assert [o["vaccination"] for o in got] == [False, True]
