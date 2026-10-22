"""Observation-aware fallback in Assessment — Issue #1181 (updated by #1776).

Issue #1181's original fix cited today-measured vitals in the Assessment
fallback so the note did not contradict the Objective section's
observations by claiming "not measured". Issue #1776 strengthens that
contract: the Assessment fallback must NOT re-quote the Objective-section
vitals at all AND must not emit the "defer focused review" boilerplate
that saturated 74% of populated narratives. The new structured-data
fallback uses the chronic condition's ``stage`` (populated by the
longitudinal engine as of #1753) or a bare "noted on problem list; no
acute change" stub.

The #1181 spirit — do not contradict Objective by claiming no measurement
when one exists — is preserved: the new fallback neither claims "not
measured" nor contradicts anything. These tests encode the post-#1776
contract.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _mk_ctx_with_condition_and_vitals(
    condition_code: str,
    vitals: dict | None,
    labs: list | None = None,
    lang: str = "ja",
) -> NarrativeContext:
    p = PatientProfile(patient_id="pt-1181")
    p.chronic_conditions = [SimpleNamespace(code=condition_code)]
    p.current_medications = []
    p.age = 70
    p.sex = "F"
    p.date_of_birth = date(1955, 1, 1)
    vital_records = []
    if vitals is not None:
        vital_records.append(
            SimpleNamespace(
                systolic_bp=vitals.get("sbp"),
                diastolic_bp=vitals.get("dbp"),
                heart_rate=vitals.get("hr"),
                temperature_celsius=vitals.get("temp"),
                spo2=vitals.get("spo2"),
                respiratory_rate=vitals.get("rr"),
            )
        )
    enc = SimpleNamespace(encounter_id="enc-1181", admission_datetime=datetime(2026, 8, 1, 10, 0))
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
        vitals=vital_records,
        lab_results=labs or [],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _run(ctx: NarrativeContext) -> str:
    return TemplateNarrativeGenerator()._compose_chronic_assessment_integrated(ctx)


def test_condition_without_specific_dispatch_and_no_measurements_still_stubs() -> None:
    # #1776: a condition with no stage emits the structured "noted on
    # problem list; no acute change" stub (not "本日測定なし" anymore).
    # The spirit of #1181 — do not claim "not measured" and so
    # contradict Objective — is preserved by the new phrase, which
    # neither claims measurement nor its absence.
    ctx = _mk_ctx_with_condition_and_vitals("F32.9", vitals=None, labs=None)
    text = _run(ctx)
    assert "本日測定なし" not in text
    assert "問題リスト" in text or "noted on problem list" in text.lower()


def test_condition_without_specific_dispatch_but_vitals_present_does_not_requote_vitals() -> None:
    # #1776: Assessment must not re-quote Objective-section vitals.
    # #1181 spirit preserved by not claiming "not measured".
    ctx = _mk_ctx_with_condition_and_vitals(
        "F32.9",
        vitals={"sbp": 118, "dbp": 76, "hr": 72, "temp": 36.5, "spo2": 98},
    )
    text = _run(ctx)
    assert "本日測定なし" not in text
    for token in ("BP 118/76", "HR 72", "T 36.5", "SpO2 98"):
        assert token not in text, f"post-#1776 Assessment fallback must not re-quote {token!r}: {text!r}"


def test_condition_without_specific_dispatch_but_lab_present_does_not_requote_lab() -> None:
    # #1776: labs also belong in Objective; Assessment fallback should
    # not re-quote them under the chronic line.
    labs = [SimpleNamespace(lab_name="AST", value=42, unit="U/L")]
    ctx = _mk_ctx_with_condition_and_vitals("K76.0", vitals=None, labs=labs)
    text = _run(ctx)
    assert "本日測定なし" not in text
    assert "ast" not in text.lower() and "AST" not in text, (
        f"post-#1776 Assessment fallback must not re-quote the AST lab value: {text!r}"
    )


def test_condition_without_specific_dispatch_english_fallback() -> None:
    # #1776: EN fallback emits the structured stub, not the "today's
    # measurements ... not condition-specific; defer focused review"
    # boilerplate.
    ctx = _mk_ctx_with_condition_and_vitals(
        "F32.9",
        vitals={"sbp": 118, "dbp": 76, "hr": 72, "temp": 36.5, "spo2": 98},
        lang="en",
    )
    text = _run(ctx)
    assert "no measurement today" not in text
    assert "not condition-specific" not in text
    assert "focused review" not in text.lower()
    assert "noted on problem list" in text.lower() or "no acute change" in text.lower()


def test_hypertension_i10_dispatch_still_wins() -> None:
    # I10 with BP present should still fire the HTN dispatch (not the
    # observation-aware fallback). This locks in the "dispatch wins"
    # priority.
    ctx = _mk_ctx_with_condition_and_vitals("I10", vitals={"sbp": 155, "dbp": 95, "hr": 72, "temp": 36.5})
    text = _run(ctx)
    assert "コントロール" in text or "at goal" in text or "poorly controlled" in text
    # And no observation-aware fallback fired for I10
    assert "本日測定" not in text or "コントロール" in text
