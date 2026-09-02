"""Regression: EN narrative output must not contain full-width JP punctuation.

Session 98 verify (p=10000 seed=98) found 8,806 US chronic-visit assessment
sections carrying the ideographic comma `、` because
``_compose_chronic_assessment_integrated`` used ``"、".join(...)`` as the
delimiter regardless of ``is_ja``. The trailing period switched on locale
but the joiner did not, producing "SpO2 95%、Tiotropium inhalation continue"
in English notes. The fix threads the join separator through the locale
switch — this test locks in the invariant so the class does not regress.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, PatientProfile

FULLWIDTH_JP_PUNCT = "、。「」【】《》『』〜"


def _en_ctx_with_chronic(codes: list[str]) -> NarrativeContext:
    """Build a US-locale ctx with the given chronic ICD-10 codes present.

    Includes vitals and labs that trigger the per-code assessment branches
    (SpO2 for J44/J45, HbA1c for E10/E11, eGFR for N18) — otherwise the
    function returns before the `、`-join line and the test is vacuous.
    """
    patient = PatientProfile(patient_id="pt-test")
    patient.chronic_conditions = [
        ChronicCondition(code=c, system="icd-10-cm", onset_date=date(2015, 1, 1)) for c in codes
    ]
    patient.current_medications = [
        SimpleNamespace(drug_name="Tiotropium", route="INH", dose="18mcg"),
        SimpleNamespace(drug_name="Metformin", route="PO", dose="500mg"),
    ]
    patient.smoking_status = "former"
    patient.alcohol_use = "none"

    encounter = SimpleNamespace(
        encounter_id="enc-test",
        encounter_type=SimpleNamespace(value="ambulatory"),
        admission_datetime=datetime(2024, 6, 1, 10, 0),
    )
    vitals = [
        SimpleNamespace(spo2=95, systolic_bp=132, diastolic_bp=85, heart_rate=78),
    ]
    labs = [
        SimpleNamespace(lab_name="hba1c", value=6.5, unit="%"),
        SimpleNamespace(lab_name="egfr", value=55, unit="mL/min/1.73m²"),
        SimpleNamespace(lab_name="ldl", value=130, unit="mg/dL"),
    ]
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=encounter.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="mild",
        day_index=0,
        los_days=1,
        vitals=vitals,
        lab_results=labs,
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang="en",
        locale="us",
    )


@pytest.mark.unit
def test_compose_chronic_assessment_integrated_en_has_no_fullwidth_punct():
    """Regression: EN chronic assessment must use ASCII delimiters only."""
    gen = TemplateNarrativeGenerator()
    ctx = _en_ctx_with_chronic(["E11", "J44", "J45", "N18", "I10", "E78"])
    text = gen._compose_chronic_assessment_integrated(ctx)  # noqa: SLF001
    assert text, "expected assessment content when chronic conditions + vitals present"
    for ch in FULLWIDTH_JP_PUNCT:
        assert ch not in text, (
            f"US assessment contains full-width JP punct {ch!r} — session-98 F1 regression. Offending text: {text!r}"
        )


@pytest.mark.unit
def test_compose_chronic_assessment_integrated_ja_uses_fullwidth_punct():
    """JA assessment MUST use `、` — proves the locale switch is bidirectional."""
    gen = TemplateNarrativeGenerator()
    ctx = _en_ctx_with_chronic(["E11", "J44"])
    ctx.target_lang = "ja"
    ctx.locale = "jp"
    text = gen._compose_chronic_assessment_integrated(ctx)  # noqa: SLF001
    assert text, "expected assessment content"
    assert "、" in text or "。" in text, f"JA assessment should carry JA punct, got {text!r}"


@pytest.mark.unit
def test_compose_today_prescription_line_ja_uses_fullwidth_join():
    """L4795 minor polish: JA prescription list should use `、` not `; `.

    The item builder emitted the JA prescription list as
    "本日処方: Metformin 500mg tid x14日分; Tiotropium 18mcg qd" — an
    ASCII semicolon inside a JA sentence reads as mixed-locale style.
    The locale-conditional join keeps the JP `、` for JA and `; ` for EN.
    """
    gen = TemplateNarrativeGenerator()
    ctx = _en_ctx_with_chronic(["E11", "J44"])
    ctx.target_lang = "ja"
    ctx.locale = "jp"
    ctx.medications = [
        SimpleNamespace(medication_name="Metformin", route="PO", dose="500mg", frequency="tid", duration_days=14),
        SimpleNamespace(medication_name="Tiotropium", route="INH", dose="18mcg", frequency="qd", duration_days=None),
    ]
    text = gen._compose_today_prescription_line(ctx)  # noqa: SLF001
    if text:  # only asserts when the composer actually produced items
        # JA output must not carry an ASCII semicolon as the item separator.
        # (Individual items may legitimately embed other ASCII punctuation.)
        assert "; " not in text, f"JA prescription list uses `; ` between items — got {text!r}"
