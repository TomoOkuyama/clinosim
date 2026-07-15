"""P2-13 PR3 sub-PR-D:JP-eCheckup 3 健診種別の section code dispatch tests(JP-only)."""

from __future__ import annotations

import pytest

_SECTION_SYSTEM = "http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code"


def _make_checkup_doc(checkup_type: str):
    """checkup_type 指定の HEALTH_CHECKUP_REPORT stub。"""
    return {
        "document_id": "doc-CHK-001-01",
        "document_type": "HEALTH_CHECKUP_REPORT",
        "loinc_code": "53576-5",
        "format_type": "composition",
        "patient_id": "POP-000001",
        "encounter_id": "CHK-001",
        "author_practitioner_id": "PRAC-JP-001",
        "authored_datetime": "2026-04-15T09:00:00",
        "language": "ja",
        "period_start": "2026-04-15T09:00:00",
        "period_end": "2026-04-15T10:00:00",
        "checkup_type": checkup_type,
        "narrative": {
            "sections": {
                "checkup_lab_results": "BMI 22.5 標準。",
                "checkup_questionnaire": "既往歴なし。",
            }
        },
    }


@pytest.mark.unit
def test_occupational_dispatches_to_01031_01032():
    """事業者健診(occupational)は 01031 + 01032 に dispatch。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _make_checkup_doc("occupational")
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    codes = [s["code"]["coding"][0]["code"] for s in comp["section"]]
    assert codes == ["01031", "01032"]
    for s in comp["section"]:
        assert s["code"]["coding"][0]["system"] == _SECTION_SYSTEM


@pytest.mark.unit
def test_specific_dispatches_to_01011_01012():
    """特定健診(specific)は 01011 + 01012 に dispatch。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _make_checkup_doc("specific")
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    codes = [s["code"]["coding"][0]["code"] for s in comp["section"]]
    assert codes == ["01011", "01012"]


@pytest.mark.unit
def test_regional_union_dispatches_to_01021_01022():
    """広域連合健診(regional_union)は 01021 + 01022 に dispatch。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _make_checkup_doc("regional_union")
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    codes = [s["code"]["coding"][0]["code"] for s in comp["section"]]
    assert codes == ["01021", "01022"]


@pytest.mark.unit
def test_missing_checkup_type_falls_back_to_occupational():
    """checkup_type 未指定は事業者健診に fallback(既存 sub-PR-A/B 互換)。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _make_checkup_doc("")
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    codes = [s["code"]["coding"][0]["code"] for s in comp["section"]]
    assert codes == ["01031", "01032"]


@pytest.mark.unit
def test_unknown_checkup_type_falls_back_to_occupational():
    """未知の checkup_type も fallback(defensive)。"""
    from clinosim.modules.output._fhir_composition import _build_composition

    doc = _make_checkup_doc("gakko")  # 学校健診 = 未対応
    comp = _build_composition(doc, doc["narrative"]["sections"], "ja")
    codes = [s["code"]["coding"][0]["code"] for s in comp["section"]]
    assert codes == ["01031", "01032"]


# ─────────────────────────────────────────────────────────────────
# Enricher 側の age-based 種別選択 test
# ─────────────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.parametrize(
    "age,expected",
    [
        (40, "occupational"),
        (55, "occupational"),
        (64, "occupational"),
        (65, "specific"),
        (74, "specific"),
        (75, "regional_union"),
        (90, "regional_union"),
    ],
)
def test_pick_checkup_type_by_age(age, expected):
    """年齢帯 → 健診種別の決定的マッピング。"""
    from clinosim.modules.health_checkup.engine import _pick_checkup_type

    assert _pick_checkup_type(age) == expected


@pytest.mark.unit
def test_enricher_sets_checkup_type_on_document():
    """enricher が生成する ClinicalDocument に checkup_type が反映されること。"""
    from clinosim.modules.health_checkup.engine import (
        _patient_selected,
        enrich_health_checkup,
    )
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.config import SimulatorConfig
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile

    # サブセットに入る patient_id を探す
    selected_id = None
    for i in range(100):
        pid = f"POP-{i:06d}"
        if _patient_selected(pid):
            selected_id = pid
            break
    assert selected_id is not None

    # 65 歳(特定健診対象)で test
    record = CIFPatientRecord(
        patient=PatientProfile(patient_id=selected_id, age=68, sex="M"),
    )
    cfg = SimulatorConfig(country="JP", modules={"health_checkup": True})
    ctx = EnricherContext(config=cfg, master_seed=42, records=[record])
    enrich_health_checkup(ctx)
    # 新規 record が追加され、doc.checkup_type = "specific" になっていること
    assert len(ctx.records) == 2
    checkup_record = ctx.records[1]
    doc = checkup_record.documents[0]
    assert doc.checkup_type == "specific"
    # encounter.chief_complaint も 特定健診 になっていること
    enc = checkup_record.encounters[0]
    assert enc.chief_complaint == "特定健診"
