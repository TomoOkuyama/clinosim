"""Assessment vital-abnormal handlers — Issue #1183.

Before the fix, `_compose_chronic_assessment_integrated` iterated
only over the patient's chronic conditions. Any abnormal vital
without a matching chronic condition (fever without J18, tachycardia
without I10, hypoxemia without J44/J45) was silently dropped —
tachycardia surfaced in only 2.5% of notes (20/790), hypoxemia in
0% (0/1,890), and fever in only 6.7% (2/30).

Fix: after the condition-dispatch loop, always append vital-abnormal
lines for HR ≥100, SpO2 <95, T ≥38.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _mk_ctx(hr: float | None, spo2: float | None, temp: float | None, lang: str = "ja") -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-1183")
    # No chronic conditions — this is the pure vital-abnormal case
    # (Issue #1183's regression: tachycardia in a healthy patient
    # never showed up in Assessment).
    patient.chronic_conditions = []
    patient.current_medications = []
    patient.age = 55
    patient.sex = "F"
    patient.date_of_birth = date(1970, 1, 1)
    vital = SimpleNamespace(
        systolic_bp=None,
        diastolic_bp=None,
        heart_rate=hr,
        temperature_celsius=temp,
        spo2=spo2,
        respiratory_rate=None,
    )
    encounter = SimpleNamespace(
        encounter_id="enc-1183",
        admission_datetime=datetime(2026, 8, 1, 10, 0),
    )
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[vital],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def _run(ctx: NarrativeContext) -> str:
    gen = TemplateNarrativeGenerator()
    return gen._compose_chronic_assessment_integrated(ctx)


def test_tachycardia_ja_surfaces_hr_line() -> None:
    text = _run(_mk_ctx(hr=108, spo2=None, temp=None, lang="ja"))
    assert "頻脈" in text
    assert "HR 108" in text


def test_tachycardia_en_surfaces_hr_line() -> None:
    text = _run(_mk_ctx(hr=108, spo2=None, temp=None, lang="en"))
    assert "Tachycardia" in text
    assert "HR 108" in text


def test_hypoxemia_ja_surfaces_spo2_line() -> None:
    text = _run(_mk_ctx(hr=None, spo2=88, temp=None, lang="ja"))
    assert "低酸素" in text
    assert "SpO2 88%" in text


def test_severe_hypoxemia_uses_severe_label() -> None:
    text = _run(_mk_ctx(hr=None, spo2=85, temp=None, lang="ja"))
    assert "重度低酸素" in text


def test_hypoxemia_boundary_below_95_fires() -> None:
    text = _run(_mk_ctx(hr=None, spo2=94, temp=None, lang="ja"))
    assert "低酸素" in text


def test_hypoxemia_boundary_at_95_does_not_fire() -> None:
    text = _run(_mk_ctx(hr=None, spo2=95, temp=None, lang="ja"))
    assert "低酸素" not in text


def test_fever_ja_surfaces_temp_line() -> None:
    text = _run(_mk_ctx(hr=None, spo2=None, temp=38.5, lang="ja"))
    assert "発熱" in text
    assert "T 38.5°C" in text


def test_fever_en_surfaces_temp_line() -> None:
    text = _run(_mk_ctx(hr=None, spo2=None, temp=38.5, lang="en"))
    assert "Fever" in text
    assert "T 38.5°C" in text


def test_fever_boundary_at_38_fires() -> None:
    text = _run(_mk_ctx(hr=None, spo2=None, temp=38.0, lang="ja"))
    assert "発熱" in text


def test_fever_below_38_does_not_fire() -> None:
    text = _run(_mk_ctx(hr=None, spo2=None, temp=37.9, lang="ja"))
    assert "発熱" not in text


def test_multiple_abnormalities_all_surface() -> None:
    text = _run(_mk_ctx(hr=110, spo2=88, temp=39.0, lang="ja"))
    assert "頻脈" in text
    assert "低酸素" in text
    assert "発熱" in text


def test_no_abnormal_vitals_yields_no_vital_lines() -> None:
    text = _run(_mk_ctx(hr=72, spo2=98, temp=36.6, lang="ja"))
    for word in ("頻脈", "低酸素", "発熱"):
        assert word not in text
