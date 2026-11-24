"""Issue #3697: a Composition section's code.text names the section, not the LOINC display of its code."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

pytestmark = pytest.mark.unit


def _soap(lang: str) -> dict:
    return {
        "document_id": "doc-ENC-001-soap-01",
        "document_type": "OUTPATIENT_SOAP",
        "loinc_code": "34131-3",
        "format_type": "composition",
        "patient_id": "POP-000001",
        "encounter_id": "ENC-001",
        "author_practitioner_id": "PRAC-001",
        "authored_datetime": "2026-03-01T10:00:00",
        "language": lang,
        "narrative": {"sections": {"subjective": "s", "objective": "o", "assessment": "a", "plan": "p"}},
    }


def _plan_section(lang: str, country: str) -> dict:
    doc = _soap(lang)
    comp = _build_composition(doc, doc["narrative"]["sections"], lang, country=country)
    plan = [s for s in comp["section"] if s["code"]["coding"][0]["code"] == "18776-5"]
    assert len(plan) == 1
    return plan[0]


def test_ja_soap_plan_section_text_is_its_title_not_the_admission_plan_form() -> None:
    sec = _plan_section("ja", "JP")
    assert sec["title"] == "計画"
    assert sec["code"]["text"] == "計画"
    assert sec["code"]["coding"][0]["code"] == "18776-5"


def test_en_soap_plan_section_text_is_its_title() -> None:
    sec = _plan_section("en", "US")
    assert sec["code"]["text"] == sec["title"] == "Plan"
    assert sec["code"]["coding"][0]["code"] == "18776-5"


def test_every_section_text_equals_its_title() -> None:
    doc = _soap("ja")
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja", country="JP")
    for sec in comp["section"]:
        assert sec["code"]["text"] == sec["title"]


def test_admission_care_plan_document_type_keeps_the_loinc_display() -> None:
    doc = _soap("ja")
    doc.update({"document_type": "ADMISSION_CARE_PLAN", "loinc_code": "18776-5"})
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja", country="JP")
    assert comp["type"]["coding"][0]["code"] == "18776-5"
    assert comp["type"]["text"] == "入院診療計画書"
