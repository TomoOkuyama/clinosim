"""α-min-2 Composition builder tests for 4 new COMPOSITION DocumentType.

Verifies that existing _bb_compositions filter (format_type == 'composition')
automatically picks up the 4 new α-min-2 COMPOSITION doc types:
  - ADMISSION_NURSING_ASSESSMENT  (LOINC 78390-2)
  - NURSING_DISCHARGE_SUMMARY     (LOINC 34745-0)
  - OUTPATIENT_SOAP               (LOINC 34131-3)
  - ED_NOTE                       (LOINC 34878-9)

JP locale: LOINC display texts are verified against loinc.yaml entries added in Task 8.
dict/dataclass dual-access (_o() helper) verified per PR-90 lesson.

Task 12 — Tier 1 #3 α-min-2 PR1.
"""

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


# ── ADMISSION_NURSING_ASSESSMENT ────────────────────────────────────────────


def _sample_nursing_assessment_dataclass() -> ClinicalDocument:
    return ClinicalDocument(
        document_id="doc-enc1-nursing_assessment-1",
        loinc_code="78390-2",
        patient_id="pt1",
        encounter_id="enc1",
        author_practitioner_id="staff-001",
        authored_datetime="2026-07-01T08:00:00",
        language="en",
        format_type="composition",
        narrative=ClinicalDocumentNarrative(
            sections={
                "nursing_history": "Patient has a history of diabetes managed with insulin.",
                "adl_assessment": "Independent in ADLs prior to admission.",
                "risk_assessments": "Braden score 18: low pressure injury risk.",
                "nursing_diagnosis": "Risk for infection related to altered skin integrity.",
                "care_plan": "Monitor blood glucose QID. Skin care protocol initiated.",
            },
            generator="template",
        ),
    )


def _sample_nursing_assessment_dict() -> dict:
    return {
        "document_id": "doc-enc1-nursing_assessment-1",
        "loinc_code": "78390-2",
        "patient_id": "pt1",
        "encounter_id": "enc1",
        "author_practitioner_id": "staff-001",
        "authored_datetime": "2026-07-01T08:00:00",
        "language": "en",
        "format_type": "composition",
        "narrative": {
            "text": "",
            "sections": {
                "nursing_history": "Patient has a history of diabetes managed with insulin.",
                "adl_assessment": "Independent in ADLs prior to admission.",
                "risk_assessments": "Braden score 18: low pressure injury risk.",
                "nursing_diagnosis": "Risk for infection related to altered skin integrity.",
                "care_plan": "Monitor blood glucose QID. Skin care protocol initiated.",
            },
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


def test_admission_nursing_assessment_composition_shape():
    """ADMISSION_NURSING_ASSESSMENT emits valid Composition with LOINC 78390-2."""
    ctx = _make_ctx([_sample_nursing_assessment_dataclass()])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "Composition"
    assert r["status"] == "final"
    coding = r["type"]["coding"][0]
    assert coding["code"] == "78390-2"
    assert "loinc" in coding["system"].lower() or "loinc.org" in coding["system"]


def test_admission_nursing_assessment_sections_populated():
    """Composition.section[] contains all 5 expected nursing assessment sections."""
    ctx = _make_ctx([_sample_nursing_assessment_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert "section" in r
    titles = {s["title"] for s in r["section"]}
    assert "nursing_history" in titles
    assert "adl_assessment" in titles
    assert "risk_assessments" in titles
    assert "nursing_diagnosis" in titles
    assert "care_plan" in titles


def test_admission_nursing_assessment_id_uses_prefix():
    """Composition.id uses COMPOSITION_ID_PREFIX, stripping doc- prefix."""
    ctx = _make_ctx([_sample_nursing_assessment_dataclass()])
    r = _bb_compositions(ctx)[0]
    assert r["id"].startswith(COMPOSITION_ID_PREFIX)
    assert r["id"] == f"{COMPOSITION_ID_PREFIX}enc1-nursing_assessment-1"


def test_admission_nursing_assessment_dict_path():
    """PR-90: dict fixture (production JSON round-trip) produces same output as dataclass."""
    ctx = _make_ctx([_sample_nursing_assessment_dict()])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "Composition"
    assert r["type"]["coding"][0]["code"] == "78390-2"
    assert r["subject"]["reference"] == "Patient/pt1"
    assert r["encounter"]["reference"] == "Encounter/enc1"
    assert len(r["section"]) == 5


def test_jp_locale_admission_nursing_assessment_display():
    """JP locale: type.coding[0].display resolves to '看護入院アセスメント' via code_lookup."""
    doc = _sample_nursing_assessment_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="jp")
    r = _bb_compositions(ctx)[0]
    display = r["type"]["coding"][0]["display"]
    assert display == "看護入院アセスメント", (
        f"Expected '看護入院アセスメント', got '{display}' — check loinc.yaml 78390-2 ja field"
    )


# ── NURSING_DISCHARGE_SUMMARY ────────────────────────────────────────────────


def _sample_nursing_discharge_dict() -> dict:
    return {
        "document_id": "doc-enc1-nursing_discharge-1",
        "loinc_code": "34745-0",
        "patient_id": "pt1",
        "encounter_id": "enc1",
        "author_practitioner_id": "staff-002",
        "authored_datetime": "2026-07-05T10:00:00",
        "language": "en",
        "format_type": "composition",
        "narrative": {
            "text": "",
            "sections": {
                "admission_status": "Admitted for pneumonia. Initial SpO2 88%.",
                "nursing_interventions_provided": "Oxygen therapy. IV antibiotics administered.",
                "patient_education": "Taught breathing exercises. Medication compliance discussed.",
                "discharge_readiness": "Patient ambulates independently. Afebrile x 24h.",
            },
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


def test_nursing_discharge_summary_composition_shape():
    """NURSING_DISCHARGE_SUMMARY emits valid Composition with LOINC 34745-0."""
    ctx = _make_ctx([_sample_nursing_discharge_dict()])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "Composition"
    assert r["type"]["coding"][0]["code"] == "34745-0"


def test_nursing_discharge_summary_sections():
    """Composition.section[] contains all 4 discharge summary sections."""
    ctx = _make_ctx([_sample_nursing_discharge_dict()])
    r = _bb_compositions(ctx)[0]
    assert "section" in r
    titles = {s["title"] for s in r["section"]}
    assert "admission_status" in titles
    assert "nursing_interventions_provided" in titles
    assert "patient_education" in titles
    assert "discharge_readiness" in titles


def test_jp_locale_nursing_discharge_summary_display():
    """JP locale: LOINC 34745-0 display resolves to '看護退院サマリー'."""
    doc = _sample_nursing_discharge_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="jp")
    r = _bb_compositions(ctx)[0]
    display = r["type"]["coding"][0]["display"]
    assert display == "看護退院サマリー", (
        f"Expected '看護退院サマリー', got '{display}' — check loinc.yaml 34745-0 ja field"
    )


# ── OUTPATIENT_SOAP ───────────────────────────────────────────────────────────


def _sample_outpatient_soap_dict() -> dict:
    return {
        "document_id": "doc-enc2-outpatient_soap-1",
        "loinc_code": "34131-3",
        "patient_id": "pt1",
        "encounter_id": "enc2",
        "author_practitioner_id": "staff-003",
        "authored_datetime": "2026-07-02T14:00:00",
        "language": "en",
        "format_type": "composition",
        "narrative": {
            "text": "",
            "sections": {
                "subjective": "Patient reports persistent cough for 2 weeks.",
                "objective": "Lungs: scattered wheeze. SpO2 96%.",
                "assessment": "Exacerbation of asthma.",
                "plan": "Increase SABA, add ICS. Follow up in 2 weeks.",
            },
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


def test_outpatient_soap_composition_shape():
    """OUTPATIENT_SOAP emits valid Composition with LOINC 34131-3."""
    ctx = _make_ctx([_sample_outpatient_soap_dict()])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "Composition"
    assert r["type"]["coding"][0]["code"] == "34131-3"


def test_outpatient_soap_four_sections():
    """Composition.section[] contains SOAP sections: S/O/A/P."""
    ctx = _make_ctx([_sample_outpatient_soap_dict()])
    r = _bb_compositions(ctx)[0]
    assert "section" in r
    titles = {s["title"] for s in r["section"]}
    assert "subjective" in titles
    assert "objective" in titles
    assert "assessment" in titles
    assert "plan" in titles


def test_jp_locale_outpatient_soap_display():
    """JP locale: LOINC 34131-3 display resolves to '外来経過記録（SOAP）'."""
    doc = _sample_outpatient_soap_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="jp")
    r = _bb_compositions(ctx)[0]
    display = r["type"]["coding"][0]["display"]
    assert display == "外来経過記録（SOAP）", (
        f"Expected '外来経過記録（SOAP）', got '{display}' — check loinc.yaml 34131-3 ja field"
    )


# ── ED_NOTE ───────────────────────────────────────────────────────────────────


def _sample_ed_note_dict() -> dict:
    return {
        "document_id": "doc-enc3-ed_note-1",
        "loinc_code": "34878-9",
        "patient_id": "pt1",
        "encounter_id": "enc3",
        "author_practitioner_id": "staff-004",
        "authored_datetime": "2026-07-01T22:30:00",
        "language": "en",
        "format_type": "composition",
        "narrative": {
            "text": "",
            "sections": {
                "chief_complaint": "Chest pain radiating to left arm, onset 1 hour ago.",
                "hpi": "65yo male with hx of CAD presents with acute onset chest pain.",
                "triage_details": "Triage level: ESI 2. Immediate assessment initiated.",
                "physical_exam": "HR 102 bpm. Diaphoresis. Muffled heart sounds.",
                "ed_workup": "ECG: ST elevation leads II, III, aVF. Troponin I pending.",
                "assessment": "STEMI — inferior wall.",
                "disposition": "Emergent PCI. Transfer to cath lab.",
            },
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }


def test_ed_note_composition_shape():
    """ED_NOTE emits valid Composition with LOINC 34878-9."""
    ctx = _make_ctx([_sample_ed_note_dict()])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    r = resources[0]
    assert r["resourceType"] == "Composition"
    assert r["type"]["coding"][0]["code"] == "34878-9"


def test_ed_note_seven_sections():
    """Composition.section[] contains all 7 expected ED note sections."""
    ctx = _make_ctx([_sample_ed_note_dict()])
    r = _bb_compositions(ctx)[0]
    assert "section" in r
    titles = {s["title"] for s in r["section"]}
    expected = {"chief_complaint", "hpi", "triage_details", "physical_exam",
                "ed_workup", "assessment", "disposition"}
    assert expected == titles


def test_jp_locale_ed_note_display():
    """JP locale: LOINC 34878-9 display resolves to '救急科記録'."""
    doc = _sample_ed_note_dict()
    doc["language"] = "ja"
    ctx = _make_ctx([doc], country="jp")
    r = _bb_compositions(ctx)[0]
    display = r["type"]["coding"][0]["display"]
    assert display == "救急科記録", (
        f"Expected '救急科記録', got '{display}' — check loinc.yaml 34878-9 ja field"
    )


# ── Multi-type and cross-type verification ────────────────────────────────────


def test_all_four_alpha2_composition_types_emitted_together():
    """All 4 α-min-2 COMPOSITION docs emitted when present in one record."""
    docs = [
        _sample_nursing_assessment_dict(),
        _sample_nursing_discharge_dict(),
        _sample_outpatient_soap_dict(),
        _sample_ed_note_dict(),
    ]
    ctx = _make_ctx(docs)
    resources = _bb_compositions(ctx)
    assert len(resources) == 4
    loinc_codes = {r["type"]["coding"][0]["code"] for r in resources}
    assert loinc_codes == {"78390-2", "34745-0", "34131-3", "34878-9"}


def test_free_text_skipped_among_alpha2_compositions():
    """format_type='free_text' docs in same record are skipped by _bb_compositions."""
    docs = [
        _sample_nursing_assessment_dict(),
        {  # NURSING_SHIFT_NOTE is free_text — must be skipped
            "document_id": "doc-enc1-nursing_shift-1",
            "loinc_code": "34746-8",
            "patient_id": "pt1",
            "encounter_id": "enc1",
            "format_type": "free_text",
            "text": "Night shift: patient rested comfortably.",
        },
    ]
    ctx = _make_ctx(docs)
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    assert resources[0]["type"]["coding"][0]["code"] == "78390-2"


def test_section_text_div_contains_content():
    """Each section's text.div contains the expected narrative fragment."""
    ctx = _make_ctx([_sample_nursing_assessment_dict()])
    r = _bb_compositions(ctx)[0]
    braden_section = next(s for s in r["section"] if s["title"] == "risk_assessments")
    assert "Braden" in braden_section["text"]["div"]
    assert braden_section["text"]["status"] == "generated"
