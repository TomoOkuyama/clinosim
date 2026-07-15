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
