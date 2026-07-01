"""α-min-2 DocumentReference builder tests for 2 new FREE_TEXT DocumentType.

Verifies that existing _bb_document_references filter (format_type == 'free_text')
automatically picks up the 2 new α-min-2 FREE_TEXT doc types:
  - NURSING_SHIFT_NOTE  (LOINC 34746-8)
  - ED_TRIAGE_NOTE      (LOINC 54094-8)

JP locale: LOINC display texts are verified against loinc.yaml entries added in Task 8.
dict/dataclass dual-access (_o() helper) verified per PR-90 lesson.

Task 12 — Tier 1 #3 α-min-2 PR1.
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


# ── NURSING_SHIFT_NOTE ─────────────────────────────────────────────────────


def _sample_shift_note_dataclass() -> ClinicalDocument:
    return ClinicalDocument(
        document_id="doc-enc1-nursing_shift-1",
        loinc_code="34746-8",
        patient_id="pt1",
        encounter_id="enc1",
        author_practitioner_id="staff-nurse-01",
        authored_datetime="2026-07-01T07:00:00",
        language="en",
        format_type="free_text",
        narrative=ClinicalDocumentNarrative(
            text="Day 1/3 shift: Patient rested comfortably. Vitals stable. IV line patent.",
            generator="template",
        ),
    )


def _sample_shift_note_dict() -> dict:
    return {
        "document_id": "doc-enc1-nursing_shift-1",
        "loinc_code": "34746-8",
        "patient_id": "pt1",
        "encounter_id": "enc1",
        "author_practitioner_id": "staff-nurse-01",
        "authored_datetime": "2026-07-01T07:00:00",
        "language": "en",
        "format_type": "free_text",
        "narrative": {
            "text": "Day 1/3 shift: Patient rested comfortably. Vitals stable. IV line patent.",
            "sections": {},
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


def test_nursing_shift_note_document_reference_shape():
    """NURSING_SHIFT_NOTE emits valid DocumentReference with LOINC 34746-8."""
    ctx = _make_ctx([_sample_shift_note_dataclass()])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "DocumentReference"
    assert r["status"] == "current"
    assert r["docStatus"] == "final"
    coding = r["type"]["coding"][0]
    assert coding["code"] == "34746-8"
    assert "loinc" in coding["system"].lower() or "loinc.org" in coding["system"]


def test_nursing_shift_note_attachment_base64_roundtrip():
    """content[0].attachment.data base64-decodes to original text."""
    ctx = _make_ctx([_sample_shift_note_dataclass()])
    r = _bb_document_references(ctx)[0]
    attachment = r["content"][0]["attachment"]
    decoded = base64.b64decode(attachment["data"]).decode("utf-8")
    assert "Vitals stable" in decoded


def test_nursing_shift_note_id_has_doc_prefix():
    """DocumentReference.id starts with DOC_REFERENCE_ID_PREFIX."""
    ctx = _make_ctx([_sample_shift_note_dataclass()])
    r = _bb_document_references(ctx)[0]
    assert r["id"].startswith(DOC_REFERENCE_ID_PREFIX)
    assert r["id"] == "doc-enc1-nursing_shift-1"


def test_nursing_shift_note_subject_and_encounter():
    """subject + context.encounter references are correctly wired."""
    ctx = _make_ctx([_sample_shift_note_dataclass()])
    r = _bb_document_references(ctx)[0]
    assert r["subject"]["reference"] == "Patient/pt1"
    assert r["context"]["encounter"][0]["reference"] == "Encounter/enc1"


def test_nursing_shift_note_dict_path():
    """PR-90 lesson: dict fixture (production JSON round-trip) works via _o() dual-access."""
    ctx = _make_ctx([_sample_shift_note_dict()])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "DocumentReference"
    assert r["type"]["coding"][0]["code"] == "34746-8"
    assert r["subject"]["reference"] == "Patient/pt1"


def test_jp_locale_nursing_shift_note_display():
    """JP locale: LOINC 34746-8 display resolves to '看護記録'."""
    doc = _sample_shift_note_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="JP")
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    display = r["type"]["coding"][0]["display"]
    assert display == "看護記録", (
        f"Expected '看護記録', got '{display}' — check loinc.yaml 34746-8 ja field"
    )


# ── ED_TRIAGE_NOTE ────────────────────────────────────────────────────────────


def _sample_ed_triage_dataclass() -> ClinicalDocument:
    return ClinicalDocument(
        document_id="doc-enc3-ed_triage-1",
        loinc_code="54094-8",
        patient_id="pt1",
        encounter_id="enc3",
        author_practitioner_id="staff-triage-01",
        authored_datetime="2026-07-01T22:15:00",
        language="en",
        format_type="free_text",
        narrative=ClinicalDocumentNarrative(
            text="Triage level: ESI 2. Chief complaint: chest pain. Acuity: high.",
            generator="template",
        ),
    )


def _sample_ed_triage_dict() -> dict:
    return {
        "document_id": "doc-enc3-ed_triage-1",
        "loinc_code": "54094-8",
        "patient_id": "pt1",
        "encounter_id": "enc3",
        "author_practitioner_id": "staff-triage-01",
        "authored_datetime": "2026-07-01T22:15:00",
        "language": "en",
        "format_type": "free_text",
        "narrative": {
            "text": "Triage level: ESI 2. Chief complaint: chest pain. Acuity: high.",
            "sections": {},
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


def test_ed_triage_note_document_reference_shape():
    """ED_TRIAGE_NOTE emits valid DocumentReference with LOINC 54094-8."""
    ctx = _make_ctx([_sample_ed_triage_dataclass()])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "DocumentReference"
    coding = r["type"]["coding"][0]
    assert coding["code"] == "54094-8"
    assert "loinc" in coding["system"].lower() or "loinc.org" in coding["system"]


def test_ed_triage_note_attachment_base64_roundtrip():
    """ED_TRIAGE_NOTE content.attachment.data decodes to original text."""
    ctx = _make_ctx([_sample_ed_triage_dataclass()])
    r = _bb_document_references(ctx)[0]
    attachment = r["content"][0]["attachment"]
    decoded = base64.b64decode(attachment["data"]).decode("utf-8")
    assert "chest pain" in decoded


def test_ed_triage_note_dict_path():
    """PR-90: dict fixture works for ED_TRIAGE_NOTE."""
    ctx = _make_ctx([_sample_ed_triage_dict()])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["type"]["coding"][0]["code"] == "54094-8"


def test_jp_locale_ed_triage_note_display():
    """JP locale: LOINC 54094-8 display resolves to 'トリアージ記録'."""
    doc = _sample_ed_triage_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="JP")
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    r = resources[0]
    display = r["type"]["coding"][0]["display"]
    assert display == "トリアージ記録", (
        f"Expected 'トリアージ記録', got '{display}' — check loinc.yaml 54094-8 ja field"
    )


# ── Multi-type and cross-type verification ────────────────────────────────────


def test_both_alpha2_free_text_types_emitted_together():
    """Both NURSING_SHIFT_NOTE + ED_TRIAGE_NOTE emitted from same record."""
    docs = [_sample_shift_note_dict(), _sample_ed_triage_dict()]
    ctx = _make_ctx(docs)
    resources = _bb_document_references(ctx)
    assert len(resources) == 2
    codes = {r["type"]["coding"][0]["code"] for r in resources}
    assert codes == {"34746-8", "54094-8"}


def test_composition_skipped_among_alpha2_free_text():
    """format_type='composition' docs in same record are skipped by _bb_document_references."""
    docs = [
        _sample_shift_note_dict(),
        {  # ADMISSION_NURSING_ASSESSMENT is composition — must be skipped
            "document_id": "doc-enc1-nursing_assessment-1",
            "loinc_code": "78390-2",
            "patient_id": "pt1",
            "encounter_id": "enc1",
            "format_type": "composition",
            "sections": {"nursing_history": "Some history."},
        },
    ]
    ctx = _make_ctx(docs)
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    assert resources[0]["type"]["coding"][0]["code"] == "34746-8"


def test_multiple_nursing_shift_notes_all_emitted():
    """Multiple NURSING_SHIFT_NOTE docs (daily) all emitted."""
    doc1 = _sample_shift_note_dict()
    doc2 = _sample_shift_note_dict()
    doc2["document_id"] = "doc-enc1-nursing_shift-2"
    doc2["narrative"]["text"] = "Day 2/3 shift: Patient improving. SpO2 98%."
    ctx = _make_ctx([doc1, doc2])
    resources = _bb_document_references(ctx)
    assert len(resources) == 2
    ids = {r["id"] for r in resources}
    assert "doc-enc1-nursing_shift-1" in ids
    assert "doc-enc1-nursing_shift-2" in ids


def test_ed_triage_note_skips_empty_text():
    """ED_TRIAGE_NOTE with empty text → skipped (FHIR R4 requires attachment content)."""
    doc = _sample_ed_triage_dict()
    doc["narrative"]["text"] = ""
    ctx = _make_ctx([doc])
    assert _bb_document_references(ctx) == []
