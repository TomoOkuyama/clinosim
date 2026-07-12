"""JP-eCheckup 事業者健診 opt-in module — POST_RECORDS enricher(JP-only).

opt-in 制御:``SimulatorConfig.modules["health_checkup"]=True`` かつ
country=JP のときのみ発火する。default OFF で急性期病院想定を保つ。

サブセット選定:
- 40 歳以上の成人患者から決定的 30%(SHA-256 hash on patient_id、
  ``HEALTH_CHECKUP_SUBSET_RATE`` で調整可)。
- 各患者につき年 1 回、simulation snapshot 手前の日付に 1 CHECKUP encounter。
- 新規 RNG 追加なし(hash 決定的)、AD-16 準拠。

生成物:
- ``record.encounters`` に CHECKUP encounter(単日、退院同日)を append
- ``record.lab_results`` に法定健診項目 5 種の OrderResult を append
  (BMI / 収縮期 BP / 拡張期 BP / HbA1c / LDL コレステロール)
- ``record.documents`` に HEALTH_CHECKUP_REPORT の ClinicalDocument stub
  (narrative=None、Stage 2 TemplateNarrativePass が populate)

FHIR emit は _fhir_composition.py の JP-eCheckup builder が担う。
Composition.section の text.div は narrative pass が入れる。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.clinical import ClinicalDocument
from clinosim.types.encounter import (
    Encounter,
    EncounterStatus,
    EncounterType,
    OrderResult,
)

# 40 歳以上成人に対する決定的サブセット率。労安衛法定健診は年 1 回全員
# 対象だが、simulation cohort ではサンプル効果を考慮し MVP 30% とする。
# 将来 sub-PR で PatientProfile.employment_status を参照して事業所勤務者に
# 絞る等の高度化余地あり。
HEALTH_CHECKUP_SUBSET_RATE = 0.30

# 対象年齢下限(労安衛法定健診相当)
HEALTH_CHECKUP_MIN_AGE = 40

# 年齢帯 → 健診種別の decision map(sub-PR-D)。
#   40-64: 事業者健診(occupational、労安衛法定)
#   65-74: 特定健診(specific、40-74 保険 base)
#   75+:   広域連合健診(regional_union、後期高齢者医療)
# 実務では 40-64 でも保険加入者は特定健診対象になる場合があるが、MVP は
# 年齢帯単一 dispatch で単純化する。将来 sub-PR で保険種別 / 就業状態を
# 参照した精緻化余地あり。
def _pick_checkup_type(age: int) -> str:
    if age >= 75:
        return "regional_union"
    if age >= 65:
        return "specific"
    return "occupational"


# 種別ごとの主訴表示
_CHECKUP_TYPE_CHIEF_COMPLAINT: dict[str, str] = {
    "occupational":   "事業者健診",
    "specific":       "特定健診",
    "regional_union": "広域連合健診",
}

# 法定健診項目の LOINC コードと単位。実測値は
# `_derive_checkup_values(patient, rng)` が PatientProfile と chronic_conditions
# から個別化する(sub-PR-B 高度化, session 48)。
_CHECKUP_ITEMS: list[dict[str, str]] = [
    {"loinc": "39156-5", "key": "bmi",     "unit": "kg/m2"},
    {"loinc": "8480-6",  "key": "sbp",     "unit": "mmHg"},
    {"loinc": "8462-4",  "key": "dbp",     "unit": "mmHg"},
    {"loinc": "4548-4",  "key": "hba1c",   "unit": "%"},
    {"loinc": "18262-6", "key": "ldl",     "unit": "mg/dL"},
]

# 糖尿病を示す ICD-10 code(chronic_conditions.code で判定)
_DM_CODES = {"E10", "E11", "E13", "E11.9", "E10.9", "E13.9"}
# 脂質異常症を示す ICD-10 code
_DYSLIPIDEMIA_CODES = {"E78", "E78.0", "E78.1", "E78.2", "E78.4", "E78.5"}


def _derive_checkup_values(patient: Any, rng: np.random.Generator) -> dict[str, float]:
    """患者プロファイルと chronic_conditions から健診 5 項目の実測値を導出。

    - BMI:``patient.bmi`` に測定日変動を乗せる(sd 0.3 kg/m²)。
    - SBP/DBP:``patient.baseline_vitals`` を base とし、日間変動 sd 5.0/3.5 mmHg。
      HT(I10)は FP-I10(session 38)で baseline_vitals に既に反映済み。
    - HbA1c:糖尿病(E10/E11)保有時は ``glycemic_control`` から
      ``hba1c_from_glycemic_control`` を再利用(条件側未設定なら中央値 0.5)。
      非糖尿病は 5.1 + 年齢係数 0.003(HBA1C_NONDM_BASE パターンを踏襲)。
    - LDL:年齢/性別 baseline に脂質異常症(E78)の上乗せ、薬物制御は
      current_medications にスタチン系薬名が含まれる場合に -30 mg/dL。

    RNG は per-patient sub-seed 由来(``derive_sub_seed``)、AD-16 準拠。
    測定ノイズは grade 境界を跨がない小さめの値に留める。
    """
    from clinosim.modules.physiology.engine import (
        HBA1C_NONDM_BASE,
        hba1c_from_glycemic_control,
    )

    age = int(_o(patient, "age", 60) or 60)
    sex = str(_o(patient, "sex", "M") or "M").upper()
    chronic = _o(patient, "chronic_conditions", []) or []
    meds = _o(patient, "current_medications", []) or []

    # BMI:profile が持つ値に測定日変動を足す(patient.bmi は生成時決定)
    bmi_base = float(_o(patient, "bmi", 22.5) or 22.5)
    bmi = float(np.clip(bmi_base + rng.normal(0.0, 0.3), 10.0, 60.0))

    # SBP/DBP:baseline_vitals が HT stage(FP-I10)を反映済み
    bv = _o(patient, "baseline_vitals", None)
    sbp_base = float(_o(bv, "systolic_bp", 120) if bv is not None else 120)
    dbp_base = float(_o(bv, "diastolic_bp", 75) if bv is not None else 75)
    sbp = float(np.clip(sbp_base + rng.normal(0.0, 5.0), 80.0, 220.0))
    dbp = float(np.clip(dbp_base + rng.normal(0.0, 3.5), 40.0, 140.0))

    # HbA1c:DM 有無で分岐
    dm_condition = None
    for c in chronic:
        code = _o(c, "code", "") or ""
        # 完全一致 or prefix match(E11 は E11.9 等の parent も検出)
        if code in _DM_CODES or any(code.startswith(p + ".") for p in ("E10", "E11", "E13")):
            dm_condition = c
            break
    if dm_condition is not None:
        gc = _o(dm_condition, "glycemic_control", None)
        if gc is None:
            gc = 0.5  # 未設定時は中央値
        hba1c_true = hba1c_from_glycemic_control(float(gc))
        hba1c = float(np.clip(hba1c_true + rng.normal(0.0, 0.15), 4.0, 15.0))
    else:
        hba1c_base = HBA1C_NONDM_BASE + max(0, age - 40) * 0.003
        hba1c = float(np.clip(hba1c_base + rng.normal(0.0, 0.12), 4.0, 7.0))

    # LDL:年齢/性別 baseline + E78 modifier + statin 逆補正
    # baseline は Framingham + JP 特定健診公表統計に基づく大まかな中央値
    if sex == "F":
        ldl_base = 105.0 + max(0, age - 40) * 0.7  # 女性は加齢で上昇強め(閉経後)
    else:
        ldl_base = 115.0 + max(0, age - 40) * 0.3
    has_dyslipidemia = any(
        (_o(c, "code", "") or "").split(".")[0] == "E78" or
        (_o(c, "code", "") or "") in _DYSLIPIDEMIA_CODES
        for c in chronic
    )
    if has_dyslipidemia:
        ldl_base += 40.0  # 未治療脂質異常症の相対上昇
    # スタチン系薬(-statin 末尾)服用で薬理制御
    on_statin = any(
        isinstance(m, str) and m.lower().endswith("statin")
        for m in meds
    )
    if on_statin:
        ldl_base -= 30.0
    ldl = float(np.clip(ldl_base + rng.normal(0.0, 10.0), 40.0, 300.0))

    return {"bmi": bmi, "sbp": sbp, "dbp": dbp, "hba1c": hba1c, "ldl": ldl}


def _patient_selected(patient_id: str) -> bool:
    """患者 id の SHA-256 hash で 30% サブセットに入るかを決定的判定。"""
    digest = hashlib.sha256(patient_id.encode("utf-8")).digest()
    frac = int.from_bytes(digest[:8], "big") / (1 << 64)
    return frac < HEALTH_CHECKUP_SUBSET_RATE


def _pick_checkup_date(snapshot_date: date | str | None) -> date:
    """健診日を snapshot_date の 90 日前あたりに固定する(決定的)。

    実務では年度末 3 月前後に法定健診を実施する事業所が多いため、
    snapshot 手前の Q4 相当を default 位置とする。将来 sub-PR で
    事業所別の実施月分布を導入可能。

    SimulatorConfig.snapshot_date は Pydantic により str 化されている
    場合があるため、ISO 8601 文字列も受け付ける(YYYY-MM-DD)。
    """
    if snapshot_date is None:
        snapshot_date = date(2026, 12, 31)
    elif isinstance(snapshot_date, str):
        # ISO 8601 の YYYY-MM-DD を date に変換
        try:
            snapshot_date = date.fromisoformat(snapshot_date.split("T")[0])
        except ValueError:
            snapshot_date = date(2026, 12, 31)
    return snapshot_date - timedelta(days=90)


def _build_checkup_encounter(
    patient_id: str, checkup_date: date, encounter_seq: int,
    checkup_type: str = "occupational",
) -> Encounter:
    """CHECKUP encounter を組み立てる(1 日完結、退院同日)。

    chief_complaint は健診種別を反映(occupational=事業者健診 等)、
    将来 FHIR emit 側でこの表示を Encounter.reasonCode などに含める余地。
    """
    enc_id = f"CHK-{patient_id}-{encounter_seq:03d}"
    admission_dt = datetime.combine(checkup_date, datetime.min.time().replace(hour=9))
    discharge_dt = admission_dt + timedelta(hours=2)
    cc = _CHECKUP_TYPE_CHIEF_COMPLAINT.get(checkup_type, "定期健康診断")
    return Encounter(
        encounter_id=enc_id,
        patient_id=patient_id,
        encounter_type=EncounterType.CHECKUP,
        status=EncounterStatus.COMPLETED,
        department_id="health_checkup",
        admission_datetime=admission_dt,
        discharge_datetime=discharge_dt,
        chief_complaint=cc,
        # 健診は routine、緊急でも救急経由でもない
        priority="R",
        admit_source="outp",
        discharge_disposition="home",
    )


def _interp_for(loinc: str, value: float) -> tuple[str, str]:
    """LOINC 別に (interpretation, reference_range) を返す。

    interpretation は HL7 v2 Table 0078 の "N" / "H" / "L"(健診 5 項目は L は
    実運用されないが将来のため保持)。BP は SBP と DBP を独立に扱う。
    """
    if loinc == "39156-5":  # BMI
        return ("H" if value >= 25.0 else "N", "18.5-24.9 kg/m2")
    if loinc == "8480-6":   # SBP
        return ("H" if value >= 130.0 else "N", "<130 mmHg")
    if loinc == "8462-4":   # DBP
        return ("H" if value >= 85.0 else "N", "<85 mmHg")
    if loinc == "4548-4":   # HbA1c
        return ("H" if value >= 5.6 else "N", "<5.6 %")
    if loinc == "18262-6":  # LDL
        return ("H" if value >= 120.0 else "N", "<120 mg/dL")
    return ("N", "")


def _build_checkup_lab_results(
    patient_id: str, patient: Any, checkup_date: date,
    rng: np.random.Generator,
) -> list[OrderResult]:
    """法定健診 5 項目の OrderResult を組み立てる(sub-PR-B 高度化)。

    ``_derive_checkup_values`` で PatientProfile + chronic_conditions を反映した
    実測値を得て、LOINC 別 reference_range と interpretation("N" or "H")を
    ``_interp_for`` で付与する。
    """
    result_dt = datetime.combine(checkup_date, datetime.min.time().replace(hour=10))
    values = _derive_checkup_values(patient, rng)
    results: list[OrderResult] = []
    for item in _CHECKUP_ITEMS:
        v = values[item["key"]]
        # BMI/HbA1c/LDL は小数第 1 位、BP は整数丸め
        if item["key"] in ("sbp", "dbp"):
            v = float(round(v))
        else:
            v = float(round(v, 1))
        interp, ref = _interp_for(item["loinc"], v)
        results.append(OrderResult(
            result_datetime=result_dt,
            performed_by="",
            lab_name=item["loinc"],
            value=v,
            unit=item["unit"],
            reference_range=ref,
            flag=("H" if interp == "H" else None),
            interpretation=interp,
            specimen_note="",
        ))
    return results


def _build_checkup_document_stub(
    patient_id: str, encounter_id: str, checkup_date: date, doc_seq: int, lang: str,
    checkup_type: str = "occupational",
) -> ClinicalDocument:
    """健診結果報告書 ClinicalDocument stub を作る(narrative=None)。

    Stage 2 の TemplateNarrativePass が checkup_lab_results /
    checkup_questionnaire section を populate する。
    ``checkup_type`` は FHIR emit 時に section code(01011/01021/01031 等)
    を dispatch するために Composition builder が読み取る。
    """
    authored_dt = datetime.combine(checkup_date, datetime.min.time().replace(hour=11))
    return ClinicalDocument(
        document_id=f"doc-{encounter_id}-{doc_seq:02d}",
        task_type="health_checkup_report",
        loinc_code="53576-5",
        patient_id=patient_id,
        encounter_id=encounter_id,
        author_practitioner_id="",
        authored_datetime=authored_dt.isoformat(),
        period_start=authored_dt.isoformat(),
        period_end=authored_dt.isoformat(),
        language=lang,
        format_type="composition",
        checkup_type=checkup_type,
        narrative=None,
    )


def enrich_health_checkup(ctx: Any) -> None:
    """POST_RECORDS enricher entry — 事業者健診 opt-in の CIF 拡張。

    ctx.records の各 CIFPatientRecord に対して:
      1. 40 歳以上かつ hash-based 30% サブセットに入る場合のみ処理
      2. CHECKUP encounter を record.encounters に append
      3. 法定健診 5 項目を record.lab_results に append
      4. HEALTH_CHECKUP_REPORT stub を record.documents に append

    enabled gate は register_builtin_enrichers 側で country=JP かつ
    config.module_enabled("health_checkup") == True を確認する。
    ここでは gate 突破後の処理のみ。

    RNG(sub-PR-B 高度化):per-patient sub-seed を
    ``derive_sub_seed(master, ENRICHER_SEED_OFFSETS["health_checkup"], patient_id)``
    で導出。健診 5 項目の測定日変動を patient-scoped に決定的にサンプルする。
    """
    master_seed = getattr(ctx, "master_seed", 42) or 42
    hc_offset = ENRICHER_SEED_OFFSETS["health_checkup"]

    snapshot_date = _o(ctx.config, "snapshot_date", None)
    if isinstance(snapshot_date, datetime):
        snapshot_date = snapshot_date.date()
    # _pick_checkup_date が str も許容するため、そのままでも動く。

    lang = "ja" if is_jp(_o(ctx.config, "country", "")) else "en"

    # 患者 id ごとに 1 度だけ健診レコードを追加する(年 1 回想定)。
    # dataset.patients は encounter 種別ごとに record を分けているため、
    # 健診 encounter も新規 CIFPatientRecord として append する。narrative
    # pass は record.encounters[0] で spec applicability を判定するため、
    # 既存 inpatient record に健診 encounter を後ろから足すと
    # HEALTH_CHECKUP_REPORT spec が適用対象外になり narrative 生成が skip
    # される(session 47 sub-PR-B verify で発覚)。健診 record を独立させる
    # ことで narrative pass の walk が CHECKUP encounter を正しく認識する。
    from clinosim.types.output import CIFPatientRecord

    seen_patient_ids: set[str] = set()
    known_patients: dict[str, Any] = {}
    for record in ctx.records:
        patient = _o(record, "patient", None)
        if patient is None:
            continue
        patient_id = _o(patient, "patient_id", "")
        if patient_id and patient_id not in known_patients:
            known_patients[patient_id] = patient

    new_records: list[Any] = []
    for patient_id, patient in known_patients.items():
        if patient_id in seen_patient_ids:
            continue
        age = _o(patient, "age", 0) or 0
        if age < HEALTH_CHECKUP_MIN_AGE:
            continue
        if not _patient_selected(patient_id):
            continue
        seen_patient_ids.add(patient_id)

        checkup_date = _pick_checkup_date(snapshot_date)
        checkup_type = _pick_checkup_type(age)
        encounter = _build_checkup_encounter(
            patient_id, checkup_date, 1, checkup_type=checkup_type,
        )
        # per-patient sub-rng(AD-16):同 seed+同 patient_id → 同 lab 値。
        patient_rng = np.random.default_rng(
            derive_sub_seed(master_seed, hc_offset, patient_id)
        )
        checkup_labs = _build_checkup_lab_results(
            patient_id, patient, checkup_date, patient_rng,
        )
        checkup_doc = _build_checkup_document_stub(
            patient_id, encounter.encounter_id, checkup_date, 1, lang,
            checkup_type=checkup_type,
        )

        # 健診 record は新規 CIFPatientRecord として組み立てる:
        # narrative pass の spec applicability は record.encounters[0] を
        # 見るため、健診専用 record の唯一の encounter が CHECKUP になる。
        checkup_record = CIFPatientRecord(
            patient=patient,
            encounters=[encounter],
            lab_results=list(checkup_labs),
            documents=[checkup_doc],
        )
        new_records.append(checkup_record)

    # まとめて append(iteration 中の list 変更を避ける)
    ctx.records.extend(new_records)
