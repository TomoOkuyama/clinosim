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
   で疾患 / condition に一致した処置 (例: 尿道カテーテル、中心静脈 /
   動脈ライン、腰椎穿刺、胸腔穿刺、腹腔穿刺、NG チューブ、胸腔
   ドレーン、除細動、輸血、緊急透析、心電図、末梢ライン、シーネ /
   非観血的整復、創処置、酸素療法) を重症度 scale の base 確率 +
   入院後時刻 offset サンプリングで発火。別表
   `_ISSUE939_PROCEDURE_RULES` (PCI、ペースメーカー、開頭血腫除去、
   イレウス管、腸切除; Issue #939) は専用の (encounter, procedure)
   別サブ RNG で draw。
3. **術後 rehab** (`generate_rehab_sessions`) — post-op day 1 から
   退院日までの日次 PT スケジュール。early / mid / late phase の
   活動、疼痛モデル、skip-day / 拒否確率を持つ。
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
  Code: JP `K894` (経腟分娩 — MHLW 診療報酬点数表 K-code) または
  US CPT `59400` (routine obstetric care incl. vaginal delivery)。
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
                                 #  country="JP", surgeon_id="", anesthesiologist_id="", operating_rooms=2)
                                 #  -> (ProcedureRecord, dict[str, float])
    generate_bedside_procedures, # (patient_id, encounter_id, disease_id, admission_time, severity, rng,
                                 #  country="US") -> list[ProcedureRecord]
    generate_rehab_sessions,     # (patient_id, encounter_id, surgery_date, total_days, rng,
                                 #  country="JP") -> list[RehabSession]
)
from clinosim.modules.procedure.engine import (
    build_intubation_procedure,  # (patient_id, encounter_id, start, country, procedure_id) -> ProcedureRecord
)
```

`engine.py` 内部の `ProcedureMeta` は procedure ごとの SNOMED
`category_code` + `body_site_code` を持ち、outcome / 合併症の SNOMED
code とともに
[`clinosim/codes/data/procedure-snomed-metadata.yaml`](../../codes/data/procedure-snomed-metadata.yaml)
から読み込む。bedside 処置ごとの CPT / K-code / 名称 / 麻酔は
`engine.py` の `_BEDSIDE_PROCEDURES` 表。

## 決定論

- `ENRICHER_SEED_OFFSETS` にサブ seed 未登録。全 entry は caller
  供給の `rng` に対して純粋。
- 例外: `generate_bedside_procedures` 内の `_ISSUE939_PROCEDURE_RULES`
  loop は `determinism.default_rng(seeding.issue939_procedure_seed(encounter_id,
  proc_type))` から draw し、caller の stream を動かさない。
- 合併症サンプリングは `_surgery_thresholds` の確率で gate された
  `rng.random()`。outcome 導出は合併症リストからの決定論的 mapping
  (無し → success、有り → partial)。

## 依存

- `clinosim.modules._shared` — `is_jp`。
- `clinosim.determinism` + `clinosim.seeding.issue939_procedure_seed`
  — Issue #939 規則用の隔離サブ RNG。
- `clinosim.modules.procedure._bedside_thresholds` — bedside 処置
  確率 + time-offset 範囲 (Issue #637)。
- `clinosim.modules.procedure._rehab_thresholds` — session
  duration, phase cutoff, 疼痛モデル param, modality 確率
  (Issue #637)。
- `clinosim.modules.procedure._surgery_thresholds` — 手術 timing,
  duration / EBL 既定値, ASA, 術中合併症, state-impact 定数 (Issue #637)。
- `clinosim.modules.disease.acuity` — `NEURO_LOC_MONITORING_DISEASES`
  (`_PROCEDURE_RULES` の 1 entry の疾患リスト)。
- `clinosim.types.procedure` — `ProcedureRecord`, `RehabSession`。
- `numpy`, `yaml`。

## 定数と設定

- **Bedside threshold** ([`_bedside_thresholds.py`](_bedside_thresholds.py)、
  Issue #637): 重症度 multiplier、入院後時刻 offset (floor + 指数分布
  平均)、duration (floor / mean / SD)。処置ごとの base 確率は
  `engine.py` の `_PROCEDURE_RULES` / `_ISSUE939_PROCEDURE_RULES`。
- **Rehab threshold** ([`_rehab_thresholds.py`](_rehab_thresholds.py)、
  Issue #637): 開始 POD、session 時刻、JP / US session 時間、skip-day
  確率、phase cutoff (early ≤ POD 3 / mid ≤ POD 14 / late)、疼痛
  モデル (base、POD ごと decay、SD、clamp)、参加 / 拒否閾値。
- **Surgery threshold** ([`_surgery_thresholds.py`](_surgery_thresholds.py)、
  Issue #637): JP / US 手術までの時間 mean / SD / floor、duration・EBL
  既定値 (protocol の `procedure` block が上書き)、脊椎麻酔確率、ASA
  class 閾値、術中合併症確率、大腿骨骨折術式の配分、術後 state-impact
  delta。
- **`reference_data/` は無い** — 本モジュールは渡された disease
  protocol と `clinosim/codes/data/` の SNOMED metadata yaml を読む。

## ディレクトリ構造

```
clinosim/modules/procedure/
  __init__.py                        5 symbol を再 export
  engine.py                          simulate_surgery + generate_bedside_procedures + generate_rehab_sessions + build_intubation_procedure
  _bedside_thresholds.py             bedside 処置確率 + timing (Issue #637)
  _rehab_thresholds.py               rehab session shape + 疼痛モデル (Issue #637)
  _surgery_thresholds.py             surgery timing / duration / state-impact (Issue #637)
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` / `reference_data/` は存在しない**。

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
