"""P2-13 PR2a Task 4:JP-CLINS 退院時サマリー Composition unit tests(JP-only)."""

from __future__ import annotations

import pytest

_PROFILE_URL = "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"


def _jp_ds_doc():
    return {
        "document_id": "doc-ENC-001-01",
        "document_type": "DISCHARGE_SUMMARY",
        "loinc_code": "18842-5",
        "format_type": "composition",
        "patient_id": "POP-000001",
        "encounter_id": "ENC-001",
        "author_practitioner_id": "PRAC-JP-001",
        "authored_datetime": "2026-01-20T10:00:00",
        "language": "ja",
        "period_start": "2026-01-15T09:00:00",
        "period_end": "2026-01-20T10:00:00",
        "narrative": {
            "sections": {
                "admission_reason": "細菌性肺炎のため入院となった。",
                "admission_details": "2026-01-15、救急外来受診後、内科病棟に入院した。",
                "admission_diagnoses": "1. 細菌性肺炎（J13）",
                "chief_complaint": "発熱・咳嗽",
                "present_illness": "3日前より発熱と咳嗽を認め、当院受診となった。",
            }
        },
    }


def _us_ds_doc():
    return {
        "document_id": "doc-ENC-101-01",
        "document_type": "DISCHARGE_SUMMARY",
        "loinc_code": "18842-5",
        "format_type": "composition",
        "patient_id": "POP-000002",
        "encounter_id": "ENC-101",
        "author_practitioner_id": "PRAC-US-001",
        "authored_datetime": "2026-01-20T10:00:00",
        "language": "en",
        "period_start": "2026-01-15T09:00:00",
        "period_end": "2026-01-20T10:00:00",
        "narrative": {
            "sections": {
                "admission_summary": "Admitted for bacterial pneumonia.",
                "hospital_course": "Improved on ceftriaxone.",
                "discharge_diagnoses": "1. Bacterial pneumonia (J13)",
                "discharge_medications": "amoxicillin-clavulanate 500mg PO TID x7d",
                "discharge_instructions": "Follow up in 1 week.",
                "follow_up": "PCP in 7 days",
            }
        },
    }


@pytest.mark.unit
def test_jp_clins_composition_type_uses_doc_typecodes():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    assert any(c.get("system") == _DOC_TYPE_SYSTEM and c.get("code") == "18842-5" for c in comp["type"]["coding"]), (
        comp["type"]
    )


@pytest.mark.unit
def test_jp_clins_composition_has_profile():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    profs = comp.get("meta", {}).get("profile", [])
    assert _PROFILE_URL in profs


@pytest.mark.unit
def test_jp_clins_composition_has_nested_structural_section():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top = comp["section"]
    # Exactly one top-level section (300 構造情報) that nests 5 required children.
    assert len(top) == 1, top
    parent = top[0]
    parent_code = parent["code"]["coding"][0]
    assert parent_code["system"] == _SECTION_SYSTEM
    assert parent_code["code"] == "300"
    children = parent["section"]
    child_codes = {c["code"]["coding"][0]["code"] for c in children}
    assert child_codes == {"312", "322", "342", "352", "360"}


@pytest.mark.unit
def test_jp_clins_composition_child_section_text_div():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    parent = comp["section"][0]
    children_by_code = {c["code"]["coding"][0]["code"]: c for c in parent["section"]}
    # 312 = admission_reason
    assert "細菌性肺炎" in children_by_code["312"]["text"]["div"]
    # 352 = chief_complaint
    assert "発熱" in children_by_code["352"]["text"]["div"]
    # 360 = present_illness
    assert "3日前" in children_by_code["360"]["text"]["div"]


@pytest.mark.unit
def test_jp_clins_composition_title_is_ja():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    assert comp["title"] == "退院時サマリー"


@pytest.mark.unit
def test_us_discharge_summary_composition_unchanged():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _us_ds_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "en")
    # No JP-CLINS profile
    profs = comp.get("meta", {}).get("profile", [])
    assert not any(p.startswith("http://jpfhir.jp/fhir/eDischargeSummary/") for p in profs), profs
    # Type uses LOINC only, no doc-typecodes leak
    systems = {c.get("system") for c in comp["type"]["coding"]}
    assert "http://loinc.org" in systems
    assert _DOC_TYPE_SYSTEM not in systems
    # Flat 6 sections at top level (no nesting)
    assert len(comp["section"]) == 6
    # No JP section system leaked
    for s in comp["section"]:
        code_coding = s.get("code", {}).get("coding", [])
        for cc in code_coding:
            assert cc.get("system") != _SECTION_SYSTEM
