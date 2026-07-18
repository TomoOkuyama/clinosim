"""P2-13 PR2b:JP-CLINS 診療情報提供書 Composition unit tests(JP-only)."""

from __future__ import annotations

import pytest

_PROFILE_URL = "http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral"
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"


def _jp_referral_doc():
    return {
        "document_id": "doc-ENC-001-02",
        "document_type": "REFERRAL_NOTE",
        "loinc_code": "57133-1",
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
                "referring_institution": "紹介元:当院(急性期一般病棟)。",
                "referral_destination": "紹介先:他院。継続加療目的。",
                "referral_purpose": "紹介目的:継続加療のため。",
                "diagnoses_and_complaint": "【傷病名】\n1. 細菌性肺炎（J13）\n\n【主訴】\n発熱・咳嗽",
                "present_illness_ref": "3日前より発熱と咳嗽を認め、当院受診となった。",
            }
        },
    }


@pytest.mark.unit
def test_jp_clins_referral_composition_type():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    systems = {c.get("system") for c in comp["type"]["coding"]}
    # Session 57 v3 fix: eReferral profile constrains type.coding to max=1,
    # so only the doc-typecodes coding is emitted (LOINC dropped).
    assert _DOC_TYPE_SYSTEM in systems
    assert "http://loinc.org" not in systems
    assert len(comp["type"]["coding"]) == 1
    assert comp["title"] == "診療情報提供書"


@pytest.mark.unit
def test_jp_clins_referral_composition_profile():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    profs = comp.get("meta", {}).get("profile", [])
    assert _PROFILE_URL in profs


@pytest.mark.unit
def test_jp_clins_referral_composition_top_level_sections():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top = comp["section"]
    top_codes = [s["code"]["coding"][0]["code"] for s in top]
    assert top_codes == ["920", "910", "300"], top_codes
    for s in top:
        assert s["code"]["coding"][0]["system"] == _SECTION_SYSTEM


@pytest.mark.unit
def test_jp_clins_referral_composition_structural_children():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    structural = [s for s in comp["section"] if s["code"]["coding"][0]["code"] == "300"][0]
    child_codes = [c["code"]["coding"][0]["code"] for c in structural["section"]]
    assert child_codes == ["950", "340", "360"], child_codes


@pytest.mark.unit
def test_jp_clins_referral_composition_section_content():
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_referral_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top_by_code = {s["code"]["coding"][0]["code"]: s for s in comp["section"]}
    # 920 紹介元
    assert "当院" in top_by_code["920"]["text"]["div"]
    # 910 紹介先
    assert "他院" in top_by_code["910"]["text"]["div"]
    # 300 structural nested
    structural_by_code = {c["code"]["coding"][0]["code"]: c for c in top_by_code["300"]["section"]}
    assert "継続加療" in structural_by_code["950"]["text"]["div"]
    assert "細菌性肺炎" in structural_by_code["340"]["text"]["div"]
    assert "3日前" in structural_by_code["360"]["text"]["div"]


@pytest.mark.unit
def test_referral_note_fires_deterministic():
    """20% fire rate は (encounter_id, patient_id) ごとに決定的であること。"""
    from clinosim.modules.document.engine import _referral_note_fires

    # Same inputs → same output
    assert _referral_note_fires("ENC-1", "P1") == _referral_note_fires("ENC-1", "P1")
    # Different encounter_id → possibly different (but deterministic)
    # This just documents that _fires is deterministic (not a probability test)
    outcomes = {_referral_note_fires(f"ENC-{i}", "P1") for i in range(1000)}
    assert outcomes == {True, False}, "fires should hit both branches over 1000 samples"


@pytest.mark.unit
def test_referral_note_fire_rate_approximately_20pct():
    """N=2000 で実測発火率が 20% ±5% 以内であること。"""
    from clinosim.modules.document.engine import _referral_note_fires

    fires = sum(1 for i in range(2000) if _referral_note_fires(f"ENC-{i:04d}", f"P-{i:04d}"))
    rate = fires / 2000
    assert 0.15 <= rate <= 0.25, f"referral fire rate {rate} outside [0.15, 0.25]"
