# `clinosim.modules.monitoring` — 慢性薬駆動 monitoring lab pipeline

## 概要

慢性薬が要求する standard-of-care monitoring lab (代表例:
Warfarin → PT-INR) を、POST_RECORDS 時点で患者の encounter に注入し、
Issue #736 で顕在化し META Issue #757 で追跡されているアーキテクチャ
ギャップを埋める。本モジュール以前、simulator の lab 発注源は
disease YAML の `laboratory` block、per-encounter admission /
discharge protocol、および antibiotic 起点 order の 3 系統だけで、
`patient.current_medications` を参照するものが無かった。結果として
外来 HTN follow-up のみを持つ warfarin 患者は PT-INR を一度も
持たなかった。

## Scope

- **In scope**: POST_RECORDS 時点で各患者の `current_medications` を
  読み、`medication_monitoring.yaml` の drug + alias に対して
  case-insensitive 部分一致で match し、適格 encounter 1 件あたり
  monitoring lab を 1 件注入 (MVP scope — 頻度 / cadence
  スケジューリングは META #757 の後続 PR で対応)、per-encounter
  dedup により disease YAML flow (sepsis / PE / GI bleed) が正当に
  同 analyte を発注しているケースを尊重して二重発行しない。
- **Out of scope**: 慢性薬付与
  ([`clinosim.modules.patient`](../patient/README.md) activator)、
  disease YAML lab order
  ([`clinosim.modules.order`](../order/README.md))、lab 値そのもの
  の導出
  ([`clinosim.modules.observation`](../observation/README.md))、
  FHIR emission
  ([`clinosim.modules.output`](../output/README.md))、
  頻度 scheduling (daily vs monthly、induction vs maintenance) —
  META #757 pass 3+ 予定。

## Public API

`__init__.py` は package docstring のみ。呼び出し側は submodule から
直接 import:

```python
from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.monitoring.mapping import (
    load_medication_monitoring,      # () -> {drug_name: {aliases, monitoring: [...]}}
    match_drugs,                     # (current_medications) -> list[matched drug entry]
)
```

## 決定論

- サブ seed オフセット `0x4D4D` (`"MM"`) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["medication_monitoring"]` に登録済み。
- 患者単位サブ RNG:
  `derive_sub_seed(master_seed, offset, patient_id)` — master RNG
  未消費 (care_level / family_history pattern に一致)。
- per-lab noise draw は `individual_lab_seed(order_id)`
  ([`clinosim/seeding.py`](../../seeding.py)) — `outpatient.py`,
  `inpatient.py` Pass 1 と同じ AD-59 per-order 分離。
- 合成 order id は content 由来 (`<encounter_id>-MED-MON-<idx>`)
  なので同 seed の repeated run で安定。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`。
- `clinosim.modules.observation.engine` — `canonical_lab_name`,
  `generate_lab_result`, `get_lab_unit`, `determine_flag` (単一の
  lab-emission surface)。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`,
  `individual_lab_seed`。
- `clinosim.types.encounter` — `EncounterType`, `Order`,
  `OrderResult`, `OrderStatus`。
- `yaml`, `numpy`。

## 定数と設定

- [`reference_data/medication_monitoring.yaml`](reference_data/medication_monitoring.yaml)
  — drug → labs mapping。各 entry:
  ```yaml
  <Drug canonical name>:
    aliases:        [<optional case-insensitive 部分一致>]
    monitoring:
      - lab:        <observation engine 内部 analyte 名>
        loinc:      "<LOINC code>"
        rationale:  "<1 文の臨床根拠>"
  ```
  alias は case-insensitive 部分一致で `physiology.engine._WARFARIN_NAMES`
  と同じ pattern を踏襲 — `"Warfarin 3mg PO"`, `"ワルファリン"`,
  `"WARFARIN"` はすべて Warfarin entry と match する。
- Loader は [`mapping.py`](mapping.py) — 意図的に cache-less
  (小 file、POST_RECORDS pass あたり 1 回のみ呼ばれる)、Pydantic を
  使わず plain dict に parse (sibling `sdoh.load_social_history`
  loader style)。必須 key 欠落は fail-loud — YAML typo は load 時に
  顕在化し「drug never matched」の silent 症状にならない。

## ディレクトリ構造

```
clinosim/modules/monitoring/
  __init__.py                        package docstring のみ
  enricher.py                        enrich_medication_monitoring (POST_RECORDS)
  mapping.py                         load_medication_monitoring + match_drugs
  reference_data/
    medication_monitoring.yaml       drug → monitoring-labs mapping
```

**`engine.py` / `audit.py` は存在しない** — enricher entry は
`enricher.py`、mapping helper は `mapping.py`。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L213-231` 付近) で登録:

- `name="medication_monitoring"`, `stage=POST_RECORDS`, `order=65`,
  `enabled=lambda c: True`。
- `care_level` (order=60) の後、`health_checkup` (order=70) の前に
  実行 — 全 cross-record enricher が record shape を populate した後、
  JP-only opt-in の `health_checkup` が CHECKUP encounter を追加する
  前に走る。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:226`](../../simulator/enrichers.py) | POST_RECORDS order=65 登録。 |
| Observation engine | [`clinosim/modules/observation/engine.py`](../observation/engine.py) | `generate_lab_result` + `determine_flag` + `get_lab_unit` が emit lab 値を生成。 |
| 下流 FHIR + CSV | (生成される `Order` / `OrderResult` 経由) | 注入 order が標準 lab-emission path を流れる。 |

## テスト

```bash
pytest tests/unit -k medication_monitoring -q
```

個別ファイル:

- [`tests/unit/test_medication_monitoring.py`](../../../tests/unit/test_medication_monitoring.py)
  — mapping load、drug matching (case + JA)、per-encounter dedup、
  決定論。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
