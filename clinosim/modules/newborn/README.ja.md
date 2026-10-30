# `clinosim.modules.newborn` — 新生児の出生入院中の臨床 workup

## 概要

実際の新生児カルテが出生入院中に必ず持つ臨床イベントのうち、他の
module が担当していないものを emit する。
`simulator/perinatal.py` (Encounter + Patient の枠を担当) と
`clinosim.modules.pediatric` (退院後の well-child 受診を担当) の間の
ギャップを埋める。

Issue #1252 で起票。module 境界の根拠と、`perinatal.py` や
`pediatric/` に組み込むより専用 module の方が優れる理由は
[#1252 の設計コメント](https://github.com/TomoOkuyama/clinosim/issues/1252)
にある。

## Scope

- **In scope**: 新生児側 CIF レコード
  (`condition_event.condition_type == "newborn_birth"`) で発火する
  出生入院中の臨床イベント。#1252 の全 slice が実装済み:
  - ビタミン K 予防投与 (`MedicationAdministration` — JP は入院期間内
    であれば day 0 / 7 に経口 K2 シロップ、US は 1 mg IM — N2)。
  - 新生児の `baseline_vitals` からの勤務帯ごとのバイタルサイン
    (`VitalSignRecord` — N3)。
  - 1 分 / 5 分 Apgar スコア (`Observation`、LOINC 9271-8 /
    9274-2 — N4)。
  - AABR 聴覚スクリーニング (`Procedure`、SNOMED 232717001 — N5)。
  - タンデムマス法による先天代謝異常マススクリーニング
    (`Procedure`、SNOMED 405058008、加えて `ServiceRequest` +
    `Specimen` + `Observation` + `DiagnosticReport` の workflow —
    N6 / N6b)。
  - 経皮ビリルビン、CCHD パルスオキシメトリスクリーニング
    (`Observation`)、US のエリスロマイシン眼軟膏予防投与
    (`MedicationAdministration`。JP config は薬剤を宣言しないため
    何も emit されない) — N7。
- **新生児 1 人 1 回の重複排除** (Issue #1736): 同じ母親から生まれた
  兄弟は `patient_id = "<mother_id>-BABY"` を共有するため、聴覚
  スクリーニングと代謝スクリーニングは module レベルの
  `(patient_id, SNOMED)` tracker (`has_perinatal_baseline_emitted` /
  `mark_perinatal_baseline_emitted`) で gate される。tracker は
  `clinosim.simulator.engine.run_beta` の冒頭と
  `tests/conftest.py` の autouse fixture でリセットされる。
- **Out of scope**: NICU 病態 (Z38.0 の健常新生児のみ)、多胎
  (Z37.2 / 3 / 4 / 5 — 単胎のみ)、自宅 / 助産所での分娩、退院後の
  投与 (例: JP の 1 か月時ビタミン K 投与)。

## Public API

```python
from clinosim.modules.newborn import (
    load_newborn_config,               # locale schedule loader (cached)
    is_newborn_birth_record,           # firing-gate predicate
    build_vitamin_k_administrations,   # (record, country) -> list[MedicationAdministration]
    build_newborn_shift_vitals,        # (record) -> list[VitalSignRecord]
    build_apgar_scores,                # (record) -> list[dict]
    build_hearing_screen_procedure,    # (record) -> ProcedureRecord | None
    build_metabolic_screen_procedure,  # (record, country) -> ProcedureRecord | None
    build_bilirubin_observations,      # (record) -> list[dict]
    build_cchd_pulse_ox,               # (record) -> list[dict]
    build_ophthalmic_prophylaxis,      # (record, country) -> list[MedicationAdministration]
    PERINATAL_BASELINE_SNOMEDS,        # {"232717001", "405058008"}
    has_perinatal_baseline_emitted,
    mark_perinatal_baseline_emitted,
    reset_perinatal_baseline_tracker,
    enrich_newborn,                    # POST_ENCOUNTER enricher entrypoint
)
```

`engine.build_metabolic_screen_workflow_data` (再 export されない) が
ServiceRequest / Specimen / DiagnosticReport の payload を構築する。

## 出力先

`enrich_newborn` は新生児レコードに以下を追記する:

- `medication_administrations` — ビタミン K + 眼軟膏予防投与。
- `vital_signs` — 勤務帯ごとのバイタル。
- `procedures` — 聴覚 + 代謝スクリーニングの `ProcedureRecord`。
- `extensions["newborn"]` — `apgar`、`bilirubin`、`cchd_pulse_ox`、
  `metabolic_screen` の payload。[`fhir_emit.py`](fhir_emit.py) の
  `_bb_newborn_*` bundle-builder がこれを描画し、
  `clinosim/modules/output/fhir_r4/builder.py` がそれを import する。

## Enricher 登録

`clinosim/simulator/enrichers.py` に
`POST_ENCOUNTER order=92` として登録され、JP / US locale で always-on:

- `imaging` (90) の後に実行し、module が完全に埋まった encounter を
  参照できるようにする。
- `triage` (93) と `document` (95) の前に実行し、ビタミン K 投与に
  言及する narrative が MAR エントリを既に参照できるようにする。

## 設定

`reference_data/newborn_screening.yaml` — locale 別のプロトコル
パラメータ。repo の規約 (定数はコードではなく yaml に置く) に従い、
臨床的に意味のある定数はすべてここにある。engine は用量 / 日数 /
薬剤名をハードコードしない。

トップレベルキー: `bilirubin`、`cchd_pulse_ox`、`ophthalmic_prophylaxis`、
`metabolic_screen`、`hearing_screen`、`apgar`、`shift_vitals`、
`vitamin_k`。例えばビタミン K ブロックは:

```yaml
vitamin_k:
  jp: {drug_name, dose, route, schedule_days, within_hours_of_birth, yj_code}
  us: {drug_name, dose, route, schedule_days, within_hours_of_birth, rxnorm_code}
```

## 決定論

master stream の RNG は消費しない。ビタミン K、眼軟膏予防投与、
勤務帯バイタルは、出生 encounter の入院日時、新生児の
`baseline_vitals`、yaml schedule の決定論的関数である。Apgar
スコア、聴覚 / 代謝スクリーニングの結果、ビリルビン値、CCHD の SpO2
値は、固定ラベルと新生児の patient id の SHA-256 から seed した
ローカルの `np.random.default_rng` を用いる (例:
`newborn-apgar|<pid>|…`、`newborn-hearing-screen|<pid>`)。そのため
患者単位で再現可能で、caller の RNG から独立している。
`ENRICHER_SEED_OFFSETS` のエントリは使わない。ビタミン K の
coverage-miss / 拒否の経路はまだ無い。

## テスト

`tests/unit/modules/newborn/` — `test_vitamin_k.py`、
`test_shift_vitals.py`、`test_apgar.py`、`test_hearing_screen.py`、
`test_metabolic_screen.py`、`test_bilirubin_cchd_ophthalmic.py`、
`test_perinatal_baseline_dedup.py`。FHIR の shape は
`tests/unit/output/test_newborn_metabolic_screen_fhir_shape.py`。

## 参考文献

- JP MHLW 新生児 ビタミン K 欠乏性出血症予防 (2011 改訂、3 回経口
  投与 schedule)。
- AAP Guidelines for Perinatal Care 8th ed. (US のビタミン K 1 mg IM、
  出生後 6 時間以内)。
- FHIR R4 `MedicationAdministration` — MAR エントリ用に既存の
  `medications/` builder が使う emit shape。

英語版: [`README.md`](README.md)。
