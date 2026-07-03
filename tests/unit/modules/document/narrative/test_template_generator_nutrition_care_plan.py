"""Tests for TemplateNarrativeGenerator nutrition_care_plan sections (chain 2).

Mirrors tests/unit/modules/document/narrative/test_template_generator_admission_care_plan.py.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

_NCP_SECTIONS = (
    "ward_and_physician", "dietitian", "nutrition_risk", "nutrition_assessment",
    "nutrition_goals", "nutrition_supply", "dysphagia_diet", "dietary_content",
    "nutrition_counseling", "other_issues", "reassessment_timing", "discharge_evaluation",
)


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="nutrition_care_plan",
        loinc_code="80791-7",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="admission_once_los_gt_7",
        composition_sections=_NCP_SECTIONS,
        encounter_types_supported=("inpatient", "icu"),
        stage2_strategy="template_only",
    )


def _make_encounter(ward_id: str = "4W", attending_physician_id: str = "dr-ncp-001") -> Any:
    return SimpleNamespace(
        encounter_id="enc-ncp-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        ward_id=ward_id,
        attending_physician_id=attending_physician_id,
    )


def _make_patient(bmi: float = 22.5, weight_kg: float = 65.0) -> PatientProfile:
    patient = PatientProfile(patient_id="pt-ncp-test")
    patient.bmi = bmi
    patient.weight_kg = weight_kg
    return patient


def _make_ctx(
    encounter: Any = None,
    patient: Any = None,
    target_lang: str = "ja",
    locale: str = "jp",
) -> NarrativeContext:
    return NarrativeContext(
        patient=patient or _make_patient(),
        encounter=encounter or _make_encounter(),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=10,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.NUTRITION_CARE_PLAN,
        target_lang=target_lang,
        locale=locale,
    )


def test_nutrition_care_plan_returns_all_12_sections_non_empty() -> None:
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in _NCP_SECTIONS:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != "", f"section {section!r} is empty"


def test_nutrition_care_plan_jp_has_japanese_text() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, f"nutrition_care_plan sections contain no Japanese text: {all_text[:300]!r}"


def test_nutrition_care_plan_en_no_crash() -> None:
    spec = _make_spec()
    ctx = _make_ctx(target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in _NCP_SECTIONS:
        assert out.sections[section].strip() != ""


def test_ward_and_physician_includes_ward_and_physician_id() -> None:
    spec = _make_spec()
    enc = _make_encounter(ward_id="6S", attending_physician_id="dr-ncp-999")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "6S" in out.sections["ward_and_physician"]
    assert "dr-ncp-999" in out.sections["ward_and_physician"]


def test_nutrition_risk_low_for_low_bmi() -> None:
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(bmi=17.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "低栄養" in out.sections["nutrition_risk"]


def test_nutrition_risk_normal_for_mid_bmi() -> None:
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(bmi=22.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "22.0" in out.sections["nutrition_risk"]


def test_nutrition_risk_over_for_high_bmi() -> None:
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(bmi=27.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "過栄養" in out.sections["nutrition_risk"]


def test_nutrition_supply_computes_energy_and_protein_from_weight() -> None:
    """weight_kg=60.0 -> energy=round(60*27.5)=1650, protein=round(60*1.1,1)=66.0"""
    spec = _make_spec()
    ctx = _make_ctx(patient=_make_patient(weight_kg=60.0))
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "1650" in out.sections["nutrition_supply"]
    assert "66.0" in out.sections["nutrition_supply"]
    assert "経口" in out.sections["nutrition_supply"]


def test_dysphagia_diet_fixed_none() -> None:
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "なし" in out.sections["dysphagia_diet"]


def test_discharge_evaluation_is_pending_placeholder() -> None:
    """Genuinely unknowable at plan-creation time (design spec §2, row 10)."""
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "退院時" in out.sections["discharge_evaluation"]
