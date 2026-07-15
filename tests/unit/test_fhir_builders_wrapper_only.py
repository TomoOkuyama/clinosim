"""FHIR builder wrapper-only tests (AD-65 Task 4).

Verifies _fhir_composition and _fhir_documents builders read narrative
content exclusively via doc["narrative"]["sections"] / doc["narrative"]["text"]
— never the removed flat ClinicalDocument.sections / .text fields — and that
a stub with narrative=None is skipped (with a warning) rather than crashing
or emitting an empty resource.
"""

from __future__ import annotations

import base64

import pytest

from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_composition import _bb_compositions, _build_composition
from clinosim.modules.output._fhir_documents import (
    _bb_document_references,
    _build_dref_from_clinical_doc,
)


def _make_ctx(docs: list[dict], country: str = "us") -> BundleContext:
    return BundleContext(
        record={"documents": docs, "extensions": {}},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="ENC-1",
        patient_sex="",
    )


# --- Composition builder ----------------------------------------------------


@pytest.mark.unit
def test_composition_builder_reads_narrative_sections():
    doc = {
        "document_id": "doc-1",
        "task_type": "admission_hp",
        "loinc_code": "34117-2",
        "format_type": "composition",
        "encounter_id": "ENC-1",
        "patient_id": "P-1",
        "author_practitioner_id": "DR-1",
        "authored_datetime": "2026-01-01T00:00:00",
        "language": "en",
    }
    sections = {"hpi": "text", "assessment_and_plan": "plan"}
    resource = _build_composition(doc, sections, "en")

    assert resource["resourceType"] == "Composition"
    titles = {s["title"] for s in resource["section"]}
    assert titles == {"hpi", "assessment_and_plan"}
    divs = "".join(s["text"]["div"] for s in resource["section"])
    assert "text" in divs and "plan" in divs


@pytest.mark.unit
def test_bb_compositions_merges_narrative_from_doc_dict():
    """End-to-end through _bb_compositions: reads doc['narrative']['sections']."""
    doc = {
        "document_id": "doc-1",
        "task_type": "admission_hp",
        "loinc_code": "34117-2",
        "format_type": "composition",
        "encounter_id": "ENC-1",
        "patient_id": "P-1",
        "author_practitioner_id": "DR-1",
        "authored_datetime": "2026-01-01T00:00:00",
        "language": "en",
        "narrative": {
            "text": "",
            "sections": {"hpi": "65yo M ..."},
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }
    ctx = _make_ctx([doc])
    resources = _bb_compositions(ctx)
    assert len(resources) == 1
    assert resources[0]["section"][0]["title"] == "hpi"


@pytest.mark.unit
def test_bb_compositions_skips_stub_with_no_narrative(caplog):
    doc = {
        "document_id": "doc-1",
        "task_type": "admission_hp",
        "loinc_code": "34117-2",
        "format_type": "composition",
        "encounter_id": "ENC-1",
        "patient_id": "P-1",
        "narrative": None,
    }
    ctx = _make_ctx([doc])
    resources = _bb_compositions(ctx)
    assert resources == []
    assert any("narrative" in rec.message.lower() for rec in caplog.records)


# --- DocumentReference builder ----------------------------------------------


@pytest.mark.unit
def test_docref_builder_reads_narrative_text():
    doc = {
        "document_id": "doc-1",
        "task_type": "nursing_shift_note",
        "loinc_code": "34746-8",
        "format_type": "free_text",
        "encounter_id": "ENC-1",
        "patient_id": "P-1",
        "author_practitioner_id": "DR-1",
        "authored_datetime": "2026-01-01T00:00:00",
        "language": "en",
    }
    narrative = {
        "text": "nurse note content",
        "sections": {},
        "structured": {},
        "generator": "template",
        "generator_metadata": {},
        "generated_at": "",
        "facts_used": [],
    }
    resource = _build_dref_from_clinical_doc(doc, narrative, "P-1", "us")

    assert resource is not None
    assert resource["resourceType"] == "DocumentReference"
    attachment = resource["content"][0]["attachment"]
    decoded = base64.b64decode(attachment["data"]).decode("utf-8")
    assert decoded == "nurse note content"


@pytest.mark.unit
def test_bb_document_references_merges_narrative_from_doc_dict():
    doc = {
        "document_id": "doc-1",
        "task_type": "nursing_shift_note",
        "loinc_code": "34746-8",
        "format_type": "free_text",
        "encounter_id": "ENC-1",
        "patient_id": "P-1",
        "author_practitioner_id": "DR-1",
        "authored_datetime": "2026-01-01T00:00:00",
        "language": "en",
        "narrative": {
            "text": "nurse note content",
            "sections": {},
            "structured": {},
            "generator": "template",
            "generator_metadata": {},
            "generated_at": "",
            "facts_used": [],
        },
    }
    ctx = _make_ctx([doc])
    resources = _bb_document_references(ctx)
    assert len(resources) == 1
    attachment = resources[0]["content"][0]["attachment"]
    assert base64.b64decode(attachment["data"]).decode("utf-8") == "nurse note content"


@pytest.mark.unit
def test_bb_document_references_skips_stub_with_no_narrative(caplog):
    doc = {
        "document_id": "doc-1",
        "task_type": "nursing_shift_note",
        "loinc_code": "34746-8",
        "format_type": "free_text",
        "encounter_id": "ENC-1",
        "patient_id": "P-1",
        "narrative": None,
    }
    ctx = _make_ctx([doc])
    resources = _bb_document_references(ctx)
    assert resources == []
    assert any("narrative" in rec.message.lower() for rec in caplog.records)
