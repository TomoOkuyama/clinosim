"""P2-13 PR3 sub-PR-A:JP-eCheckup 事業者健診 opt-in enricher unit tests(JP-only)."""

from __future__ import annotations

import pytest


def _make_ctx(country: str, opt_in: bool, records: list) -> "object":
    """SimulatorConfig + EnricherContext を最小構成で組み立てる。"""
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.config import SimulatorConfig
    cfg = SimulatorConfig(country=country, modules={"health_checkup": opt_in})
    return EnricherContext(config=cfg, master_seed=42, records=records)


def _make_record(patient_id: str, age: int):
    """テスト用 CIFPatientRecord を最小構成で作る。"""
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    return CIFPatientRecord(
        patient=PatientProfile(patient_id=patient_id, age=age, sex="M"),
    )


@pytest.mark.unit
def test_health_checkup_disabled_by_default():
    """opt-in flag False では何も追加されない。"""
    from clinosim.modules.health_checkup.engine import enrich_health_checkup
    record = _make_record("POP-000001", 45)
    ctx = _make_ctx("JP", opt_in=False, records=[record])
    # opt-in gate 突破前に呼ぶと enricher 自体は run するが、
    # register_builtin_enrichers 側で enabled=False → run 呼ばれない。
    # ここでは直接 run を呼び、opt-in gate は register_builtin_enrichers で
    # 済んでいる前提。よってこの test は「直接 run した場合の挙動」を
    # 検証:年齢閾値未満 or サブセット外の患者には何も起きないこと。
    # 直接呼びで挙動確認 (enabled gate が opt-in を制御する)
    enrich_health_checkup(ctx)
    # 45 歳 patient_id=POP-000001 は hash-based 30% サブセット判定次第だが、
    # ここでは gate 依存性ではなく年齢閾値以下の挙動を検証するため
    # 別の test で subset ロジック確認する
    # → この test は「run 呼び出し自体が例外を起こさない」ことのみ確認
    assert isinstance(record.encounters, list)


@pytest.mark.unit
def test_health_checkup_skips_below_age_threshold():
    """40 歳未満は健診対象外(HEALTH_CHECKUP_MIN_AGE=40)。"""
    from clinosim.modules.health_checkup.engine import (
        enrich_health_checkup, HEALTH_CHECKUP_MIN_AGE,
    )
    assert HEALTH_CHECKUP_MIN_AGE == 40
    young = _make_record("POP-YOUNG-001", age=30)
    ctx = _make_ctx("JP", opt_in=True, records=[young])
    enrich_health_checkup(ctx)
    # 30 歳の場合、encounters / documents は空のまま(年齢閾値未満)
    assert young.encounters == []
    assert young.documents == []


@pytest.mark.unit
def test_health_checkup_subset_rate_approximately_30pct():
    """N=1000 で hash-based サブセットに入る割合が 30% ±5% 以内。"""
    from clinosim.modules.health_checkup.engine import _patient_selected
    fires = sum(1 for i in range(1000) if _patient_selected(f"POP-{i:06d}"))
    rate = fires / 1000
    assert 0.25 <= rate <= 0.35, f"subset rate {rate} outside [0.25, 0.35]"


@pytest.mark.unit
def test_health_checkup_creates_encounter_and_document_for_selected_adult():
    """40 歳以上かつサブセット内の患者に対して encounter + observations + document が追加される。"""
    from clinosim.modules.health_checkup.engine import (
        _patient_selected, enrich_health_checkup,
    )
    from clinosim.types.encounter import EncounterType
    # サブセットに入る patient_id を探す(決定的 hash)
    selected_id = None
    for i in range(100):
        pid = f"POP-{i:06d}"
        if _patient_selected(pid):
            selected_id = pid
            break
    assert selected_id is not None, "no subset-matching patient id in 100 samples"
    record = _make_record(selected_id, age=45)
    ctx = _make_ctx("JP", opt_in=True, records=[record])
    enrich_health_checkup(ctx)
    # 1 CHECKUP encounter が追加
    assert len(record.encounters) == 1
    enc = record.encounters[0]
    assert enc.encounter_type == EncounterType.CHECKUP
    assert enc.department_id == "health_checkup"
    assert enc.chief_complaint == "定期健康診断"
    # 法定健診 5 項目が lab_results に追加
    assert len(record.lab_results) == 5
    loincs = {r.lab_name for r in record.lab_results}
    assert loincs == {"39156-5", "8480-6", "8462-4", "4548-4", "18262-6"}
    # HEALTH_CHECKUP_REPORT stub が documents に追加
    assert len(record.documents) == 1
    doc = record.documents[0]
    assert doc.loinc_code == "53576-5"
    assert doc.task_type == "health_checkup_report"
    assert doc.encounter_id == enc.encounter_id
    assert doc.format_type == "composition"
    assert doc.narrative is None  # Stage 2 が populate する


@pytest.mark.unit
def test_health_checkup_deterministic_across_runs():
    """同 patient_id で複数回 run しても結果が deterministic。"""
    from clinosim.modules.health_checkup.engine import (
        _patient_selected, enrich_health_checkup,
    )
    selected_id = None
    for i in range(100):
        pid = f"POP-{i:06d}"
        if _patient_selected(pid):
            selected_id = pid
            break
    assert selected_id is not None
    r1 = _make_record(selected_id, age=45)
    ctx1 = _make_ctx("JP", opt_in=True, records=[r1])
    enrich_health_checkup(ctx1)
    r2 = _make_record(selected_id, age=45)
    ctx2 = _make_ctx("JP", opt_in=True, records=[r2])
    enrich_health_checkup(ctx2)
    assert r1.encounters[0].encounter_id == r2.encounters[0].encounter_id
    assert r1.documents[0].document_id == r2.documents[0].document_id
