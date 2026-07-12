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

from clinosim.modules._shared import is_jp
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

# 法定健診項目の LOINC コードと標準基準内サンプル値(MVP:全員基準内、
# 実 PatientProfile 参照個別化は sub-PR-B スコープ)。
_CHECKUP_ITEMS: list[dict[str, Any]] = [
    {"loinc": "39156-5", "name": "BMI",              "value": 22.5, "unit": "kg/m2"},
    {"loinc": "8480-6",  "name": "systolic BP",      "value": 118,  "unit": "mmHg"},
    {"loinc": "8462-4",  "name": "diastolic BP",     "value": 76,   "unit": "mmHg"},
    {"loinc": "4548-4",  "name": "HbA1c",            "value": 5.4,  "unit": "%"},
    {"loinc": "18262-6", "name": "LDL cholesterol",  "value": 118,  "unit": "mg/dL"},
]


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
) -> Encounter:
    """CHECKUP encounter を組み立てる(1 日完結、退院同日)。"""
    enc_id = f"CHK-{patient_id}-{encounter_seq:03d}"
    admission_dt = datetime.combine(checkup_date, datetime.min.time().replace(hour=9))
    discharge_dt = admission_dt + timedelta(hours=2)
    return Encounter(
        encounter_id=enc_id,
        patient_id=patient_id,
        encounter_type=EncounterType.CHECKUP,
        status=EncounterStatus.COMPLETED,
        department_id="health_checkup",
        admission_datetime=admission_dt,
        discharge_datetime=discharge_dt,
        chief_complaint="定期健康診断",
        # 健診は routine、緊急でも救急経由でもない
        priority="R",
        admit_source="outp",
        discharge_disposition="home",
    )


def _build_checkup_lab_results(
    patient_id: str, checkup_date: date,
) -> list[OrderResult]:
    """法定健診 5 項目の OrderResult を組み立てる。"""
    result_dt = datetime.combine(checkup_date, datetime.min.time().replace(hour=10))
    results: list[OrderResult] = []
    for item in _CHECKUP_ITEMS:
        results.append(OrderResult(
            result_datetime=result_dt,
            performed_by="",
            lab_name=item["loinc"],
            value=item["value"],
            unit=item["unit"],
            reference_range="",
            flag=None,  # MVP:全員基準内、flag なし
            interpretation="N",  # normal
            specimen_note="",
        ))
    return results


def _build_checkup_document_stub(
    patient_id: str, encounter_id: str, checkup_date: date, doc_seq: int, lang: str,
) -> ClinicalDocument:
    """健診結果報告書 ClinicalDocument stub を作る(narrative=None)。

    Stage 2 の TemplateNarrativePass が checkup_lab_results /
    checkup_questionnaire section を populate する。
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
    """
    from clinosim.modules._shared import get_attr_or_key as _o

    snapshot_date = _o(ctx.config, "snapshot_date", None)
    if isinstance(snapshot_date, datetime):
        snapshot_date = snapshot_date.date()
    # _pick_checkup_date が str も許容するため、そのままでも動く。

    lang = "ja" if is_jp(_o(ctx.config, "country", "")) else "en"

    # 患者 id ごとに 1 度だけ健診 encounter を追加する(年 1 回想定)。
    # dataset.patients には同一患者の記録が複数(inpatient + outpatient + ED)
    # 含まれる場合があるため、重複追加を防ぐ。最初に遭遇したレコードに
    # 追加する pattern。
    seen_patient_ids: set[str] = set()
    for record in ctx.records:
        patient = _o(record, "patient", None)
        if patient is None:
            continue
        patient_id = _o(patient, "patient_id", "")
        if not patient_id or patient_id in seen_patient_ids:
            continue
        age = _o(patient, "age", 0) or 0
        if age < HEALTH_CHECKUP_MIN_AGE:
            continue
        if not _patient_selected(patient_id):
            continue
        seen_patient_ids.add(patient_id)

        checkup_date = _pick_checkup_date(snapshot_date)

        existing_encounters = _o(record, "encounters", []) or []
        encounter_seq = len(existing_encounters) + 1
        encounter = _build_checkup_encounter(
            patient_id, checkup_date, encounter_seq,
        )
        # AD-55 の spirit:opt-in module は core field に書くのを最小に留めるが、
        # 健診 encounter は encounter そのものなので encounters list に追加する。
        record.encounters.append(encounter)

        record.lab_results.extend(
            _build_checkup_lab_results(patient_id, checkup_date)
        )

        doc_seq = len(_o(record, "documents", []) or []) + 1
        record.documents.append(_build_checkup_document_stub(
            patient_id, encounter.encounter_id, checkup_date, doc_seq, lang,
        ))
