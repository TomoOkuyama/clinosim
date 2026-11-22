"""A bedside procedure note states what the record holds (Issue #3550, narrative part).

Consent follows urgency and the patient's consciousness at the procedure time,
completion is stated plainly (nothing is claimed when no outcome is recorded),
and an insertion site is named only when the record has one.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
    build_pn_consent,
    build_pn_course,
    build_pn_procedure_name,
)
from clinosim.types.document import DocumentType, NarrativeContext

_STD_JA = "文書で説明し、同意を得た"
_STD_EN = "written consent was obtained"


def _proc(**kw) -> dict:
    base = {
        "procedure_id": "P1",
        "procedure_type": "intubation",
        "procedure_code": "31500",
        "procedure_code_us": "31500",
        "procedure_code_jp": "J044",
        "start_datetime": "2026-03-23T15:17:00",
        "duration_minutes": 30,
        "outcome_code": "385669000",
        "body_site_code": "74262004",
        "approach": "",
    }
    base.update(kw)
    return base


def _vital(ts: str, level: str) -> dict:
    return {"timestamp": ts, "consciousness_level": level}


def _ctx(lang: str, proc: dict, *, priority: str = "", vitals: list | None = None) -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(patient_id="p", sex="M", chronic_conditions=[]),
        encounter=SimpleNamespace(
            encounter_id="e", encounter_type=SimpleNamespace(value="inpatient"), priority=priority
        ),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=3,
        los_days=7,
        vitals=vitals or [],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[proc],
        prior_procedures=[],
        allergies=[],
        document_type=DocumentType.PROCEDURE_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        related_procedure_id=proc["procedure_id"],
    )


def _consent(lang, proc, **kw) -> str:
    return build_pn_consent(None, _ctx(lang, proc, **kw))[0]


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_emergency_intubation_does_not_claim_written_consent(lang):
    text = _consent(lang, _proc(), vitals=[_vital("2026-03-23T14:00:00", "U")])
    assert (_STD_JA if lang == "ja" else _STD_EN) not in text
    assert ("推定同意" if lang == "ja" else "implied consent") in text


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_reduced_consciousness_uses_last_reading_before_the_procedure(lang):
    proc = _proc(procedure_type="central_line", procedure_code_jp="G005-2", procedure_code_us="36556")
    reduced = _consent(lang, proc, vitals=[_vital("2026-03-23T10:00:00", "A"), _vital("2026-03-23T15:00:00", "P")])
    assert (_STD_JA if lang == "ja" else _STD_EN) not in reduced
    # A later reading (after the start) must not count; the last one before is alert.
    alert = _consent(
        lang,
        proc,
        vitals=[_vital("2026-03-23T15:00:00", "A"), _vital("2026-03-23T16:00:00", "U")],
    )
    assert (_STD_JA if lang == "ja" else _STD_EN) in alert


def test_emergency_encounter_priority_states_emergency_consent():
    proc = _proc(procedure_type="central_line")
    text = _consent("ja", proc, priority="EM", vitals=[_vital("2026-03-23T15:00:00", "A")])
    assert _STD_JA not in text
    assert "緊急" in text


def test_elective_alert_patient_keeps_standard_consent_line():
    proc = _proc(procedure_type="urinary_catheter", procedure_code_jp="J063")
    assert _STD_JA in _consent("ja", proc, vitals=[_vital("2026-03-23T15:00:00", "A")])


@pytest.mark.parametrize(("lang", "needle"), [("ja", "手技は完遂した"), ("en", "The procedure was completed")])
def test_completion_is_stated_plainly(lang, needle):
    text = build_pn_course(None, _ctx(lang, _proc()))[0]
    assert needle in text
    assert "問題なく" not in text and "without issue" not in text


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_no_outcome_recorded_claims_no_completion(lang):
    text = build_pn_course(None, _ctx(lang, _proc(outcome_code="")))[0]
    assert "完遂" not in text and "completed" not in text


def test_central_line_without_site_names_none():
    proc = _proc(procedure_type="central_line", procedure_code_jp="G005-2", body_site_code="113257007")
    text = build_pn_procedure_name(None, _ctx("ja", proc))[0]
    assert "循環器系" not in text and "穿刺部位" not in text


def test_central_line_with_a_recorded_site_names_it():
    proc = _proc(procedure_type="central_line", procedure_code_jp="G005-2", body_site_code="421466002")
    text = build_pn_procedure_name(None, _ctx("ja", proc))[0]
    assert "穿刺部位" in text
    en = build_pn_procedure_name(None, _ctx("en", proc))[0]
    assert "site:" in en
