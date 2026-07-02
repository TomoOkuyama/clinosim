import pytest

from clinosim.types.clinical import (
    ClinicalDocument,
    ClinicalDocumentNarrative,
    NarrativeVersionManifest,
)


@pytest.mark.unit
def test_narrative_wrapper_defaults_are_empty():
    n = ClinicalDocumentNarrative()
    assert n.text == ""
    assert n.sections == {}
    assert n.structured == {}
    assert n.generator == "none"
    assert n.generator_metadata == {}
    assert n.generated_at == ""
    assert n.facts_used == []


@pytest.mark.unit
def test_clinical_document_default_narrative_is_none():
    """AD-65: stub 直後は narrative=None(Stage 2 未実行の signal)"""
    doc = ClinicalDocument(document_id="doc-x", loinc_code="34117-2")
    assert doc.narrative is None


@pytest.mark.unit
def test_clinical_document_has_no_legacy_flat_fields():
    """AD-65: text/sections/text_source 等 flat narrative fields は削除"""
    doc = ClinicalDocument()
    for legacy in (
        "text",
        "sections",
        "text_source",
        "llm_model",
        "llm_provider",
        "prompt_version",
        "cache_hit",
        "fallback_reason",
    ):
        assert not hasattr(doc, legacy), f"legacy field {legacy} must be moved to narrative"


@pytest.mark.unit
def test_clinical_document_carries_wrapper():
    n = ClinicalDocumentNarrative(text="hello", sections={"hpi": "text"})
    doc = ClinicalDocument(document_id="doc-y", narrative=n)
    assert doc.narrative is not None
    assert doc.narrative.text == "hello"
    assert doc.narrative.sections["hpi"] == "text"


@pytest.mark.unit
def test_narrative_version_manifest_defaults():
    m = NarrativeVersionManifest(
        version_id="template",
        generator="template",
        generator_config={},
        generated_at="",
        encounter_count=0,
        document_count=0,
        document_counts_by_type={},
        doc_types_enabled=[],
        languages_used=[],
        llm_cost_report={},
    )
    assert m.version_id == "template"
