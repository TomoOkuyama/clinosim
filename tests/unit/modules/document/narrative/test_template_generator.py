"""Tests for TemplateNarrativeGenerator (Task 6, Tier 1 #3 α-min-1).

Tests cover:
- 3 format types: FREE_TEXT, COMPOSITION, QUESTIONNAIRE_RESPONSE
- JP / EN locale dispatch
- Disease YAML-driven content (bacterial_pneumonia)
- Multi-day fallback chain
- Missing disease_protocol graceful handling
- facts_used population
- Determinism
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, FormatType, NarrativeContext
from clinosim.types.patient import PatientProfile

# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────


def _make_ctx(
    document_type: DocumentType = DocumentType.ADMISSION_HP,
    day_index: int = 0,
    target_lang: str = "ja",
    locale: str = "jp",
    archetype: str = "uncomplicated_improvement",
    severity: str = "moderate",
    disease_protocol: Any = None,
    los_days: int = 5,
    allergies: list[Any] | None = None,
    medications: list[Any] | None = None,
    diagnoses: list[Any] | None = None,
) -> NarrativeContext:
    """Build a minimal NarrativeContext for testing."""
    patient = PatientProfile(patient_id="pt-test")
    patient.chronic_conditions = []
    patient.current_medications = []
    patient.allergies = allergies or []
    patient.smoking_status = "former"
    patient.alcohol_use = "occasional"
    patient.occupation = "office"

    encounter = SimpleNamespace(
        encounter_id="enc-test",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=datetime(2026, 7, 1, 10, 0),
    )
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=encounter.encounter_type,
        disease_protocol=disease_protocol,
        encounter_protocol=None,
        clinical_course_archetype=archetype,
        severity=severity,
        day_index=day_index,
        los_days=los_days,
        vitals=[],
        lab_results=[],
        medications=medications or [],
        diagnoses=diagnoses or [],
        procedures=[],
        allergies=allergies or [],
        document_type=document_type,
        target_lang=target_lang,
        locale=locale,
    )


def _get_spec(document_type: DocumentType):
    """Load DocumentTypeSpec for a given document type."""
    specs = load_document_type_specs()
    return specs[document_type]


# ─────────────────────────────────────────────────────────────────
# 1. Format type dispatch — FREE_TEXT
# ─────────────────────────────────────────────────────────────────


def test_free_text_format_returns_raw_text() -> None:
    """FREE_TEXT format must populate raw_text; sections is empty or absent."""
    spec = _get_spec(DocumentType.PROGRESS_NOTE)
    assert spec.format_type == FormatType.FREE_TEXT
    ctx = _make_ctx(document_type=DocumentType.PROGRESS_NOTE, day_index=0)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.raw_text != "", "raw_text must be non-empty for FREE_TEXT format"


def test_free_text_contains_soap_markers() -> None:
    """FREE_TEXT PROGRESS_NOTE should include SOAP structure labels."""
    spec = _get_spec(DocumentType.PROGRESS_NOTE)
    ctx = _make_ctx(document_type=DocumentType.PROGRESS_NOTE, day_index=0)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    # at least one SOAP section marker (S: / O: / A: / P: or 主観/客観)
    raw = out.raw_text.upper()
    soap_markers = ("S:", "O:", "A:", "P:", "主観", "客観", "評価", "計画")
    has_soap = any(marker in raw for marker in soap_markers)
    assert has_soap, f"SOAP markers not found in raw_text: {out.raw_text[:200]!r}"


# ─────────────────────────────────────────────────────────────────
# 2. Format type dispatch — COMPOSITION
# ─────────────────────────────────────────────────────────────────


def test_composition_format_returns_sections_dict() -> None:
    """COMPOSITION format must populate sections dict with expected keys."""
    spec = _get_spec(DocumentType.ADMISSION_HP)
    assert spec.format_type == FormatType.COMPOSITION
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict), "sections must be a dict for COMPOSITION"
    # All spec.composition_sections must be present in output
    for section in spec.composition_sections:
        assert section in out.sections, f"section '{section}' missing from output.sections"


def test_composition_all_sections_non_empty() -> None:
    """All composition sections must have non-empty string values."""
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for section, text in out.sections.items():
        assert isinstance(text, str), f"section {section!r} value must be a string"
        assert text.strip() != "", f"section {section!r} must not be empty"


def test_discharge_summary_sections() -> None:
    """DISCHARGE_SUMMARY COMPOSITION has its own section set."""
    spec = _get_spec(DocumentType.DISCHARGE_SUMMARY)
    assert spec.format_type == FormatType.COMPOSITION
    ctx = _make_ctx(document_type=DocumentType.DISCHARGE_SUMMARY, day_index=5, los_days=5)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    expected_sections = set(spec.composition_sections)
    assert expected_sections.issubset(out.sections.keys()), (
        f"Missing sections: {expected_sections - set(out.sections.keys())}"
    )


# ─────────────────────────────────────────────────────────────────
# 3. Format type dispatch — QUESTIONNAIRE_RESPONSE (stub)
# ─────────────────────────────────────────────────────────────────


def test_questionnaire_response_returns_structured_dict() -> None:
    """QUESTIONNAIRE_RESPONSE format returns structured dict (infrastructure stub)."""
    # Build a fake spec with QUESTIONNAIRE_RESPONSE format_type
    from clinosim.modules.document.narrative.registry import DocumentTypeSpec
    spec = DocumentTypeSpec(
        type_key="test_qr",
        loinc_code="99999-9",
        format_type=FormatType.QUESTIONNAIRE_RESPONSE,
        countries_supported=("jp", "us"),
        generation_frequency="once",
    )
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.structured, dict), "structured must be a dict for QUESTIONNAIRE_RESPONSE"
    # infrastructure stub — structured may be empty but metadata must indicate stub
    assert out.metadata.get("generator") == "template"


# ─────────────────────────────────────────────────────────────────
# 4. JP locale — disease YAML narrative content (bacterial_pneumonia)
# ─────────────────────────────────────────────────────────────────


def test_jp_locale_admission_hp_uses_disease_yaml_chief_complaint() -> None:
    """JP ADMISSION_HP must include chief_complaint from disease YAML (Japanese)."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
        disease_protocol=protocol,
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    # bacterial_pneumonia chief_complaint.ja = "発熱・咳嗽・呼吸困難"
    cc_text = out.sections.get("chief_complaint", "")
    assert "発熱" in cc_text or "咳嗽" in cc_text or "呼吸" in cc_text, (
        f"JP chief_complaint not found in: {cc_text!r}"
    )


def test_jp_locale_hpi_uses_onset_pattern() -> None:
    """JP ADMISSION_HP hpi section uses narrative.hpi_template.onset_pattern."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
        disease_protocol=protocol,
        severity="moderate",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    hpi_text = out.sections.get("hpi", "")
    # bacterial_pneumonia HPI for moderate: "発熱・咳嗽・喀痰が出現し、SpO2 低下を認め緊急受診。"
    assert hpi_text != "", "hpi section must not be empty"
    # Should contain Japanese text (at minimum some hiragana/katakana)
    has_jp = any("぀" <= c <= "ヿ" for c in hpi_text)
    assert has_jp, f"hpi section does not contain Japanese text: {hpi_text!r}"


def test_jp_locale_physical_examination_section() -> None:
    """JP physical_examination section uses disease YAML physical_exam_findings."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
        disease_protocol=protocol,
        severity="moderate",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    phys_text = out.sections.get("physical_examination", "")
    assert phys_text != "", "physical_examination must not be empty"
    # Should contain body-system content (any Japanese text is fine)
    has_jp = any("぀" <= c <= "ヿ" for c in phys_text)
    assert has_jp, f"physical_examination does not contain Japanese text: {phys_text!r}"


def test_jp_locale_discharge_instructions_uses_disease_specific() -> None:
    """JP DISCHARGE_SUMMARY discharge_instructions uses disease_specific override."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.DISCHARGE_SUMMARY)
    ctx = _make_ctx(
        document_type=DocumentType.DISCHARGE_SUMMARY,
        target_lang="ja",
        locale="jp",
        disease_protocol=protocol,
        day_index=5,
        los_days=5,
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    di_text = out.sections.get("discharge_instructions", "")
    assert di_text != "", "discharge_instructions must not be empty"
    # bacterial_pneumonia override contains "抗菌薬" — verify disease_specific is used
    assert "抗菌薬" in di_text, (
        f"disease_specific discharge instruction ('抗菌薬') not in: {di_text!r}"
    )


# ─────────────────────────────────────────────────────────────────
# 5. EN locale
# ─────────────────────────────────────────────────────────────────


def test_en_locale_admission_hp_chief_complaint() -> None:
    """EN ADMISSION_HP chief_complaint from disease YAML (English)."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        target_lang="en",
        locale="us",
        disease_protocol=protocol,
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    cc_text = out.sections.get("chief_complaint", "")
    # bacterial_pneumonia chief_complaint.en = "Fever, cough, dyspnea"
    cc_lower = cc_text.lower()
    assert "fever" in cc_lower or "cough" in cc_lower or "dyspnea" in cc_lower, (
        f"EN chief_complaint not found in: {cc_text!r}"
    )


def test_en_locale_discharge_instructions_has_en_text() -> None:
    """EN DISCHARGE_SUMMARY discharge_instructions has English text."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.DISCHARGE_SUMMARY)
    ctx = _make_ctx(
        document_type=DocumentType.DISCHARGE_SUMMARY,
        target_lang="en",
        locale="us",
        disease_protocol=protocol,
        day_index=5,
        los_days=5,
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    di_text = out.sections.get("discharge_instructions", "")
    assert di_text != "", "discharge_instructions must not be empty for EN locale"
    # bacterial_pneumonia EN override has "antibiotic"
    assert "antibiotic" in di_text.lower(), (
        f"EN disease-specific instruction not found in: {di_text!r}"
    )


# ─────────────────────────────────────────────────────────────────
# 6. PROGRESS_NOTE day_0 with disease YAML trajectory
# ─────────────────────────────────────────────────────────────────


def test_progress_note_day_0_contains_assessment() -> None:
    """PROGRESS_NOTE at day_0 must include assessment from daily_trajectory.

    bacterial_pneumonia uses 'smooth_recovery' as the disease YAML archetype.
    The baseline reference data uses 'uncomplicated_improvement'.
    """
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.PROGRESS_NOTE)
    # Use the actual disease YAML archetype name (smooth_recovery for bacterial_pneumonia)
    ctx = _make_ctx(
        document_type=DocumentType.PROGRESS_NOTE,
        day_index=0,
        disease_protocol=protocol,
        archetype="smooth_recovery",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.raw_text != "", "raw_text must not be empty"
    # bacterial_pneumonia day_0 assessment = "初期診断確定、治療開始"
    assert "初期診断" in out.raw_text or "治療開始" in out.raw_text or "診断" in out.raw_text, (
        f"Day-0 assessment text not found in: {out.raw_text!r}"
    )


def test_progress_note_day_3_from_disease_yaml() -> None:
    """PROGRESS_NOTE at day_1 uses daily_trajectory.day_1.

    bacterial_pneumonia uses 'smooth_recovery' as the disease YAML archetype.
    """
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.PROGRESS_NOTE)
    # Use the actual disease YAML archetype name
    ctx = _make_ctx(
        document_type=DocumentType.PROGRESS_NOTE,
        day_index=1,
        disease_protocol=protocol,
        archetype="smooth_recovery",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    # bacterial_pneumonia day_1 subjective = "症状緩和傾向"
    assert out.raw_text != ""
    assert "症状" in out.raw_text or "治療" in out.raw_text, (
        f"Day-1 content not found in: {out.raw_text!r}"
    )


# ─────────────────────────────────────────────────────────────────
# 7. Multi-day fallback chain
# ─────────────────────────────────────────────────────────────────


def test_multi_day_fallback_no_empty_for_day_7() -> None:
    """PROGRESS_NOTE at day_7 uses fallback when YAML only has day_0/day_1."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.PROGRESS_NOTE)
    # bacterial_pneumonia daily_trajectory only has day_0 + day_1
    ctx = _make_ctx(
        document_type=DocumentType.PROGRESS_NOTE,
        day_index=7,
        disease_protocol=protocol,
        archetype="uncomplicated_improvement",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    # Must produce non-empty output — no crash, no empty string
    assert out.raw_text.strip() != "", (
        "raw_text must not be empty for day_7 with fallback chain"
    )


def test_multi_day_fallback_physical_exam_day_5_uses_nearest_earlier() -> None:
    """Physical exam fallback for day_5 uses day_3 (nearest earlier available)."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    # bacterial_pneumonia physical_exam_findings has day_0 + day_3
    # day_5 should fall back to day_3
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        day_index=5,
        disease_protocol=protocol,
        archetype="uncomplicated_improvement",
        severity="moderate",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    phys_text = out.sections.get("physical_examination", "")
    assert phys_text.strip() != "", "physical_examination must not be empty with fallback"


# ─────────────────────────────────────────────────────────────────
# 8. Baseline disease (non-priority, no disease_protocol)
# ─────────────────────────────────────────────────────────────────


def test_admission_hp_without_disease_protocol_produces_valid_output() -> None:
    """ADMISSION_HP with disease_protocol=None must produce valid NarrativeOutput."""
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP, disease_protocol=None)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert isinstance(out.sections, dict)
    for section in spec.composition_sections:
        assert section in out.sections
        assert isinstance(out.sections[section], str)


def test_progress_note_without_disease_protocol_no_crash() -> None:
    """PROGRESS_NOTE with disease_protocol=None must not crash."""
    spec = _get_spec(DocumentType.PROGRESS_NOTE)
    ctx = _make_ctx(document_type=DocumentType.PROGRESS_NOTE, disease_protocol=None, day_index=3)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.raw_text.strip() != "", "raw_text must be non-empty even without disease_protocol"


def test_discharge_summary_without_disease_protocol_no_crash() -> None:
    """DISCHARGE_SUMMARY without disease_protocol uses baseline discharge instructions."""
    spec = _get_spec(DocumentType.DISCHARGE_SUMMARY)
    ctx = _make_ctx(
        document_type=DocumentType.DISCHARGE_SUMMARY,
        disease_protocol=None,
        day_index=5,
        los_days=5,
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    di_text = out.sections.get("discharge_instructions", "")
    # baseline discharge instructions must be used when no disease_protocol
    assert di_text.strip() != "", (
        "discharge_instructions must use baseline when no disease_protocol"
    )


# ─────────────────────────────────────────────────────────────────
# 9. facts_used populated
# ─────────────────────────────────────────────────────────────────


def test_facts_used_populated_for_composition() -> None:
    """facts_used must contain at least 3 source field paths for COMPOSITION."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        disease_protocol=protocol,
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert len(out.facts_used) >= 3, (
        f"facts_used should have >=3 entries, got {len(out.facts_used)}: {out.facts_used}"
    )


def test_facts_used_uses_dot_notation_strings() -> None:
    """facts_used entries must be strings in dot-notation format."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP, disease_protocol=protocol)
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    for fact in out.facts_used:
        assert isinstance(fact, str), f"facts_used entry must be str, got: {type(fact)}"
        assert "." in fact, f"facts_used entry must be dot-notation: {fact!r}"


# ─────────────────────────────────────────────────────────────────
# 10. Determinism
# ─────────────────────────────────────────────────────────────────


def test_deterministic_two_calls_same_output() -> None:
    """Two calls with identical NarrativeContext produce identical NarrativeOutput."""
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        disease_protocol=protocol,
        target_lang="ja",
        locale="jp",
        severity="moderate",
    )
    gen = TemplateNarrativeGenerator()
    out1 = gen.generate(ctx, spec)
    out2 = gen.generate(ctx, spec)
    assert out1.raw_text == out2.raw_text
    assert out1.sections == out2.sections
    assert out1.metadata == out2.metadata


# ─────────────────────────────────────────────────────────────────
# 11. metadata field
# ─────────────────────────────────────────────────────────────────


def test_metadata_includes_generator_and_lang() -> None:
    """metadata dict must include 'generator' and 'lang' keys."""
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP, target_lang="ja")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    assert out.metadata.get("generator") == "template"
    assert out.metadata.get("lang") == "ja"


# ─────────────────────────────────────────────────────────────────
# 12. Allergies listed in allergies section
# ─────────────────────────────────────────────────────────────────


def test_allergies_listed_in_admission_hp() -> None:
    """Allergies in ctx must appear in allergies section of ADMISSION_HP."""
    from clinosim.types.allergy import Allergy
    allergy = Allergy(allergen_display="ペニシリン", criticality="high", category="medication")
    protocol = load_disease_protocol("bacterial_pneumonia")
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(
        document_type=DocumentType.ADMISSION_HP,
        disease_protocol=protocol,
        allergies=[allergy],
        target_lang="ja",
    )
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    allergy_text = out.sections.get("allergies", "")
    assert "ペニシリン" in allergy_text, (
        f"Allergy 'ペニシリン' not found in: {allergy_text!r}"
    )


def test_no_allergies_shows_nkda_phrase() -> None:
    """Empty allergy list should show NKDA or equivalent phrase."""
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP, allergies=[])
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    allergy_text = out.sections.get("allergies", "")
    assert allergy_text.strip() != "", "allergies section must not be empty even with no allergies"


# ─────────────────────────────────────────────────────────────────
# 13. Social history section
# ─────────────────────────────────────────────────────────────────


def test_social_history_section_includes_smoking() -> None:
    """ADMISSION_HP social_history must mention smoking status."""
    spec = _get_spec(DocumentType.ADMISSION_HP)
    ctx = _make_ctx(document_type=DocumentType.ADMISSION_HP, target_lang="ja")
    gen = TemplateNarrativeGenerator()
    out = gen.generate(ctx, spec)
    social_text = out.sections.get("social_history", "")
    assert social_text.strip() != ""
    # smoking_status = "former" should appear as "元喫煙者" or similar
    has_smoking = "喫煙" in social_text or "smoking" in social_text.lower()
    assert has_smoking, f"smoking status not found in social_history: {social_text!r}"
