"""Unit tests for _fhir_documents _bb_document_references builder (Task 10).

Tests the new Stage 1 default builder that reads record.documents
(Task 8 enricher output) where format_type='free_text' and emits
DocumentReference resources.

The legacy _build_document_reference function is NOT tested here —
see existing test_fhir_documents.py if present.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

from clinosim.modules.document import DOC_REFERENCE_ID_PREFIX
from clinosim.modules.output._fhir_documents import _bb_document_references
from clinosim.types.clinical import ClinicalDocument, ClinicalDocumentNarrative


def _make_ctx(docs, country="us"):
    return SimpleNamespace(
        record={"documents": docs, "patient": {"patient_id": "pt1"}, "extensions": {}},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "pt1"},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        patient_sex="",
    )


def _sample_doc_dataclass(format_type="free_text") -> ClinicalDocument:
    return ClinicalDocument(
        document_id="doc-enc1-progress_note-1",
        loinc_code="11506-3",
        patient_id="pt1",
        encounter_id="enc1",
        author_practitioner_id="staff-001",
        authored_datetime="2026-07-01T09:00:00",
        language="en",
        format_type=format_type,
        narrative=ClinicalDocumentNarrative(
            text="Patient is stable. Vitals within normal limits. No acute distress.",
            generator="template",
        ),
    )


def _sample_doc_dict(format_type="free_text") -> dict:
    return {
        "document_id": "doc-enc1-progress_note-1",
        "loinc_code": "11506-3",
        "patient_id": "pt1",
        "encounter_id": "enc1",
        "author_practitioner_id": "staff-001",
        "authored_datetime": "2026-07-01T09:00:00",
        "language": "en",
        "format_type": format_type,
        "narrative": {
            "text": "Patient is stable. Vitals within normal limits. No acute distress.",
            "sections": {},
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


# --- test_bb_document_references_emits_for_free_text_docs ---


def test_bb_document_references_emits_for_free_text_docs():
    """Fixture with a ClinicalDocument format_type='free_text' → 1 DocumentReference emitted."""
    ctx = _make_ctx([_sample_doc_dataclass()])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "DocumentReference"
    assert r["id"] == "doc-enc1-progress_note-1"
    assert r["status"] == "current"
    # type.coding must use LOINC
    coding = r["type"]["coding"][0]
    assert coding["code"] == "11506-3"
    assert "loinc" in coding["system"].lower() or "loinc.org" in coding["system"]
    # content must have base64 attachment
    assert len(r["content"]) == 1
    attachment = r["content"][0]["attachment"]
    decoded = base64.b64decode(attachment["data"]).decode("utf-8")
    assert "stable" in decoded


def test_bb_document_references_skips_composition_docs():
    """format_type='composition' → builder returns [] (Composition builder handles those)."""
    ctx = _make_ctx([_sample_doc_dataclass(format_type="composition")])
    assert _bb_document_references(ctx) == []


def test_bb_document_references_dict_path():
    """dict-fixture (production JSON round-trip) works via _o() dual-access."""
    ctx = _make_ctx([_sample_doc_dict()])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "DocumentReference"
    assert r["id"] == "doc-enc1-progress_note-1"
    assert r["subject"]["reference"] == "Patient/pt1"
    assert r["context"]["encounter"][0]["reference"] == "Encounter/enc1"


def test_bb_document_references_jp_locale():
    """country='JP' → DocumentReference type carries EN LOINC canonical on
    ``coding[].display`` (walker-safe) + JP on ``text`` (Issue #360 G5,
    2026-07-22 — pre-fix this test asserted JP on coding[].display which
    was subsequently stripped by
    ``_strip_japanese_display_on_english_only_systems``)."""
    doc = _sample_doc_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="JP")
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    coding_display = r["type"]["coding"][0]["display"]
    text_display = r["type"]["text"]
    # LOINC 11506-3 canonical: en="Progress note", ja="経過記録".
    assert coding_display == "Progress note"
    assert text_display == "経過記録"


def test_bb_document_references_empty_input_returns_empty_list():
    """Graceful handling of empty document list."""
    ctx = _make_ctx([])
    assert _bb_document_references(ctx) == []


# --- additional edge cases ---


def test_bb_document_references_skips_empty_text():
    """ClinicalDocument with text='' → not emitted (FHIR R4 requires attachment content)."""
    doc = _sample_doc_dataclass()
    doc.narrative.text = ""
    ctx = _make_ctx([doc])
    assert _bb_document_references(ctx) == []


def test_bb_document_references_subject_uses_patient_id():
    """DocumentReference.subject.reference points to the correct patient."""
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_document_references(ctx)[0]
    assert r["subject"]["reference"] == "Patient/pt1"


def test_bb_document_references_id_matches_doc_reference_prefix():
    """Resource id starts with DOC_REFERENCE_ID_PREFIX."""
    ctx = _make_ctx([_sample_doc_dataclass()])
    r = _bb_document_references(ctx)[0]
    assert r["id"].startswith(DOC_REFERENCE_ID_PREFIX)


def test_bb_document_references_multiple_free_text_all_emitted():
    """Multiple free_text docs → all emitted."""
    doc1 = _sample_doc_dict()
    doc2 = _sample_doc_dict()
    doc2["document_id"] = "doc-enc1-admission_hp-1"
    doc2["loinc_code"] = "34117-2"
    ctx = _make_ctx([doc1, doc2])
    resources = _bb_document_references(ctx)
    assert len(resources) == 2
    ids = {r["id"] for r in resources}
    assert "doc-enc1-progress_note-1" in ids
    assert "doc-enc1-admission_hp-1" in ids


def test_bb_document_references_mixed_format_only_free_text_emitted():
    """Mixed format_type docs → only free_text emitted, composition skipped."""
    docs = [
        _sample_doc_dict(format_type="free_text"),
        _sample_doc_dict(format_type="composition"),
    ]
    docs[0]["document_id"] = "doc-enc1-progress_note-1"
    docs[1]["document_id"] = "doc-enc1-hp-1"
    ctx = _make_ctx(docs)
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    assert resources[0]["id"] == "doc-enc1-progress_note-1"


def test_bb_document_references_us_display_in_english():
    """US country → display text in English."""
    ctx = _make_ctx([_sample_doc_dict()], country="us")
    r = _bb_document_references(ctx)[0]
    type_display = r["type"]["coding"][0]["display"]
    assert type_display == "Progress note"
