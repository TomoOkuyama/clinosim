"""Observation-aware fallback in Assessment — Issue #1181.

Before the fix, `_compose_chronic_assessment_integrated` emitted the
stub `本日測定なし、次回受診時再評価。` for every chronic condition
not covered by the per-ICD-prefix dispatch (I10 / E10-11 / E78 / N18
/ J44 / J45). In the 2026-09-07 build 87.7% of outpatient SOAP notes
carried this stub. In a random n=300 sample, 100% of those
encounters actually had ≥1 Observation on the same day (mean ~18
Observations). The Assessment therefore contradicted the encounter's
own structured resources.

The fix quotes the today-measured vital signs (and the first two
lab values) in the fallback line instead of asserting "not
measured" whenever any Observation exists.
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
    # A condition with no monitoring lab in the dispatch and no vitals/labs
    # today keeps the honest "本日測定なし" stub.
    ctx = _mk_ctx_with_condition_and_vitals("F32.9", vitals=None, labs=None)
    text = _run(ctx)
    assert "本日測定なし" in text


def test_condition_without_specific_dispatch_but_vitals_present_cites_vitals() -> None:
    # F32.9 (depression) has no per-ICD dispatch; but the encounter has
    # today's vitals. Assessment must not assert "not measured today".
    ctx = _mk_ctx_with_condition_and_vitals(
        "F32.9",
        vitals={"sbp": 118, "dbp": 76, "hr": 72, "temp": 36.5, "spo2": 98},
    )
    text = _run(ctx)
    assert "本日測定なし" not in text
    # Should cite at least one vital
    for token in ("BP", "HR", "T ", "SpO2"):
        if token in text:
            break
    else:
        raise AssertionError(f"expected at least one vital token in {text!r}")


def test_condition_without_specific_dispatch_but_lab_present_cites_lab() -> None:
    labs = [SimpleNamespace(lab_name="AST", value=42, unit="U/L")]
    ctx = _mk_ctx_with_condition_and_vitals("K76.0", vitals=None, labs=labs)
    text = _run(ctx)
    assert "本日測定なし" not in text
    assert "ast" in text.lower() or "AST" in text


def test_condition_without_specific_dispatch_english_fallback() -> None:
    ctx = _mk_ctx_with_condition_and_vitals(
        "F32.9",
        vitals={"sbp": 118, "dbp": 76, "hr": 72, "temp": 36.5, "spo2": 98},
        lang="en",
    )
    text = _run(ctx)
    # EN fallback wording per PR B3
    assert "no measurement today" not in text
    assert "today's measurements" in text.lower() or "measurements" in text.lower()


def test_hypertension_i10_dispatch_still_wins() -> None:
    # I10 with BP present should still fire the HTN dispatch (not the
    # observation-aware fallback). This locks in the "dispatch wins"
    # priority.
    ctx = _mk_ctx_with_condition_and_vitals("I10", vitals={"sbp": 155, "dbp": 95, "hr": 72, "temp": 36.5})
    text = _run(ctx)
    assert "コントロール" in text or "at goal" in text or "poorly controlled" in text
    # And no observation-aware fallback fired for I10
    assert "本日測定" not in text or "コントロール" in text
