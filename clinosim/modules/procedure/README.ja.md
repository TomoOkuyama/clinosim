# `clinosim.modules.procedure` — 手術 + bedside 処置 + rehab 生成

## 概要

encounter 単位の procedure emission を 3 家族に対して所有:

1. **手術** (`simulate_surgery`) — disease YAML の `surgery` block
   または emergency encounter の `surgery` field 駆動: 期間、術中
   合併症、術後 state 影響 (post-op window の state delta)、生成
   `outcome` 文字列を含む `ProcedureRecord` を構成。
2. **Bedside 処置** (`generate_bedside_procedures`) — 規則一致した
   ルーチン入院処置 (中心静脈路、動脈路、胸腔穿刺、腹腔穿刺、腰椎
   穿刺、フォーリー挿入、NG 挿管、包交) を重症度 scale の base 確率
   + 入院後時刻 offset サンプリングで発火。
3. **術後 rehab** (`generate_rehab_sessions`) — post-op day 1 から
   退院日までの日次 PT スケジュール。phase cutoffs、疼痛モデル
   parameter、modality 配分を持つ。

3 engine が使っていた scalar は全て inline から companion
`_*_thresholds.py` 3 file (Issue #637 sweep) に臨床引用付きで lift 済。

## Scope

- **In scope**: `simulate_surgery` (術中合併症 + state 影響を持つ
  `ProcedureRecord` を返す); `generate_bedside_procedures` (重症度
  scale 確率 + time-offset サンプリング); `generate_rehab_sessions`
  (day 1 から退院までの `RehabSession` list); `_derive_outcome`,
  `_map_complications` (test で必要な internal helper);
  `ProcedureMeta` (procedure ごとの metadata dataclass)。
- **Out of scope**: procedure コード YAML
  ([`clinosim.codes`](../../codes/))、procedure encounter timeline
  ([`clinosim.modules.encounter`](../encounter/README.md))、FHIR
  `Procedure` emission
  ([`clinosim.modules.output.fhir_r4.procedures`](../output/fhir_r4/procedures/README.md))、
  imaging 発注構築 — これは
  [`clinosim.modules.imaging`](../imaging/README.md)。

### 縦断サービスライン Procedure (v0.5 → v0.6.0)

上記 3 種 (手術 / bedside / rehab) と並列に、以下 2 種の Procedure が
同じ `ProcedureRecord` shape で emit される:

- **分娩 Procedure** — 母親側の周産期分娩 Encounter (詳細:
  [`clinosim.modules.encounter`](../encounter/README.md)) に付与。
  Code: JP `K894` (経腟分娩 — MHLW 診療報酬点数表 K-code) または
  US CPT `59400` (routine obstetric care incl. vaginal delivery)。
  emit 元は
  [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py)、
  shape は
  [`clinosim/locale/shared/perinatal.yaml`](../../locale/shared/perinatal.yaml)
  の `procedure` block。`simulate_surgery` を経由しない。
- **放射線治療 Procedure** — オンコロジーサービスラインの放射線
  encounter に付与。Procedure は modality / dose / site を disease
  YAML の放射線ブロックから持つ。専用 builder が emit (session 93 landing)。
  `simulate_surgery` を経由しない。

両者とも canonical な `ProcedureRecord` field を維持するため、FHIR
adapter ([`output/fhir_r4/procedures/`](../output/fhir_r4/procedures/README.md))
は新しい resource-type builder を追加せずに emit 可能。

## Public API

```python
from clinosim.modules.procedure import (
    ProcedureRecord,             # dataclass (types.encounter から再 export)
    RehabSession,                # dataclass
    simulate_surgery,            # (patient, encounter, protocol, rng, ...) -> ProcedureRecord
    generate_bedside_procedures, # (patient, encounter, protocol, rng, ...) -> list[ProcedureRecord]
    generate_rehab_sessions,     # (patient, encounter, ...) -> list[RehabSession]
)
```

`engine.py` 内部の `ProcedureMeta` は procedure ごとの metadata
(code, display, duration distribution, 一般合併症, 期待 outcome
map) を持つ — この table が `simulate_*` / `generate_*` 呼び出しの
背後にあるデータ。

## 決定論

- `ENRICHER_SEED_OFFSETS` にサブ seed 未登録。全 entry は caller
  供給の `rng` に対して純粋。encounter simulator (`inpatient.py`,
  `emergency.py`) が呼び出し前に per-encounter サブ RNG を導出する。
- 合併症サンプリングは `_bedside_thresholds` / `_surgery_thresholds`
  の確率で gate された `rng.random()`。outcome 導出は合併症リスト
  からの決定論的 mapping。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `is_us`。
- `clinosim.modules.procedure._bedside_thresholds` — bedside 処置
  確率 + time-offset 範囲 (Issue #637)。
- `clinosim.modules.procedure._rehab_thresholds` — session
  duration, phase cutoff, 疼痛モデル param, modality 確率
  (Issue #637)。
- `clinosim.modules.procedure._surgery_thresholds` — 手術 timing,
  duration 分布, per-procedure state-impact delta (Issue #637)。
- `clinosim.modules.disease.acuity` —
  `EMERGENCY_PRIORITY_DISEASES`, `CRITICAL_MONITORING_DISEASES`
  (emergency 限定 bedside 処置の cross-reference)。
- `clinosim.types.encounter` — `ProcedureRecord`、および engine が
  mutate する encounter / physiology-state 型。
- `numpy` — `np.random.Generator`。

## 定数と設定

- **Bedside threshold** ([`_bedside_thresholds.py`](_bedside_thresholds.py)、
  Issue #637): 処置ごとの base 確率、重症度 multiplier、time-offset
  サンプリング範囲 (入院後分 / 時間)、gate 定数。
- **Rehab threshold** ([`_rehab_thresholds.py`](_rehab_thresholds.py)、
  Issue #637): 日次 session duration 分布、phase cutoff (acute /
  subacute / 退院準備)、疼痛モデル beta parameter、modality 配分
  確率。
- **Surgery threshold** ([`_surgery_thresholds.py`](_surgery_thresholds.py)、
  Issue #637): OR スケジュール offset、procedure 家族別 duration
  mean / SD、術中合併症確率、術後 state-impact delta。
- **`reference_data/` は無い** — 本モジュールは disease YAML を
  (protocol 経由で) 直接読み、procedure カタログを複製しない。

## ディレクトリ構造

```
clinosim/modules/procedure/
  __init__.py                        5 symbol を再 export
  engine.py                          simulate_surgery + generate_bedside_procedures + generate_rehab_sessions
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
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | 入院日ごとに `simulate_surgery`, `generate_bedside_procedures`, `generate_rehab_sessions` を呼び出す。 |
| Emergency encounter | [`clinosim/simulator/emergency.py`](../../simulator/emergency.py) | ED-to-OR 経路で `simulate_surgery`、ED bedside 行為で `generate_bedside_procedures`。 |
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
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
