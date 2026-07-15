"""Unit tests for _fhir_composition builder (Tier 1 #3 α-min-1 Task 9)."""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.document import COMPOSITION_ID_PREFIX
from clinosim.modules.output._fhir_composition import _bb_compositions
from clinosim.types.clinical import ClinicalDocument, ClinicalDocumentNarrative


def _make_ctx(docs, country="us"):
    return SimpleNamespace(
        record={"documents": docs, "extensions": {}},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )


def _sample_doc_dataclass(format_type="composition") -> ClinicalDocument:
    return ClinicalDocument(
        document_id="enc1-hp-1",
        loinc_code="34117-2",
        patient_id="pt1",
        encounter_id="enc1",
        author_practitioner_id="staff-001",
        authored_datetime="2026-07-01T08:00:00",
        language="en",
        format_type=format_type,
        narrative=ClinicalDocumentNarrative(
            sections={
                "History of Present Illness": "Patient presents with fever and cough.",
                "Physical Exam": "Temperature 38.5°C. Lungs: crackles bilaterally.",
            },
            generator="template",
        ),
    )


def _sample_doc_dict(format_type="composition") -> dict:
    return {
        "document_id": "enc1-hp-1",
        "loinc_code": "34117-2",
        "patient_id": "pt1",
        "encounter_id": "enc1",
        "author_practitioner_id": "staff-001",
        "authored_datetime": "2026-07-01T08:00:00",
        "language": "en",
        "format_type": format_type,
        "narrative": {
            "text": "",
            "sections": {
                "History of Present Illness": "Patient presents with fever and cough.",
                "Physical Exam": "Temperature 38.5°C. Lungs: crackles bilaterally.",
            },
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


# --- Shape and required fields ---


def test_empty_docs_emits_nothing():
    ctx = _make_ctx([])
    assert _bb_compositions(ctx) == []


def test_free_text_format_skipped():
    doc = _sample_doc_dataclass(format_type="free_text")
    ctx = _make_ctx([doc])
    assert _bb_compositions(ctx) == []


def test_emits_one_composition_for_composition_format():
    ctx = _make_ctx([_sample_doc_dataclass()])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    assert resources[0]["resourceType"] == "Composition"


def test_composition_id_uses_canonical_prefix_dataclass():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert r["id"].startswith(COMPOSITION_ID_PREFIX)
    assert r["id"] == f"{COMPOSITION_ID_PREFIX}enc1-hp-1"


def test_composition_status_is_final():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert r["status"] == "final"


def test_composition_type_coding_loinc():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    coding = r["type"]["coding"][0]
    assert coding["code"] == "34117-2"
    assert "loinc" in coding["system"].lower() or "loinc.org" in coding["system"]


def test_composition_subject_patient_ref():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert r["subject"]["reference"] == "Patient/pt1"


def test_composition_encounter_ref():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert r["encounter"]["reference"] == "Encounter/enc1"


def test_composition_author_ref():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert r["author"] == [{"reference": "Practitioner/staff-001"}]


def test_composition_date():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert r["date"] == "2026-07-01T08:00:00"


def test_composition_sections_built_from_sections_dict():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert "section" in r
    sections = r["section"]
    assert len(sections) == 2
    titles = {s["title"] for s in sections}
    assert "History of Present Illness" in titles
    assert "Physical Exam" in titles


def test_composition_section_text_div():
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_compositions(ctx)[0]
    hpi_section = next(s for s in r["section"] if s["title"] == "History of Present Illness")
    assert "status" in hpi_section["text"]
    assert "div" in hpi_section["text"]
    assert "fever" in hpi_section["text"]["div"]


def test_empty_sections_omits_section_key():
    doc = _sample_doc_dataclass()
    doc.narrative.sections = {}
    ctx = _make_ctx([doc])
    r = _bb_compositions(ctx)[0]
    assert "section" not in r


def test_no_author_yields_placeholder_author_array():
    """A-1 fix (post-PR-128 adv): empty author_id → placeholder [{"reference": "Practitioner/UNKNOWN"}].
    FHIR R4 Composition.author is 1..*; empty [] is non-conformant. Production path never fires
    (inpatient.py:184 sets attending_id=DR-001); placeholder surfaces via reference integrity
    audit (dangling Practitioner/UNKNOWN) rather than silent invalid [].
    See TODO in _fhir_composition.py for Task 10/15 full practitioner-ref fix plan."""
    doc = _sample_doc_dataclass()
    doc.author_practitioner_id = ""
    ctx = _make_ctx([doc])
    r = _bb_compositions(ctx)[0]
    assert r["author"] == [{"reference": "Practitioner/UNKNOWN"}]


def test_no_encounter_omits_encounter_field():
    doc = _sample_doc_dataclass()
    doc.encounter_id = ""
    ctx = _make_ctx([doc])
    r = _bb_compositions(ctx)[0]
    assert "encounter" not in r


# --- Dict path (production JSON-deserialized CIF) ---


def test_composition_from_dict_path():
    """Production CIF is json.load() -> dict; verify _o() dict-access path."""
    ctx = _make_ctx([_sample_doc_dict()])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "Composition"
    assert r["id"] == f"{COMPOSITION_ID_PREFIX}enc1-hp-1"
    assert r["subject"]["reference"] == "Patient/pt1"
    assert r["encounter"]["reference"] == "Encounter/enc1"
    sections = r["section"]
    assert any(s["title"] == "History of Present Illness" for s in sections)


def test_dict_path_free_text_skipped():
    ctx = _make_ctx([_sample_doc_dict(format_type="free_text")])
    assert _bb_compositions(ctx) == []


# --- Multi-doc scenarios ---


def test_multiple_docs_only_composition_type_emitted():
    docs = [
        _sample_doc_dict(format_type="composition"),
        _sample_doc_dict(format_type="free_text"),
    ]
    # Use production-format document_id with DOC_REFERENCE_ID_PREFIX ("doc-"); I-3 fix
    # strips "doc-" before prepending COMPOSITION_ID_PREFIX → "comp-enc-A" not "comp-doc-enc-A".
    from clinosim.modules.document import DOC_REFERENCE_ID_PREFIX

    docs[0]["document_id"] = f"{DOC_REFERENCE_ID_PREFIX}enc-A"
    ctx = _make_ctx(docs)
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    assert resources[0]["id"] == f"{COMPOSITION_ID_PREFIX}enc-A"


def test_multiple_composition_docs_all_emitted():
    doc1 = _sample_doc_dict()
    doc2 = _sample_doc_dict()
    doc1["document_id"] = "enc1-hp-1"
    doc2["document_id"] = "enc1-dc-1"
    doc2["loinc_code"] = "18842-5"
    ctx = _make_ctx([doc1, doc2])
    resources = _bb_compositions(ctx)
    assert len(resources) == 2
    ids = {r["id"] for r in resources}
    assert f"{COMPOSITION_ID_PREFIX}enc1-hp-1" in ids
    assert f"{COMPOSITION_ID_PREFIX}enc1-dc-1" in ids


# --- JP locale ---


def test_jp_locale_composition_language_field():
    doc = _sample_doc_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="jp")
    r = _bb_compositions(ctx)[0]
    assert r["language"] == "ja"


# --- I-1 regression: XHTML escaping in section text.div ---


def test_composition_section_text_escapes_xhtml_special_chars():
    """I-1 regression: section narrative text must escape <, >, &, " before
    interpolation into xhtml div (latent FHIR R4 conformance gap).

    Synthetic content with lab values: 'PaO2 < 80, PaCO2 > 45 & pH < 7.30'
    must emit &lt;, &gt;, &amp; — raw characters would produce invalid XHTML.
    """
    doc = _sample_doc_dict()
    doc["narrative"]["sections"] = {
        "Clinical Assessment": 'PaO2 < 80, PaCO2 > 45 & pH < 7.30 "borderline"',
    }
    ctx = _make_ctx([doc])
    r = _bb_compositions(ctx)[0]
    section = r["section"][0]
    div = section["text"]["div"]

    # Raw special chars must NOT appear unescaped
    assert " < " not in div, "Raw '<' in div — XHTML invalid"
    assert " > " not in div, "Raw '>' in div — XHTML invalid"
    assert " & " not in div, "Raw '&' in div — XHTML invalid"
    assert '"borderline"' not in div, "Raw '\"' in div — XHTML invalid"

    # Escaped forms must be present
    assert "&lt;" in div
    assert "&gt;" in div
    assert "&amp;" in div
    assert "&quot;" in div


# --- I-3 regression: Composition.id double-prefix ---


def test_composition_id_strips_doc_prefix_from_document_id():
    """I-3 regression: production document_id carries 'doc-' prefix from
    DOC_REFERENCE_ID_PREFIX. Composition.id must NOT double-prefix to
    'comp-doc-{enc}-{seq}'; it should be 'comp-{enc}-{seq}'.
    """
    from clinosim.modules.document import DOC_REFERENCE_ID_PREFIX

    doc = _sample_doc_dict()
    doc["document_id"] = f"{DOC_REFERENCE_ID_PREFIX}enc-test-01"  # production format
    ctx = _make_ctx([doc])
    r = _bb_compositions(ctx)[0]
    assert r["id"] == f"{COMPOSITION_ID_PREFIX}enc-test-01", (
        f"Expected 'comp-enc-test-01', got '{r['id']}' — double-prefix defect"
    )
    assert "doc-" not in r["id"], "DOC_REFERENCE_ID_PREFIX leaked into Composition.id"
