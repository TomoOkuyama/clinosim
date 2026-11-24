# `clinosim.modules.procedure` — 手術 + bedside 処置 + rehab 生成

## 概要

encounter 単位の procedure emission を 3 家族に対して所有:

1. **手術** (`simulate_surgery`) — disease protocol が
   `requires_surgery` のとき `simulator/inpatient.py` が呼び、protocol
   の `procedure` block を読む: 手術までの時間、期間、EBL、麻酔種別、
   ASA class、SNOMED に map した術中合併症、SNOMED outcome code を
   持つ `(ProcedureRecord, state_impacts)` を返す。`state_impacts` は
   呼び出し側が適用する physiology delta。
2. **Bedside 処置** (`generate_bedside_procedures`) — `_PROCEDURE_RULES`
   (`reference_data/procedure_rules.yaml` の `bedside_rules`) で疾患 / condition に一致した処置 (例: 尿道カテーテル、中心静脈 /
   動脈ライン、腰椎穿刺、胸腔穿刺、腹腔穿刺、NG チューブ、胸腔
   ドレーン、除細動、輸血、緊急透析、心電図、末梢ライン、シーネ /
   非観血的整復、創処置、酸素療法) を重症度 scale の base 確率 +
   入院後時刻 offset サンプリングで発火。別表
   `_ISSUE939_PROCEDURE_RULES` (yaml の `isolated_rules`。PCI、ペースメーカー、開頭血腫除去、
   イレウス管、腸切除; Issue #939) は専用の (encounter, procedure)
   別サブ RNG で draw。
3. **術後 rehab** (`generate_rehab_sessions`) — post-op day 1 から
   退院日までの日次 PT スケジュール。early / mid / late phase の
   活動、疼痛モデル、skip-day / 拒否確率を持つ。各セッションは職種の
   roster 担当療法士 (`therapist_id`、Issue #3319) を記録する。担当者は
   `staff.assign_rehab_therapist` が encounter と職種ごとに決定論的に選ぶ
   (RNG 消費なし、同じ encounter の CareTeam に載る療法士と同一人物)。
4. **気管挿管** (`build_intubation_procedure`、Issue #2091) — state が
   気道閾値を越えたとき `simulator/daily_loop.py` が作る決定論的な
   挿管 `ProcedureRecord`。

engine が使っていた scalar は全て inline から companion
`_*_thresholds.py` 3 file (Issue #637 sweep) に臨床引用付きで lift 済。

## Scope

- **In scope**: `simulate_surgery` (`ProcedureRecord` + state 影響を
  返す); `generate_bedside_procedures` (重症度 scale 確率 +
  time-offset サンプリング); `generate_rehab_sessions` (day 1 から
  退院までの `RehabSession` list); `build_intubation_procedure`;
  `_derive_outcome`, `_map_complications` (test で必要な internal
  helper); `ProcedureMeta` (procedure ごとの SNOMED category +
  body site)。
- **Out of scope**: procedure コード YAML
  ([`clinosim.codes`](../../codes/))、procedure encounter timeline
  ([`clinosim.modules.encounter`](../encounter/README.ja.md))、FHIR
  `Procedure` emission
  ([`clinosim.modules.output.fhir_r4.procedures`](../output/fhir_r4/procedures/README.ja.md))、
  imaging 発注構築 — これは
  [`clinosim.modules.imaging`](../imaging/README.ja.md)。

### 縦断サービスライン Procedure (v0.5 → v0.6.0)

上記 3 種 (手術 / bedside / rehab) と並列に、以下 2 種の Procedure が
同じ `ProcedureRecord` shape で emit される:

- **分娩 Procedure** — 母親側の周産期分娩 Encounter (詳細:
  [`clinosim.modules.encounter`](../encounter/README.ja.md)) に付与。
  Code: US CPT `59400` (JP は正常分娩が保険外のため K コードなし、Issue #2340)。
  CPT `59400` (routine obstetric care incl. vaginal delivery)。
  emit 元は
  [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py)、
  shape は
  [`clinosim/locale/shared/perinatal.yaml`](../../locale/shared/perinatal.yaml)
  の `procedure` block。`simulate_surgery` を経由しない。
- **放射線治療 Procedure** — `locale/shared/chronic_followup.yaml` で
  `radiation_therapy_eligible: true` の follow-up 受診の約 40 % に
  JP code `M001` (体外照射) / US CPT `77412` (放射線治療・複雑) で付与
  (Issue #957、コードは `chronic_followup.yaml` の `_radiation_therapy`、
  #2200)。
  [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py)
  が encounter hash の RNG で inline emit。`simulate_surgery` を
  経由しない。

両者とも canonical な `ProcedureRecord` field を維持するため、FHIR
adapter ([`output/fhir_r4/procedures/`](../output/fhir_r4/procedures/README.ja.md))
は新しい resource-type builder を追加せずに emit 可能。

## Public API

```python
from clinosim.modules.procedure import (
    ProcedureRecord,             # dataclass (types.procedure から再 export)
    RehabSession,                # dataclass (types.procedure から再 export)
    simulate_surgery,            # (patient, disease_id, encounter_id, admission_time, protocol, rng,
                                 #  country, surgeon_id="", anesthesiologist_id="", operating_rooms=2)
                                 #  -> (ProcedureRecord, dict[str, float])
    generate_bedside_procedures, # (patient_id, encounter_id, disease_id, admission_time, severity, rng,
                                 #  country, *, performer_id) -> list[ProcedureRecord]
    generate_rehab_sessions,     # (patient_id, encounter_id, surgery_date, total_days, rng,
                                 #  country) -> list[RehabSession]
)
from clinosim.modules.procedure.engine import (
    build_intubation_procedure,  # (patient_id, encounter_id, start, country, procedure_id, *, performer_id)
                                 #  -> ProcedureRecord
    age_gated_procedures,        # (patient_id, encounter_id, rules, age_days, start, first_index, country,
                                 #  *, performer_id) -> list[ProcedureRecord]
)
```

`engine.py` 内部の `ProcedureMeta` は procedure ごとの SNOMED
`category_code` + `body_site_code` を持ち、outcome / 合併症の SNOMED
code とともに
[`clinosim/codes/data/procedure-snomed-metadata.yaml`](../../codes/data/procedure-snomed-metadata.yaml)
から読み込む。bedside 処置ごとの CPT / K-code / 名称 / 麻酔は処置
catalog (`codes/data/clinosim-procedure-catalog.yaml` を引く
`clinosim.codes.procedures.bedside_procedures()`、Issue #2263) 由来で、
`engine.py` の `_BEDSIDE_PROCEDURES` tuple list に射影される。

インプラント (Issue #3406): 器材を残す手技は `implants_used` に
`locale/shared/narrative_op_implants.yaml` のキー (en + ja) で記録する。出所は
疾患 protocol の `procedure.implants`、無ければ catalog の `implants` 表
(`clinosim.codes.procedures.procedure_implants`: PCI は薬剤溶出性ステント、
ペースメーカー本体とリード、人工膝関節、掌側ロッキングプレート)。大腿骨近位部
骨折手術は従来どおり釘・スクリュー・人工骨頭を選ぶ。乱数の消費なし。サイズ・機種は
モデル化していないため記載しない。手術記録の使用機器・材料欄はこれを記し、
リストが空のときだけ「なし」と書く。

検体 (Issue #3284): 切除術は病理へ提出する組織を `specimens_sent` に
`codes/data/snomed-maps.yaml` の `specimen_type` キー (`appendix`、
`gallbladder`、`colon_segment`) で記録する。`simulate_surgery` と bedside
経路が catalog の `specimens` 表
(`clinosim.codes.procedures.procedure_specimens`) から写す。catalog データで
乱数は引かない。手術記録 / 処置記録はラベルで列挙し、FHIR 出力は 1 件ずつ
Specimen を出す。

出血量・ASA 分類・麻酔 (Issue #3257): `ProcedureRecord` の既定値は空
(`estimated_blood_loss_ml` / `asa_class` は None、`anesthesia_type` は "")
で、「記録なし」を意味する。出血量 (疾患 YAML の
`procedure.estimated_blood_loss_ml`) と ASA 分類を設定するのは
`simulate_surgery` のみ。bedside / 年齢条件 / 気管挿管の record は
catalog の麻酔と、呼び出し側の `performer_id` (encounter の担当医) を
`primary_surgeon_id` に持ち、出血量・ASA 分類は持たない。

処置後ケア (Issue #3257): 処置記録・手術記録の対象となる catalog の各項目は
`aftercare` 区分 (`urinary_catheter`・`central_line`・`vascular_access`・
`surgical_wound` など。`clinosim.codes.procedures.procedure_aftercare` で読む)
を持つ。記録はその区分の `procedure_aftercare.<区分>` 文言を術後方針として
書き、区分のない種別は `general` の方針になる。

## 決定論

- `ENRICHER_SEED_OFFSETS` にサブ seed 未登録。全 entry は caller
  供給の `rng` に対して純粋。
- 例外: `generate_bedside_procedures` 内の `_ISSUE939_PROCEDURE_RULES`
  loop は `determinism.default_rng(seeding.issue939_procedure_seed(encounter_id,
  proc_type))` から draw し、caller の stream を動かさない。
- 部位の詳細 (Issue #3549、`details.procedure_details`) も caller の
  stream から draw しない。対の部位の手術の側、PCI のアクセス部位と
  標的血管、中心静脈カテーテルの挿入静脈は、滞在に正準の側がある場合は
  それを使い (脳卒中の開頭は `disease.laterality.stroke_lesion_side`、
  股・膝・手関節の手術は `imaging.engine.imaging_laterality`。手術側 =
  撮像側)、無い場合は `determinism.default_rng(seeding.procedure_detail_seed(
  encounter_id, proc_type))` から引く。
- ベッドサイド処置の所要時間 (Issue #3550) は従来どおり処置ごとに
  `rng.normal` 1 回。カタログの `duration_minutes: {mean, sd, min, max}` は
  値だけを変え、stream 位置は従来の単一既定値のときと同じ。
- 合併症サンプリングは `_surgery_thresholds` の確率で gate された
  `rng.random()`。outcome 導出は合併症リストからの決定論的 mapping
  (無し → success、有り → partial)。

## 依存

- `clinosim.modules._shared` — `is_jp`。
- `clinosim.codes` — `data_table` (`procedure-snomed-metadata`)。
  `clinosim.codes.procedures.bedside_procedures` (処置 catalog)。
- `clinosim.datafiles` — `load_data_yaml` (`procedure_rules.yaml`)。
  `clinosim.locale.loader.load_code_mapping`。
- `clinosim.determinism` + `clinosim.seeding.issue939_procedure_seed`
  — Issue #939 規則用の隔離サブ RNG。
- `clinosim.modules.procedure._bedside_thresholds` — bedside 処置
  確率 + time-offset 範囲 (Issue #637)。
- `clinosim.modules.procedure._rehab_thresholds` — session
  duration, phase cutoff, 疼痛モデル param, modality 確率
  (Issue #637)。
- `clinosim.modules.procedure._surgery_thresholds` — 手術 timing,
  duration / EBL 既定値, ASA, 術中合併症, state-impact 定数 (Issue #637)。
- `clinosim.types.procedure` — `ProcedureRecord`, `RehabSession`。
- `numpy`, `pydantic` (`_Rule`, `_ProcedureRulesConfig`)。

## 定数と設定

- **Bedside threshold** ([`_bedside_thresholds.py`](_bedside_thresholds.py)、
  Issue #637): 重症度 multiplier、入院後時刻 offset (floor + 指数分布
  平均)、duration (floor / mean / SD)。処置ごとの base 確率は data
  (下記 `reference_data/procedure_rules.yaml`)。
- **Rehab threshold** ([`_rehab_thresholds.py`](_rehab_thresholds.py)、
  Issue #637): 開始 POD、session 時刻、JP / US session 時間、skip-day
  確率、phase cutoff (early ≤ POD 3 / mid ≤ POD 14 / late)、疼痛
  モデル (base、POD ごと decay、SD、clamp)、参加 / 拒否閾値。
- **Surgery threshold** ([`_surgery_thresholds.py`](_surgery_thresholds.py)、
  Issue #637): JP / US 手術までの時間 mean / SD / floor、duration・EBL
  既定値 (protocol の `procedure` block が上書き)、脊椎麻酔確率、ASA
  class 閾値、術中合併症確率、大腿骨骨折術式の配分、術後 state-impact
  delta。
- **処置 rule** ([`reference_data/procedure_rules.yaml`](reference_data/procedure_rules.yaml)、
  Issue #2525): `bedside_rules` (encounter RNG から draw →
  `_PROCEDURE_RULES`) と `isolated_rules` (`issue939_procedure_seed`
  から draw → `_ISSUE939_PROCEDURE_RULES`)。各 rule は
  `{diseases, procedures: {type: base 確率}}`。`_load_procedure_rules`
  が load し、`_ProcedureRulesConfig` / `_Rule` Pydantic model で検証
  (既知の疾患 / ED condition id、既知の処置 type、確率は `[0, 1]`)。
  rule 順序は draw 順なので load-bearing。
- **処置の詳細** ([`reference_data/procedure_details.yaml`](reference_data/procedure_details.yaml)、
  Issue #3549): どの処置種別が側を持つか (とその出所)、PCI の標的血管・
  アクセス部位、中心静脈の挿入静脈の重み。`details.py` が読込時に検証する
  (キーは `snomed-maps.yaml` の `coronary_vessel` / `arterial_access_site` /
  `central_vein` に存在すること)。重みは clinosim のモデリング上の選択で、
  公表された数値ではない。`ProcedureRecord` に `laterality`、
  `access_site`、`target_vessel` を追加し、中心静脈の静脈は
  `body_site_code` に入る。FHIR `Procedure.bodySite` に血管と SNOMED の
  側 (laterality) 修飾概念を、アクセス部位は `note` に出す。
- **ベッドサイド処置の所要時間** (Issue #3550):
  `codes/data/clinosim-procedure-catalog.yaml` の処置別 `duration_minutes`
  (公表値ではなくモデリング上の選択)。無い種別は `_bedside_thresholds`
  の既定値のまま。
- 本モジュールは他に、渡された disease protocol と
  `clinosim/codes/data/` の SNOMED metadata yaml・処置 catalog を読む。

## ディレクトリ構造

```
clinosim/modules/procedure/
  __init__.py                        5 symbol を再 export
  engine.py                          simulate_surgery + generate_bedside_procedures + generate_rehab_sessions + build_intubation_procedure
  _bedside_thresholds.py             bedside 処置確率 + timing (Issue #637)
  _rehab_thresholds.py               rehab session shape + 疼痛モデル (Issue #637)
  _surgery_thresholds.py             surgery timing / duration / state-impact (Issue #637)
  details.py                         (encounter, 処置種別) ごとの左右 / PCI 血管・アクセス部位 / 中心静脈の挿入静脈、読込時に検証 (Issue #3549)
  reference_data/
    procedure_rules.yaml             bedside_rules + isolated_rules (疾患 → 処置 base 確率、Issue #2525)
    procedure_details.yaml           左右、PCI 血管・アクセス部位、中心静脈の挿入静脈の重み (Issue #3549)
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` は存在しない**。

## Enricher 配線

該当なし — 本モジュールは encounter simulator が imperative に
呼び出す。`register_builtin_enrichers` に登録なく、
`ENRICHER_SEED_OFFSETS` にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | 入院 1 回につき、`protocol.requires_surgery` なら `simulate_surgery` + `generate_rehab_sessions`、その後 `generate_bedside_procedures` を呼ぶ。 |
| Emergency encounter | [`clinosim/simulator/emergency.py`](../../simulator/emergency.py) | ED bedside 行為で `generate_bedside_procedures`。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | 気道閾値を越えたとき `build_intubation_procedure`。 |
| FHIR Procedure builder | [`clinosim/modules/output/fhir_r4/procedures/`](../output/fhir_r4/procedures/) | `ProcedureRecord` (+ 酸素療法 performedPeriod) を read して FHIR `Procedure` を emit。 |

## テスト

```bash
pytest tests/unit -k "procedure or oxygen_therapy_procedure" -q
```

個別ファイル:

- [`tests/unit/test_procedure_types.py`](../../../tests/unit/test_procedure_types.py)
  — dataclass shape。
- [`tests/unit/test_procedure.py`](../../../tests/unit/test_procedure.py)
  — `simulate_surgery` + bedside + rehab 挙動。
- [`tests/unit/test_procedure_fhir_fields.py`](../../../tests/unit/test_procedure_fhir_fields.py)
  — FHIR field consistency guard。
- [`tests/integration/test_escalation_procedure_emission.py`](../../../tests/integration/test_escalation_procedure_emission.py)
  — escalation 起点の procedure emission end-to-end。
- [`tests/unit/output/test_fhir_procedure_jp_text.py`](../../../tests/unit/output/test_fhir_procedure_jp_text.py)
  — JP 表示テキスト guard。
- [`tests/unit/output/test_fhir_oxygen_therapy_procedure.py`](../../../tests/unit/output/test_fhir_oxygen_therapy_procedure.py)
  — vitals flag 起点の 酸素療法 `performedPeriod` (Issue #796)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
