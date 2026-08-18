"""Issue #780 (part of META #774): outpatient SOAP composition falls back to
patient-state-derived content when the encounter protocol has no
`outpatient_soap_template`.

Pre-fix, every SOAP section rendered a static string ("特記事項なし" /
"経過観察中" / "治療継続") when no template was authored, making 6 months of
follow-up SOAP notes byte-identical across the same patient. The fallback
paths tested here derive:

- O: vital-signs line (BP / HR / RR / SpO2 / T) from ctx.vitals
- A: chronic-condition list from patient.chronic_conditions
- P: current-medications list from patient.current_medications
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.template_generator import (
    _GENERIC_ASSESSMENT_JA,
    _GENERIC_FALLBACK_JA,
    _GENERIC_PLAN_JA,
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit


def _ctx(
    lang: str = "ja",
    vitals: list | None = None,
    chronic_conditions: list | None = None,
    current_medications: list | None = None,
    document_type: DocumentType = DocumentType.OUTPATIENT_SOAP,
):
    """Build a minimal NarrativeContext-shaped SimpleNamespace for SOAP
    fallback tests. Only the fields the outpatient SOAP builders read are
    populated; encounter_protocol is None so the fallback paths trigger."""
    patient = SimpleNamespace(
        chronic_conditions=chronic_conditions or [],
        current_medications=current_medications or [],
    )
    return SimpleNamespace(
        patient=patient,
        encounter=SimpleNamespace(),
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=0,
        los_days=0,
        vitals=vitals or [],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=document_type,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        materialized_facts=[],
        section_facts={},
        shift="",
        discharge_medications=[],
    )


def test_objective_falls_back_to_vital_signs_line_ja():
    """O section: with no template but vitals present, render BP/HR/RR/SpO2 line."""
    ctx = _ctx(
        vitals=[
            SimpleNamespace(
                systolic_bp=132,
                diastolic_bp=78,
                heart_rate=72,
                respiratory_rate=16,
                spo2=98.0,
                temperature_celsius=None,
            )
        ]
    )
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_objective(ctx)
    assert "BP 132/78 mmHg" in text
    assert "HR 72" in text
    assert "SpO2 98%" in text
    assert facts == ["ctx.vitals"]


def test_objective_falls_back_to_static_when_no_vitals():
    """O section preserves generic fallback when neither template nor vitals."""
    ctx = _ctx(vitals=[])
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_objective(ctx)
    assert text == _GENERIC_FALLBACK_JA
    assert facts == []


def test_assessment_falls_back_to_chronic_conditions_line():
    """A section with chronic conditions.

    v9 (2026-08-17) semantics: when the primary chronic condition matches
    the chronic SOAP registry (I10 → 本態性高血圧), the disease-specific
    template supplies the Assessment. Otherwise the per-chronic
    integrated line composes from ctx.patient.chronic_conditions +
    today's vitals/labs. Either way, the section MUST reference the
    primary condition — the old「既往症フォローアップ」flat list is no
    longer the intended output.
    """
    ctx = _ctx(
        chronic_conditions=[
            SimpleNamespace(code="I10"),
            SimpleNamespace(code="E11.9"),
        ]
    )
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_assessment(ctx)
    # Primary chronic (I10) MUST surface either via chronic registry
    # ("本態性高血圧") or via per-condition assessment integration.
    assert "本態性" in text or "高血圧" in text or "I10" in text


def test_assessment_static_fallback_when_no_conditions():
    ctx = _ctx(chronic_conditions=[])
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_assessment(ctx)
    assert text == _GENERIC_ASSESSMENT_JA
    assert facts == []


def test_plan_falls_back_to_current_medications():
    """P section: with no template, summarize current medications."""
    ctx = _ctx(
        current_medications=[
            SimpleNamespace(drug_name="アムロジピン"),
            SimpleNamespace(drug_name="メトホルミン"),
        ]
    )
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_plan(ctx)
    assert "継続処方" in text
    assert "アムロジピン" in text
    assert "メトホルミン" in text
    # v9 (2026-08-17): Plan is now multi-line — continuation Rx + follow-up
    # sentinel. Fact list carries current_medications first plus the
    # follow-up planner (see `_compose_follow_up_line`).
    assert "ctx.patient.current_medications" in facts


def test_plan_truncates_long_medication_list():
    """P section: v9 widened truncate 5 → 10 (polypharmacy is the geriatric
    outpatient norm; the old "他 3 剤" boundary lost too much info).
    """
    ctx = _ctx(
        current_medications=[SimpleNamespace(drug_name=f"薬{i}") for i in range(12)],
    )
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_plan(ctx)
    # 12 drugs → 10 shown + "他 2 剤"
    assert "他 2 剤" in text


def test_plan_static_fallback_when_no_meds():
    """v9 (2026-08-17): even without current_medications, Plan now emits a
    follow-up sentinel line rather than the bare _GENERIC_PLAN_JA."""
    ctx = _ctx(current_medications=[])
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_plan(ctx)
    # Follow-up planning phrase must appear (Rx list is empty)
    assert "次回外来" in text or text == _GENERIC_PLAN_JA


def test_english_locale_vital_signs_line():
    """EN locale variant of the O-section fallback (units in bpm/mmHg)."""
    ctx = _ctx(
        lang="en",
        vitals=[
            SimpleNamespace(
                systolic_bp=120,
                diastolic_bp=80,
                heart_rate=68,
                respiratory_rate=None,
                spo2=None,
                temperature_celsius=None,
            )
        ],
    )
    gen = TemplateNarrativeGenerator()
    text, facts = gen._build_outpatient_objective(ctx)
    assert "BP 120/80 mmHg" in text
    assert "HR 68 bpm" in text
