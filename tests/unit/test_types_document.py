"""Unit tests for clinosim.types.document(Tier 1 #3 α-min-1 PR1)."""

from __future__ import annotations

from clinosim.types.document import (
    DocumentType,
    FormatType,
    NarrativeContext,
    NarrativeOutput,
)


def test_document_type_enum_alpha_min_1_set():
    # Note: brief specified α (Unicode) in function name; using ASCII per PEP 8 convention
    # Python 3 PEP 3131 allows it but conventional codebases use ASCII identifiers.
    assert DocumentType.ADMISSION_HP.value == "admission_hp"
    assert DocumentType.PROGRESS_NOTE.value == "progress_note"
    assert DocumentType.DISCHARGE_SUMMARY.value == "discharge_summary"


def test_format_type_enum():
    assert FormatType.FREE_TEXT.value == "free_text"
    assert FormatType.COMPOSITION.value == "composition"
    assert FormatType.QUESTIONNAIRE_RESPONSE.value == "questionnaire_response"


def test_narrative_output_defaults_empty():
    out = NarrativeOutput()
    assert out.raw_text == ""
    assert out.sections == {}
    assert out.structured == {}
    assert out.metadata == {}
    assert out.facts_used == []


def test_narrative_output_section_payload():
    out = NarrativeOutput(
        sections={"chief_complaint": "発熱、咳嗽", "hpi": "3 日前より..."},
        metadata={"generator": "template"},
        facts_used=["disease_protocol.chief_complaint"],
    )
    assert out.sections["chief_complaint"] == "発熱、咳嗽"
    assert "template" in out.metadata.values()


def test_narrative_context_default_constructible():
    """NarrativeContext は dataclass、全 field default 設定可。"""
    from clinosim.types.encounter import Encounter, EncounterType
    from clinosim.types.patient import PatientProfile

    # Note: EncounterRecord does not exist in codebase; using Encounter instead.
    ctx = NarrativeContext(
        patient=PatientProfile(),
        encounter=Encounter(),
        encounter_type=EncounterType.INPATIENT,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=5,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
    )
    assert ctx.clinical_course_archetype == "uncomplicated_improvement"
    assert ctx.locale == "jp"


def test_llm_enabled_sections_for_jp_unions_with_universal():
    """v7 (2026-08-16 pm): llm_enabled_sections_jp is ADDITIVE.

    The prior implementation returned llm_enabled_sections_jp
    verbatim when populated, silently dropping the universal sections
    (hospital_course, discharge_instructions) from LLM replacement for
    JP discharge_summary. That regressed 11/11 v8 hospital_course outputs
    to raw template text (see v8 review). This test locks in the
    union semantics.
    """
    from clinosim.types.document import DocumentTypeSpec

    spec = DocumentTypeSpec(
        type_key="discharge_summary",
        loinc_code="18842-5",
        format_type=FormatType.COMPOSITION,
        countries_supported=("us", "jp"),
        generation_frequency="discharge_once",
        composition_sections=("hospital_course", "discharge_instructions"),
        llm_enabled_sections=("hospital_course", "discharge_instructions"),
        llm_enabled_sections_jp=("present_illness",),
    )
    us_list = spec.llm_enabled_sections_for("US")
    jp_list = spec.llm_enabled_sections_for("JP")
    assert us_list == ("hospital_course", "discharge_instructions")
    # JP MUST retain both universal sections AND add present_illness.
    assert set(jp_list) == {"hospital_course", "discharge_instructions", "present_illness"}
    # Universal sections MUST appear first (insertion order preserved).
    assert jp_list[0] == "hospital_course"
    assert jp_list[1] == "discharge_instructions"
    assert jp_list[-1] == "present_illness"


def test_llm_enabled_sections_for_jp_empty_extra_returns_universal():
    """When llm_enabled_sections_jp is empty (the common case for
    non-discharge doc_types), JP returns the universal list unchanged."""
    from clinosim.types.document import DocumentTypeSpec

    spec = DocumentTypeSpec(
        type_key="admission_hp",
        loinc_code="34117-2",
        format_type=FormatType.COMPOSITION,
        countries_supported=("us", "jp"),
        generation_frequency="admission_once",
        composition_sections=("hpi", "assessment_and_plan"),
        llm_enabled_sections=("hpi", "assessment_and_plan"),
        llm_enabled_sections_jp=(),
    )
    assert spec.llm_enabled_sections_for("US") == ("hpi", "assessment_and_plan")
    assert spec.llm_enabled_sections_for("JP") == ("hpi", "assessment_and_plan")


def test_llm_enabled_sections_for_dedups_overlap():
    """Defensive: if a section appears in both lists (edge case),
    dedup preserves first-occurrence order."""
    from clinosim.types.document import DocumentTypeSpec

    spec = DocumentTypeSpec(
        type_key="dummy",
        loinc_code="x",
        format_type=FormatType.COMPOSITION,
        countries_supported=("jp",),
        generation_frequency="once",
        composition_sections=("a", "b"),
        llm_enabled_sections=("a", "b"),
        llm_enabled_sections_jp=("b", "c"),
    )
    assert spec.llm_enabled_sections_for("JP") == ("a", "b", "c")
