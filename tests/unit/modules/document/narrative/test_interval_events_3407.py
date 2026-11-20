"""Issue #3407: an outpatient note states the admission or emergency visit
since the previous visit, and not "no exacerbation since the last visit" when
there was one."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative._interval_events import interval_events, other_encounters
from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_subjective,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_document_data_yaml
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_THIS = "ENC-T-3407-C"


def _enc(eid: str, kind: str, start: str, end: str | None = None, dx: str = "J44", admit_src: str = "") -> dict:
    return {
        "encounter_id": eid,
        "encounter_type": kind,
        "start": start,
        "end": end or start,
        "diagnosis_code": dx,
        "admit_source_encounter_id": admit_src,
        "procedures": [],
    }


_PREV = _enc("ENC-T-3407-A", "outpatient", "2026-01-05T10:00:00")
_STAY = _enc("ENC-T-3407-B", "inpatient", "2026-02-01T09:00:00", "2026-03-01T10:00:00", dx="S72.0")
_STAY["procedures"] = [
    {"procedure_type": "hemiarthroplasty", "anesthesia_type": "general", "start_datetime": "2026-02-02T09:00:00"},
    {"procedure_type": "arterial_line", "anesthesia_type": "none", "start_datetime": "2026-02-02T08:00:00"},
]


def _ctx(others: list[dict], lang: str = "ja", country: str = "JP", when: str = "2026-03-03T10:00:00"):
    record = {
        "patient": {
            "patient_id": "POP-T-3407",
            "sex": "M",
            "age": 78,
            "date_of_birth": "1948-01-01",
            "chronic_conditions": [{"code": "J44"}],
        },
        "encounters": [
            {
                "encounter_id": _THIS,
                "encounter_type": "outpatient",
                "admission_datetime": when,
                "discharge_datetime": when,
                "chief_complaint": "",
            }
        ],
        "vital_signs": [{"timestamp": when, "heart_rate": 80, "systolic_bp": 128, "diastolic_bp": 76}],
        "condition_event": {
            "condition_type": "chronic_followup",
            "ground_truth_diseases": ["J44"],
            "visit_type": "chronic_followup",
            "visit_condition_id": "J44",
        },
        "clinical_diagnosis": {"admission_diagnosis_code": "J44", "discharge_diagnosis_code": "J44"},
    }
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.OUTPATIENT_SOAP, 0, country)
    ctx.diagnoses = [record["clinical_diagnosis"]]
    ctx.interval_encounters = others
    return ctx


def _subjective(ctx) -> str:
    return build_outpatient_subjective(TemplateNarrativeGenerator(), ctx)[0]


def test_admission_since_the_last_visit_is_stated_and_the_no_exacerbation_phrase_dropped() -> None:
    text = _subjective(_ctx([_PREV, _STAY]))
    assert "前回受診以降、2026-02-01に" in text and "28日間入院" in text
    assert "を施行" in text and "動脈ライン" not in text
    assert "前回受診以降の増悪エピソードなし" not in text


def test_no_event_keeps_the_no_exacerbation_phrase() -> None:
    text = _subjective(_ctx([_PREV]))
    assert "前回受診以降の増悪エピソードなし" in text and "入院" not in text


def test_second_visit_after_the_event_does_not_restate_it() -> None:
    after = _enc("ENC-T-3407-X", "outpatient", "2026-03-03T10:00:00")
    ctx = _ctx([_PREV, _STAY, after], when="2026-04-15T10:00:00")
    assert interval_events(ctx) == []
    assert "前回受診以降の増悪エピソードなし" in _subjective(ctx)


def test_emergency_visit_is_stated_and_one_inside_a_stay_is_folded() -> None:
    ed = _enc("ENC-T-3407-E", "emergency", "2026-02-10T11:00:00", dx="R07.4")
    ctx = _ctx([_PREV, ed])
    assert "救急外来を受診" in _subjective(ctx)
    inside = _ctx([_PREV, _STAY, ed])
    assert [e["encounter_id"] for e in interval_events(inside)] == [_STAY["encounter_id"]]
    led = _enc("ENC-T-3407-L", "emergency", "2026-01-31T20:00:00")
    stay = {**_STAY, "admit_source_encounter_id": led["encounter_id"]}
    assert [e["encounter_id"] for e in interval_events(_ctx([_PREV, led, stay]))] == [stay["encounter_id"]]


def test_event_before_or_at_the_previous_visit_is_outside_the_interval() -> None:
    old = _enc("ENC-T-3407-O", "inpatient", "2025-12-01T09:00:00", "2026-01-05T10:00:00")
    assert interval_events(_ctx([_PREV, old])) == []


def test_without_a_previous_visit_the_lookback_applies() -> None:
    far = _enc("ENC-T-3407-F", "inpatient", "2024-06-01T09:00:00", "2024-06-10T09:00:00")
    assert interval_events(_ctx([far])) == []
    assert [e["encounter_id"] for e in interval_events(_ctx([_STAY]))] == [_STAY["encounter_id"]]


def test_english_note_states_the_admission() -> None:
    text = _subjective(_ctx([_PREV, _STAY], lang="en", country="US"))
    assert "Since the last visit, admitted on 2026-02-01" in text and "for 28 days" in text


def test_other_encounters_reads_structural_records() -> None:
    rec = {
        "encounters": [
            {
                "encounter_id": "E1",
                "encounter_type": "inpatient",
                "admission_datetime": "2026-02-01T09:00:00",
                "discharge_datetime": "2026-02-05T09:00:00",
            }
        ],
        "clinical_diagnosis": {"admission_diagnosis_code": "I50.9", "discharge_diagnosis_code": "I50.1"},
        "procedures": [{"procedure_type": "x", "anesthesia_type": "general"}],
    }
    (out,) = other_encounters([rec])
    assert (out["encounter_type"], out["diagnosis_code"], out["end"]) == ("inpatient", "I50.1", "2026-02-05T09:00:00")
    assert out["procedures"][0]["anesthesia_type"] == "general"


def test_the_phrase_is_carried_by_no_interval_event_only() -> None:
    reg = load_document_data_yaml("chronic_soap_templates.yaml")
    for code, entry in reg.items():
        assert "前回受診以降" not in entry["subjective"]["ja"], code
    assert reg["J44"]["no_interval_event"]["ja"] == "前回受診以降の増悪エピソードなし。"
