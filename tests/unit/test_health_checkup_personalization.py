"""P2-13 PR3 sub-PR-B 高度化(session 48):健診 5 項目の PatientProfile 反映テスト.

健診 lab 値は fixed(22.5/118/76/5.4/118)から PatientProfile + chronic_conditions
に応じた個別化に変更。以下を検証:

1. patient.bmi / baseline_vitals から実測値が引き出される
2. DM(E11)保有時は HbA1c が明確に上昇する
3. E78(脂質異常症)保有時は LDL が明確に上昇する
4. 同 seed + 同 patient → byte-identical(AD-16)
5. 患者間で値が分散する(全員同一値ではない)
"""
from __future__ import annotations

import pytest


def _make_ctx_with_records(records: list, master_seed: int = 42) -> object:
    from clinosim.simulator.enrichers import EnricherContext
    from clinosim.types.config import SimulatorConfig
    cfg = SimulatorConfig(country="JP", modules={"health_checkup": True})
    return EnricherContext(config=cfg, master_seed=master_seed, records=records)


def _find_selected_pid(start: int = 0) -> str:
    """`_patient_selected` に入る patient_id を検索。"""
    from clinosim.modules.health_checkup.engine import _patient_selected
    for i in range(start, start + 200):
        pid = f"POP-{i:06d}"
        if _patient_selected(pid):
            return pid
    raise AssertionError("no selected patient in range")


def _make_record(patient_id: str, **overrides):
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    kwargs = {"patient_id": patient_id, "age": 55, "sex": "M"}
    kwargs.update(overrides)
    return CIFPatientRecord(patient=PatientProfile(**kwargs))


def _run_and_extract_labs(records: list) -> dict[str, float]:
    """enrich_health_checkup を実行し、追加された CHECKUP record の
    lab_results を {LOINC: value} で返す。"""
    from clinosim.modules.health_checkup.engine import enrich_health_checkup
    n_before = len(records)
    ctx = _make_ctx_with_records(records)
    enrich_health_checkup(ctx)
    assert len(records) == n_before + 1
    checkup_record = records[-1]
    return {r.lab_name: r.value for r in checkup_record.lab_results}


@pytest.mark.unit
def test_bmi_reflects_patient_profile():
    """patient.bmi 大 → lab BMI 大(± noise 0.3)。"""
    pid = _find_selected_pid()
    lean = _make_record(pid, bmi=20.0)
    labs_lean = _run_and_extract_labs([lean])
    obese = _make_record(pid, bmi=32.0)
    labs_obese = _run_and_extract_labs([obese])
    assert labs_lean["39156-5"] < 22.0
    assert labs_obese["39156-5"] > 30.0


@pytest.mark.unit
def test_bp_reflects_baseline_vitals():
    """baseline_vitals.systolic_bp/diastolic_bp が SBP/DBP に反映される。"""
    from clinosim.types.patient import BaselineVitals
    pid = _find_selected_pid()
    normo = _make_record(pid, baseline_vitals=BaselineVitals(systolic_bp=118, diastolic_bp=72))
    labs_n = _run_and_extract_labs([normo])
    hyper = _make_record(pid, baseline_vitals=BaselineVitals(systolic_bp=160, diastolic_bp=98))
    labs_h = _run_and_extract_labs([hyper])
    # ± 5 mmHg noise を許容しても明確に分離される
    assert labs_n["8480-6"] < 130
    assert labs_h["8480-6"] > 145
    assert labs_n["8462-4"] < 80
    assert labs_h["8462-4"] > 90


@pytest.mark.unit
def test_hba1c_elevated_for_dm_patient():
    """E11(2 型糖尿病)保有時、HbA1c が非 DM 患者より明確に高い。"""
    from clinosim.types.patient import ChronicCondition
    pid = _find_selected_pid()
    healthy = _make_record(pid)
    labs_healthy = _run_and_extract_labs([healthy])
    dm = _make_record(
        pid,
        chronic_conditions=[
            ChronicCondition(code="E11", system="icd-10-cm", glycemic_control=0.3),
        ],
    )
    labs_dm = _run_and_extract_labs([dm])
    assert labs_healthy["4548-4"] < 6.0
    # glycemic_control=0.3 → HBA1C_BEST(6.0) + 0.7*6.0 = 10.2%,noise ±0.15 %
    assert labs_dm["4548-4"] >= 9.5


@pytest.mark.unit
def test_ldl_elevated_for_dyslipidemia_patient():
    """E78(脂質異常症)保有時、LDL が健常者より約 40 mg/dL 高い。"""
    from clinosim.types.patient import ChronicCondition
    pid = _find_selected_pid()
    healthy = _make_record(pid)
    labs_h = _run_and_extract_labs([healthy])
    dyslip = _make_record(
        pid,
        chronic_conditions=[ChronicCondition(code="E78", system="icd-10-cm")],
    )
    labs_d = _run_and_extract_labs([dyslip])
    delta = labs_d["18262-6"] - labs_h["18262-6"]
    # +40 baseline lift + ± 10 mg/dL noise、明確に上昇
    assert delta > 20.0


@pytest.mark.unit
def test_ldl_lowered_by_statin_medication():
    """スタチン系服薬中は LDL が薬理的に低下(-30 mg/dL)。"""
    from clinosim.types.patient import ChronicCondition
    pid = _find_selected_pid()
    dyslip_no_statin = _make_record(
        pid,
        chronic_conditions=[ChronicCondition(code="E78", system="icd-10-cm")],
    )
    labs_no = _run_and_extract_labs([dyslip_no_statin])
    dyslip_statin = _make_record(
        pid,
        chronic_conditions=[ChronicCondition(code="E78", system="icd-10-cm")],
        current_medications=["Atorvastatin"],
    )
    labs_st = _run_and_extract_labs([dyslip_statin])
    # -30 baseline + ±10 noise、明確に低下(統計的余裕あり)
    assert labs_no["18262-6"] - labs_st["18262-6"] > 15.0


@pytest.mark.unit
def test_deterministic_across_runs():
    """同 seed + 同 patient → lab 値が byte-identical(AD-16)。"""
    pid = _find_selected_pid()
    labs1 = _run_and_extract_labs([_make_record(pid)])
    labs2 = _run_and_extract_labs([_make_record(pid)])
    assert labs1 == labs2


@pytest.mark.unit
def test_lab_values_vary_across_patients():
    """複数患者で lab 値が全員同一にならない(sub-seed が patient_id 依存)。"""
    from clinosim.modules.health_checkup.engine import _patient_selected
    records = []
    seen = 0
    for i in range(200):
        pid = f"POP-{i:06d}"
        if _patient_selected(pid):
            records.append(_make_record(pid))
            seen += 1
            if seen >= 5:
                break
    assert seen == 5
    from clinosim.modules.health_checkup.engine import enrich_health_checkup
    ctx = _make_ctx_with_records(records)
    enrich_health_checkup(ctx)
    # 5 患者分の CHECKUP record が追加された
    checkup_records = records[-5:]
    bmis = {r.lab_results[0].value for r in checkup_records}
    # 5 値が全て同一なら sub-seed が効いていない
    assert len(bmis) >= 4  # noise で稀に一致し得るが 4 以上ユニーク


@pytest.mark.unit
def test_interpretation_and_reference_range_populated():
    """OrderResult.interpretation と reference_range が非空になる。"""
    pid = _find_selected_pid()
    labs = _run_and_extract_labs([_make_record(pid)])
    from clinosim.modules.health_checkup.engine import enrich_health_checkup

    # 直接 re-run して構造検証
    from clinosim.types.output import CIFPatientRecord
    from clinosim.types.patient import PatientProfile
    rec = CIFPatientRecord(patient=PatientProfile(patient_id=pid, age=55, sex="M"))
    ctx = _make_ctx_with_records([rec])
    enrich_health_checkup(ctx)
    checkup = ctx.records[-1]
    for r in checkup.lab_results:
        assert r.interpretation in {"N", "H", "L"}
        assert r.reference_range  # 非空
        # flag は None or "H"(sub-PR-B 現状は "L" 出力なし)
        assert r.flag in {None, "H"}
    assert labs  # 上の値検証と整合
