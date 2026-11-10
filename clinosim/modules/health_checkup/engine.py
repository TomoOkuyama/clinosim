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

FHIR emit は fhir_r4/documents/composition.py の JP-eCheckup builder が担う。
Composition.section の text.div は narrative pass が入れる。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import cache
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from clinosim import determinism
from clinosim.codes.valuesets import concept_group
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp
from clinosim.modules.document.narrative.registry import document_loinc
from clinosim.modules.health_checkup._checkup_thresholds import (
    BMI_MEASUREMENT_NOISE_SD,
    CHECKUP_TYPE_REGIONAL_UNION_AGE_MIN,
    CHECKUP_TYPE_SPECIFIC_AGE_MIN,
    DBP_MEASUREMENT_NOISE_SD,
    DBP_PHYSIOLOGIC_MAX,
    DBP_PHYSIOLOGIC_MIN,
    DBP_VITALS_FALLBACK,
    HBA1C_DM_MEASUREMENT_NOISE_SD,
    HBA1C_DM_PHYSIOLOGIC_MAX,
    HBA1C_DM_PHYSIOLOGIC_MIN,
    HBA1C_GC_FALLBACK,
    HBA1C_NONDM_AGE_SCALE,
    HBA1C_NONDM_MEASUREMENT_NOISE_SD,
    HBA1C_NONDM_PHYSIOLOGIC_MAX,
    HBA1C_NONDM_PHYSIOLOGIC_MIN,
    LDL_MEASUREMENT_NOISE_SD,
    LDL_PHYSIOLOGIC_MAX,
    LDL_PHYSIOLOGIC_MIN,
    SBP_MEASUREMENT_NOISE_SD,
    SBP_PHYSIOLOGIC_MAX,
    SBP_PHYSIOLOGIC_MIN,
    SBP_VITALS_FALLBACK,
)
from clinosim.modules.observation.engine import get_lab_unit
from clinosim.modules.physiology.engine import patient_lipid_panel
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.clinical import ClinicalDocument
from clinosim.types.encounter import (
    Encounter,
    EncounterStatus,
    EncounterType,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
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
    if age >= CHECKUP_TYPE_REGIONAL_UNION_AGE_MIN:
        return "regional_union"
    if age >= CHECKUP_TYPE_SPECIFIC_AGE_MIN:
        return "specific"
    return "occupational"


# 種別ごとの主訴表示は narrative_phrases.yaml の health_checkup.<種別>
_CHECKUP_TYPES = ("occupational", "specific", "regional_union")


# 法定健診 5 項目は lab_panels.yaml の Checkup パネルの component (正規の
# 検査名) が唯一の定義。単位は lab_constants.yaml、コードは国別 code mapping、
# 判定基準は reference_range_lab.yaml の checkup_ranges から引く (Issue #2300)。
def checkup_lab_names() -> list[str]:
    """法定健診項目の正規検査名 (BMI / SBP / DBP / HbA1c / LDL)。"""
    from clinosim.modules.order.panel_grouping import load_panel_definitions

    return list(load_panel_definitions()["Checkup"]["components"])


def _derive_checkup_values(patient: Any, rng: np.random.Generator, *, charted_bmi: float) -> dict[str, float]:
    """患者プロファイルと chronic_conditions から健診 5 項目の実測値を導出。

    - BMI:健診 encounter で計測した身長・体重から算出した ``charted_bmi``
      (encounter の身長・体重 Observation と同じ値から、Issue #3167)。
    - SBP/DBP:``patient.baseline_vitals`` を base とし、日間変動 sd 5.0/3.5 mmHg。
      HT(I10)は FP-I10で baseline_vitals に既に反映済み。
    - HbA1c:糖尿病(E10/E11)保有時は ``glycemic_control`` から
      ``hba1c_from_glycemic_control`` を再利用(条件側未設定なら中央値 0.5)。
      非糖尿病は 5.1 + 年齢係数 0.003(HBA1C_NONDM_BASE パターンを踏襲)。
    - LDL:入院・外来の検査値と同じ脂質状態から ``patient_lipid_panel``
      (physiology) で真値を得る。スタチンの低下率も同じ (Issue #2928, #2941)。

    RNG は per-patient sub-seed 由来(``derive_sub_seed``)、AD-16 準拠。
    測定ノイズは grade 境界を跨がない小さめの値に留める。
    """
    from clinosim.modules.physiology.engine import (
        HBA1C_NONDM_BASE,
        hba1c_from_glycemic_control,
    )

    age = int(_o(patient, "age", 60) or 60)
    chronic = _o(patient, "chronic_conditions", []) or []

    # BMI is the one computed from the height and weight charted on the
    # checkup encounter (Issue #3167). The former BMI noise draw stays in the
    # stream so the later results keep their values (determinism spec §2).
    rng.normal(0.0, BMI_MEASUREMENT_NOISE_SD)
    bmi = float(charted_bmi)

    # SBP/DBP:baseline_vitals が HT stage(FP-I10)を反映済み
    bv = _o(patient, "baseline_vitals", None)
    sbp_base = float(_o(bv, "systolic_bp", SBP_VITALS_FALLBACK) if bv is not None else SBP_VITALS_FALLBACK)
    dbp_base = float(_o(bv, "diastolic_bp", DBP_VITALS_FALLBACK) if bv is not None else DBP_VITALS_FALLBACK)
    sbp = float(np.clip(sbp_base + rng.normal(0.0, SBP_MEASUREMENT_NOISE_SD), SBP_PHYSIOLOGIC_MIN, SBP_PHYSIOLOGIC_MAX))
    dbp = float(np.clip(dbp_base + rng.normal(0.0, DBP_MEASUREMENT_NOISE_SD), DBP_PHYSIOLOGIC_MIN, DBP_PHYSIOLOGIC_MAX))

    # HbA1c:DM 有無で分岐
    dm_condition = None
    for c in chronic:
        code = _o(c, "code", "") or ""
        # 糖尿病の判定は共通の value set "diabetes" を使う (Issue #2281)
        if concept_group("diabetes").contains(code):
            dm_condition = c
            break
    if dm_condition is not None:
        # Phase 1 longitudinal subsystem (Issue #1695): read HbA1c
        # latent from patient.longitudinal_history via state_at;
        # fall back to the GC-based derivation only if no latent is
        # present (test fixtures that bypass generate_population).
        from clinosim.modules.physiology.engine import hba1c_latent_at

        _latent = hba1c_latent_at(patient, _o(patient, "checkup_date", None))
        if _latent is not None:
            hba1c_true = float(_latent)
        else:
            gc = _o(dm_condition, "glycemic_control", None)
            if gc is None:
                gc = HBA1C_GC_FALLBACK  # 未設定時は中央値
            hba1c_true = hba1c_from_glycemic_control(float(gc))
        hba1c = float(
            np.clip(
                hba1c_true + rng.normal(0.0, HBA1C_DM_MEASUREMENT_NOISE_SD),
                HBA1C_DM_PHYSIOLOGIC_MIN,
                HBA1C_DM_PHYSIOLOGIC_MAX,
            )
        )
    else:
        hba1c_base = HBA1C_NONDM_BASE + max(0, age - 40) * HBA1C_NONDM_AGE_SCALE
        hba1c = float(
            np.clip(
                hba1c_base + rng.normal(0.0, HBA1C_NONDM_MEASUREMENT_NOISE_SD),
                HBA1C_NONDM_PHYSIOLOGIC_MIN,
                HBA1C_NONDM_PHYSIOLOGIC_MAX,
            )
        )

    # LDL:入院・外来の検査値と同じ患者の脂質状態 (性別・糖尿病・脂質異常症・
    # スタチンの低下率) から真値を引き、健診の測定ノイズだけを乗せる。
    # 健診だけの年齢/性別モデルは同じ患者の外来 LDL と系統的にずれていた
    # (Issue #2941)。
    ldl_base = patient_lipid_panel(patient)["LDL"]
    ldl = float(np.clip(ldl_base + rng.normal(0.0, LDL_MEASUREMENT_NOISE_SD), LDL_PHYSIOLOGIC_MIN, LDL_PHYSIOLOGIC_MAX))

    return {"BMI": bmi, "SBP": sbp, "DBP": dbp, "HbA1c": hba1c, "LDL": ldl}


def _patient_selected(patient_id: str) -> bool:
    """患者 id の SHA-256 hash で 30% サブセットに入るかを決定的判定。"""
    return determinism.sha_bernoulli(patient_id, HEALTH_CHECKUP_SUBSET_RATE)


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


def _alive_on_checkup_date(ctx: Any, patient_id: str, patient: Any, checkup_date: date) -> bool:
    """健診日に本人が在籍・生存しているか (Issue #2940)。

    死亡の正本は ``PersonRecord`` (``record_death``) なので、population
    registry があれば ``PersonRecord.in_population_at`` をそのまま使う
    (死亡日当日以降は不在扱い)。registry の無い呼び出し (unit test 等)
    では ``sync_profile_death_dates`` が profile に写した死亡日で判定する。
    """
    persons = _o(_o(ctx, "population", None), "persons", None) or {}
    person = persons.get(patient_id)
    if person is not None:
        return bool(person.in_population_at(checkup_date))
    dod = _o(patient, "date_of_death", None)
    if isinstance(dod, datetime):
        dod = dod.date()
    return dod is None or checkup_date < dod


def _build_checkup_encounter(
    patient_id: str,
    checkup_date: date,
    encounter_seq: int,
    checkup_type: str = "occupational",
) -> Encounter:
    """CHECKUP encounter を組み立てる(1 日完結、退院同日)。

    chief_complaint は健診種別を反映(occupational=事業者健診 等)、
    将来 FHIR emit 側でこの表示を Encounter.reasonCode などに含める余地。
    """
    enc_id = f"CHK-{patient_id}-{encounter_seq:03d}"
    admission_dt = datetime.combine(checkup_date, datetime.min.time().replace(hour=9))
    discharge_dt = admission_dt + timedelta(hours=2)
    cc = t(f"health_checkup.{checkup_type if checkup_type in _CHECKUP_TYPES else 'periodic'}", "ja")
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


def _interp_for(lab_name: str, value: float) -> tuple[str, str]:
    """検査名別に (interpretation, reference_range) を返す。

    interpretation は HL7 v2 Table 0078 の "N" / "H"。保健指導判定値
    (reference_range_lab.yaml の checkup_ranges) 以上を "H" とする。
    """
    from clinosim.locale.loader import checkup_criterion

    rng_def = checkup_criterion(lab_name, "JP")
    if not rng_def:
        return ("N", "")
    return ("H" if value >= float(rng_def["high"]) else "N", str(rng_def.get("text") or ""))


def _build_checkup_lab_results(
    patient_id: str,
    patient: Any,
    encounter: Any,
    rng: np.random.Generator,
    country: str,
) -> list[OrderResult]:
    """法定健診 5 項目の OrderResult を組み立てる(sub-PR-B 高度化)。

    ``_derive_checkup_values`` で PatientProfile + chronic_conditions を反映した
    実測値を得て、LOINC 別 reference_range と interpretation("N" or "H")を
    ``_interp_for`` で付与する。BMI は健診 encounter で計測した身長・体重
    (``encounter_anthropometrics``) から算出する (Issue #3167)。
    """
    from clinosim.modules.population.encounter_anthropometry import encounter_anthropometrics

    admission = encounter.admission_datetime
    result_dt = datetime.combine(admission.date(), datetime.min.time().replace(hour=10))
    charted = encounter_anthropometrics(patient, encounter.encounter_id, admission, country)
    values = _derive_checkup_values(patient, rng, charted_bmi=charted["bmi"])
    results: list[OrderResult] = []
    for lab_name in checkup_lab_names():
        v = values[lab_name]
        # BMI/HbA1c/LDL は小数第 1 位、BP は整数丸め
        if lab_name in ("SBP", "DBP"):
            v = float(round(v))
        else:
            v = float(round(v, 1))
        interp, ref = _interp_for(lab_name, v)
        results.append(
            OrderResult(
                result_datetime=result_dt,
                performed_by="",
                lab_name=lab_name,
                value=v,
                unit=get_lab_unit(lab_name),
                reference_range=ref,
                flag=("H" if interp == "H" else None),
                interpretation=interp,
                specimen_note="",
            )
        )
    return results


def _build_checkup_document_stub(
    patient_id: str,
    encounter_id: str,
    checkup_date: date,
    doc_seq: int,
    lang: str,
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
        loinc_code=document_loinc("health_checkup_report"),
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


class CheckupStaffingFile(BaseModel):
    """Shape of ``reference_data/checkup_staffing.yaml`` (Issue #3153)."""

    model_config = ConfigDict(extra="forbid")
    attending_departments: list[str] = Field(min_length=1)


@cache
def _attending_departments() -> tuple[str, ...]:
    """Departments whose physicians perform checkups
    (``reference_data/checkup_staffing.yaml``, Issue #3153)."""
    from pathlib import Path

    from clinosim.datafiles import load_validated_yaml

    raw = load_validated_yaml(
        Path(__file__).resolve().parent / "reference_data" / "checkup_staffing.yaml", CheckupStaffingFile
    )
    return tuple(str(d) for d in raw["attending_departments"])


def checkup_attending(roster: Any, encounter_id: str) -> str:
    """The physician who performs checkup ``encounter_id`` (Issue #3153): a
    physician of the first ``attending_departments`` entry that has any,
    picked stably by the encounter id (no RNG); "" without a roster."""
    members = list(getattr(roster, "members", None) or [])
    for dept in _attending_departments():
        ids = sorted(m.staff_id for m in members if m.role == "physician" and m.department == dept)
        if ids:
            return ids[determinism.sha_index(f"checkup-attending::{encounter_id}", len(ids))]
    return ""


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
    # される(sub-PR-B verify で発覚)。健診 record を独立させる
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
        # Issue #2940: 死亡日当日以降の健診は作らない。
        if not _alive_on_checkup_date(ctx, patient_id, patient, checkup_date):
            continue
        checkup_type = _pick_checkup_type(age)
        encounter = _build_checkup_encounter(
            patient_id,
            checkup_date,
            1,
            checkup_type=checkup_type,
        )
        # per-patient sub-rng(AD-16):同 seed+同 patient_id → 同 lab 値。
        patient_rng = determinism.default_rng(derive_sub_seed(master_seed, hc_offset, patient_id))
        checkup_labs = _build_checkup_lab_results(
            patient_id,
            patient,
            encounter,
            patient_rng,
            _o(ctx.config, "country", ""),
        )
        checkup_doc = _build_checkup_document_stub(
            patient_id,
            encounter.encounter_id,
            checkup_date,
            1,
            lang,
            checkup_type=checkup_type,
        )
        # Issue #3153: a real attending physician, who authors the report.
        attending = checkup_attending(getattr(ctx, "roster", None), encounter.encounter_id)
        encounter.attending_physician_id = attending
        checkup_doc.author_practitioner_id = attending
        # CY8-01 fix:Order を lab_results 数だけ作り
        # `result` に checkup_labs を対応付ける。これで既存 `_bb_labs` /
        # `_bb_service_requests` / `_bb_diagnostic_reports` が checkup lab を
        # 拾い、FHIR Observation + ServiceRequest + DiagnosticReport が
        # 出力される(以前は record.lab_results 直接置きで silent-drop)。
        # panel_key="Checkup" を共有し、5 orders → 1 SR + 1 DR + 5 Observation。
        ordered_dt = datetime.combine(
            checkup_date,
            datetime.min.time().replace(hour=9, minute=30),
        )
        checkup_orders: list[Order] = []
        for i, res in enumerate(checkup_labs):
            checkup_orders.append(
                Order(
                    order_id=f"ord-{encounter.encounter_id}-CHK-{i:02d}",
                    encounter_id=encounter.encounter_id,
                    patient_id=patient_id,
                    order_type=OrderType.LAB,
                    order_code=res.lab_name,  # 正規の検査名 (コードは出力時に code mapping)
                    display_name=res.lab_name,
                    urgency="routine",
                    clinical_intent="health_checkup",
                    # Issue #871: JA display for JP SR reasonCode.text.
                    clinical_intent_ja=t("health_checkup.intent", "ja"),
                    ordered_datetime=ordered_dt,
                    ordered_by="",  # 健診は事業所/自治体依頼、実施医師未指定
                    status=OrderStatus.REVIEWED,  # 健診結果まで完了、reviewed 相当
                    result=res,
                    panel_key="Checkup",  # 5 orders → 1 ServiceRequest + 1 DR
                )
            )

        # 健診 record は新規 CIFPatientRecord として組み立てる:
        # narrative pass の spec applicability は record.encounters[0] を
        # 見るため、健診専用 record の唯一の encounter が CHECKUP になる。
        checkup_record = CIFPatientRecord(
            patient=patient,
            encounters=[encounter],
            orders=list(checkup_orders),  # CY8-01 fix: FHIR emit の source
            lab_results=list(checkup_labs),  # 後方互換 + narrative pass 用
            documents=[checkup_doc],
        )
        new_records.append(checkup_record)

    # まとめて append(iteration 中の list 変更を避ける)
    ctx.records.extend(new_records)
