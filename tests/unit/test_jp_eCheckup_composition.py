"""P2-13 PR3:JP-eCheckup General 健診結果報告書 Composition unit tests(JP-only、opt-in)."""

from __future__ import annotations

import pytest

_PROFILE_URL = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral"
_DOC_TYPE_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_SECTION_SYSTEM = "http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code"


def _jp_checkup_doc():
    return {
        "document_id": "doc-ENC-CHK-001-01",
        "document_type": "HEALTH_CHECKUP_REPORT",
        "loinc_code": "53576-5",
        "format_type": "composition",
        "patient_id": "POP-000001",
        "encounter_id": "ENC-CHK-001",
        "author_practitioner_id": "PRAC-JP-001",
        "authored_datetime": "2026-04-15T09:00:00",
        "language": "ja",
        "period_start": "2026-04-15T09:00:00",
        "period_end": "2026-04-15T10:00:00",
        "narrative": {
            "sections": {
                "checkup_lab_results": (
                    "【身体計測】BMI 標準範囲内。\n【血圧】収縮期・拡張期ともに基準内。\n総合判定:A(異常なし)。"
                ),
                "checkup_questionnaire": ("【既往歴】特記事項なし。\n【自覚症状】特記事項なし。"),
            }
        },
    }


@pytest.mark.unit
def test_jp_eCheckup_composition_type_uses_doc_typecodes():
    """type.coding が doc-typecodes system + 53576-5 を含むこと。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_checkup_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    systems = {c.get("system") for c in comp["type"]["coding"]}
    assert _DOC_TYPE_SYSTEM in systems
    assert "http://loinc.org" in systems
    assert comp["title"] == "検診・健診報告書"


@pytest.mark.unit
def test_jp_eCheckup_composition_has_profile():
    """JP_Composition_eCheckupGeneral profile URL が meta.profile に含まれること。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_checkup_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    profs = comp.get("meta", {}).get("profile", [])
    assert _PROFILE_URL in profs


@pytest.mark.unit
def test_jp_eCheckup_composition_sections_flat_2():
    """事業者健診の 2 必須 section(01031 + 01032)が flat 構造で emit されること。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_checkup_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    top = comp["section"]
    codes = [s["code"]["coding"][0]["code"] for s in top]
    assert codes == ["01031", "01032"], codes
    for s in top:
        assert s["code"]["coding"][0]["system"] == _SECTION_SYSTEM


@pytest.mark.unit
def test_jp_eCheckup_composition_section_content():
    """section.text.div に narrative sections dict の内容が反映されること。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_checkup_doc()
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    by_code = {s["code"]["coding"][0]["code"]: s for s in comp["section"]}
    assert "身体計測" in by_code["01031"]["text"]["div"]
    assert "既往歴" in by_code["01032"]["text"]["div"]


@pytest.mark.unit
def test_us_locale_never_emits_eCheckup_profile():
    """lang!='ja' の場合、53576-5 でも eCheckup profile は付与されないこと。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _jp_checkup_doc()
    doc["language"] = "en"
    comp = _build_composition(doc, doc["narrative"]["sections"], "en")
    profs = comp.get("meta", {}).get("profile", [])
    assert not any(p.startswith("http://jpfhir.jp/fhir/eCheckup/") for p in profs), profs


@pytest.mark.unit
def test_health_checkup_report_optin_gate():
    """SimulatorConfig.modules['health_checkup']=False では発行なし。"""
    from clinosim.types.config import SimulatorConfig

    cfg = SimulatorConfig()
    assert cfg.module_enabled("health_checkup") is False


@pytest.mark.unit
def test_health_checkup_report_optin_enabled():
    """SimulatorConfig.modules['health_checkup']=True で opt-in 有効になること。"""
    from clinosim.types.config import SimulatorConfig

    cfg = SimulatorConfig(modules={"health_checkup": True})
    assert cfg.module_enabled("health_checkup") is True
