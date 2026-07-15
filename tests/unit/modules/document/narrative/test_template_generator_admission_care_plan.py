"""Tests for TemplateNarrativeGenerator admission_care_plan sections (chain 2).

Mirrors the fixture style of test_template_generator_alpha2.py — SimpleNamespace
for encounter/protocol-shaped objects (exercises the _o() dict/dataclass dual
access path), dict for ClinicalDiagnosis-shaped objects.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

_ACP_SECTIONS = (
    "ward_and_room",
    "other_staff",
    "diagnosis",
    "symptoms",
    "treatment_plan",
    "test_schedule",
    "surgery_schedule",
    "estimated_los",
    "special_nutrition_management",
    "other_plans",
)


def _make_spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_key="admission_care_plan",
        loinc_code="18776-5",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="admission_once",
        composition_sections=_ACP_SECTIONS,
        encounter_types_supported=("inpatient", "icu"),
        stage2_strategy="template_only",
    )


def _make_encounter(
    ward_id: str = "4W",
    bed_number: str = "401-2",
    primary_nurse_id: str = "",
) -> Any:
    return SimpleNamespace(
        encounter_id="enc-acp-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
        ward_id=ward_id,
        bed_number=bed_number,
        primary_nurse_id=primary_nurse_id,
    )


def _make_diagnosis(admission_diagnosis_code: str = "J18.9") -> Any:
    return SimpleNamespace(
        admission_diagnosis_code=admission_diagnosis_code,
        admission_diagnosis_system="icd-10",
        discharge_diagnosis_code="",
        discharge_diagnosis_system="",
    )


def _make_procedure(category_code: str = "387713003", procedure_type: str = "appendectomy") -> Any:
    return SimpleNamespace(
        procedure_type=procedure_type,
        category_code=category_code,
        start_datetime=datetime(2026, 7, 2, 9, 0),
    )


def _make_disease_protocol(target_los: dict[str, Any]) -> Any:
    return SimpleNamespace(target_los=target_los)


def _make_ctx(
    encounter: Any = None,
    diagnoses: list[Any] | None = None,
    lab_results: list[Any] | None = None,
    procedures: list[Any] | None = None,
    los_days: int = 7,
    target_lang: str = "ja",
    locale: str = "jp",
    disease_protocol: Any = None,
    severity: str = "moderate",
) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-acp-test"),
        encounter=encounter or _make_encounter(),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=disease_protocol,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity=severity,
        day_index=0,
        los_days=los_days,
        vitals=[],
        lab_results=lab_results or [],
        medications=[],
        diagnoses=diagnoses or [],
        procedures=procedures or [],
        allergies=[],
        document_type=DocumentType.ADMISSION_CARE_PLAN,
        target_lang=target_lang,
        locale=locale,
    )


def test_admission_care_plan_returns_all_10_sections_non_empty() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis()])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in _ACP_SECTIONS:
        assert section in out.sections, f"section {section!r} missing"
        assert out.sections[section].strip() != "", f"section {section!r} is empty"


def test_admission_care_plan_jp_has_japanese_text() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis()], target_lang="ja", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    all_text = " ".join(out.sections.values())
    has_jp = any("぀" <= c <= "ヿ" or "一" <= c <= "鿿" for c in all_text)
    assert has_jp, f"admission_care_plan sections contain no Japanese text: {all_text[:300]!r}"


def test_admission_care_plan_en_no_crash() -> None:
    """JP-only doc type is never rendered in en in production, but the
    builder pattern in this file always supports both languages defensively."""
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis()], target_lang="en", locale="us")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section in _ACP_SECTIONS:
        assert out.sections[section].strip() != ""


def test_ward_and_room_includes_ward_and_bed() -> None:
    spec = _make_spec()
    enc = _make_encounter(ward_id="4W", bed_number="401-2")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "4W" in out.sections["ward_and_room"]
    assert "401-2" in out.sections["ward_and_room"]


def test_other_staff_includes_primary_nurse_when_set() -> None:
    spec = _make_spec()
    enc = _make_encounter(primary_nurse_id="nurse-RN-001")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "nurse-RN-001" in out.sections["other_staff"]


def test_other_staff_fallback_when_no_nurse() -> None:
    spec = _make_spec()
    enc = _make_encounter(primary_nurse_id="")
    ctx = _make_ctx(encounter=enc)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["other_staff"].strip() != ""


def test_diagnosis_resolves_admission_code_via_code_lookup() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[_make_diagnosis(admission_diagnosis_code="J18.9")])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "J18.9" in out.sections["diagnosis"]


def test_diagnosis_falls_back_to_chief_complaint_when_no_diagnoses() -> None:
    spec = _make_spec()
    ctx = _make_ctx(diagnoses=[])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["diagnosis"].strip() != ""


def test_surgery_schedule_lists_surgical_procedure() -> None:
    spec = _make_spec()
    proc = _make_procedure(category_code="387713003", procedure_type="appendectomy")
    ctx = _make_ctx(procedures=[proc])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "appendectomy" in out.sections["surgery_schedule"]


def test_surgery_schedule_excludes_non_surgical_procedure() -> None:
    spec = _make_spec()
    proc = _make_procedure(category_code="103693007", procedure_type="ct_scan")
    ctx = _make_ctx(procedures=[proc])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "ct_scan" not in out.sections["surgery_schedule"]


def test_surgery_schedule_none_planned_when_no_procedures() -> None:
    spec = _make_spec()
    ctx = _make_ctx(procedures=[])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.sections["surgery_schedule"].strip() != ""


def test_estimated_los_falls_back_to_ctx_los_days_without_disease_protocol() -> None:
    """No disease_protocol (e.g. unknown-condition path) -> fall back to the
    realized ctx.los_days (adv-1: only a fallback now, not the primary source)."""
    spec = _make_spec()
    ctx = _make_ctx(los_days=12, disease_protocol=None)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "12" in out.sections["estimated_los"]


def test_estimated_los_uses_disease_protocol_target_los_mean_when_available() -> None:
    """adv-1 finding: estimated_los must be a genuine at-admission PREDICTION
    (disease_protocol.target_los[country][severity].mean), not the realized
    ctx.los_days — using the realized LOS made the "estimate" tautologically
    100% accurate, which is unrealistic. 15 (target_los mean) must differ from
    and take precedence over los_days=7 (the realized LOS) here."""
    spec = _make_spec()
    proto = _make_disease_protocol(target_los={"japan": {"moderate": {"mean": 15, "sd": 3, "min": 8, "max": 25}}})
    ctx = _make_ctx(los_days=7, disease_protocol=proto, severity="moderate", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "15" in out.sections["estimated_los"]
    assert "7" not in out.sections["estimated_los"]


def test_estimated_los_falls_back_when_severity_not_in_target_los() -> None:
    """disease_protocol present but target_los has no entry for ctx.severity
    -> fall back to ctx.los_days rather than crashing or emitting a blank."""
    spec = _make_spec()
    proto = _make_disease_protocol(target_los={"japan": {"mild": {"mean": 5, "sd": 1, "min": 3, "max": 8}}})
    ctx = _make_ctx(los_days=9, disease_protocol=proto, severity="severe", locale="jp")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "9" in out.sections["estimated_los"]


def test_special_nutrition_management_is_always_no() -> None:
    """MVP decision (spec §3b): hardcoded 無 pending a future nutrition subsystem."""
    spec = _make_spec()
    ctx = _make_ctx()
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert "無" in out.sections["special_nutrition_management"]
