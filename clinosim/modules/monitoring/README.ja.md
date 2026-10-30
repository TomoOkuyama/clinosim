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
  case-insensitive 部分一致で match し、mapping 上の各 monitoring lab を
  record の target encounter (最初の外来 encounter、無ければ最初の
  encounter) に注入 — ただし同 analyte が lab ごとの `interval_months`
  以内に採取済みなら skip (Issue #2143 — record は患者ごとに時系列順で
  走査)、per-encounter
  dedup により disease YAML flow (sepsis / PE / GI bleed) が正当に
  同 analyte を発注しているケースを尊重して二重発行しない。
- **Out of scope**: 慢性薬付与
  ([`clinosim.modules.patient`](../patient/README.ja.md) activator)、
  disease YAML lab order
  ([`clinosim.modules.order`](../order/README.ja.md))、lab 値そのもの
  の導出
  ([`clinosim.modules.observation`](../observation/README.ja.md))、
  FHIR emission
  ([`clinosim.modules.output`](../output/README.ja.md))、
  induction vs maintenance の cadence (lab ごとの固定最小
  `interval_months` のみモデル化)。

## Public API

本モジュールは独立した 2 経路を持つ:

```python
# 1. POST_RECORDS enricher 経路 (medication_monitoring.yaml)
from clinosim.modules.monitoring.enricher import enrich_medication_monitoring
from clinosim.modules.monitoring.mapping import (
    load_medication_monitoring,      # (path=None) -> {drug_name: {aliases, drug_ja, monitoring: [...]}}
    match_drugs,                     # (current_medications, mapping) -> list[str] canonical drug 名
)

# 2. 慢性外来 lab リスト経路 (med_lab_mapping.yaml)、__init__.py から re-export
from clinosim.modules.monitoring import (
    load_medication_lab_mapping,     # () -> {entry: {matches, labs, per_visit_probability}} (lru_cache)
    monitoring_labs_for_patient,     # (current_medications, rng) -> list[str] lab 名
)
```

`monitoring_labs_for_patient` (`engine.py`) は
`clinosim/simulator/phases/_healthcare_calendar.py` から `chronic_visit`
event ごとに呼ばれ、返り値の lab を visit の `visit_labs` に merge する。
各 mapping entry は visit の `ev_rng` 上で `per_visit_probability` gate
される (enricher sub-seed ではなく visit RNG stream を消費)。

## 決定論

- サブ seed オフセット `0x4D4D` (`"MM"`) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["medication_monitoring"]` に登録済み。
- enricher 経路の患者単位サブ RNG:
  `derive_sub_seed(master_seed, offset, patient_id)` — master RNG
  未消費 (care_level / family_history pattern に一致)。
- per-lab noise draw は `individual_lab_seed(order_id)`
  ([`clinosim/seeding.py`](../../seeding.py)) — `outpatient.py`,
  `inpatient.py` Pass 1 と同じ AD-59 per-order 分離。
- 合成 order id は content 由来 (`ORD-<encounter_id>-MED-MON-<NN>`)
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

呼び出し側: `clinosim/simulator/enrichers.py` (enricher 登録) と
`clinosim/simulator/phases/_healthcare_calendar.py`
(`monitoring_labs_for_patient`)。

## 定数と設定

- [`reference_data/medication_monitoring.yaml`](reference_data/medication_monitoring.yaml)
  — enricher 用 drug → labs mapping (top-level `mappings:` key 配下)。各 entry:
  ```yaml
  mappings:
    <Drug canonical name>:
      aliases:        [<optional case-insensitive 部分一致>]
      drug_ja:        "<薬剤の日本語表示>"                  # 任意 (Issue #871)
      monitoring:
        - lab:             <observation engine 内部 analyte 名>
          interval_months: <整数 >= 1、採取間の最小月数 (Issue #2143)>
          loinc:           "<LOINC code>"
          rationale:       "<1 文の臨床根拠>"
          rationale_ja:    "<日本語の臨床根拠>"              # 任意 (Issue #871)
  ```
  alias は case-insensitive 部分一致で `physiology.engine._WARFARIN_NAMES`
  と同じ pattern を踏襲 — `"Warfarin 3mg PO"`, `"ワルファリン"`,
  `"WARFARIN"` はすべて Warfarin entry と match する。
- Loader は [`mapping.py`](mapping.py) — 意図的に cache-less
  (小 file、POST_RECORDS pass あたり 1 回のみ呼ばれる)、Pydantic を
  使わず plain dict に parse (sibling `sdoh.load_social_history`
  loader style)。必須 key 欠落は fail-loud — YAML typo は load 時に
  顕在化し「drug never matched」の silent 症状にならない (monitoring 行ごとに
  `lab`, `loinc`, 整数 `interval_months >= 1` が必須)。
- [`reference_data/med_lab_mapping.yaml`](reference_data/med_lab_mapping.yaml)
  — `monitoring_labs_for_patient` 用の慢性外来 mapping (top-level
  `medication_lab_mapping:` key 配下)。各 entry は `matches`
  (`drug_name` / `drug_name_ja` への部分一致 pattern)、`labs`
  (canonical analyte 名)、`per_visit_probability` を持つ。
  `engine.load_medication_lab_mapping` が load (cache あり、fail-loud)。

## ディレクトリ構造

```
clinosim/modules/monitoring/
  __init__.py                        load_medication_lab_mapping + monitoring_labs_for_patient を re-export
  engine.py                          load_medication_lab_mapping + monitoring_labs_for_patient (慢性外来経路)
  enricher.py                        enrich_medication_monitoring (POST_RECORDS)
  mapping.py                         load_medication_monitoring + match_drugs
  reference_data/
    medication_monitoring.yaml       drug → monitoring-labs mapping (enricher)
    med_lab_mapping.yaml             薬剤 → 慢性外来 lab mapping (engine)
```

**`audit.py` は存在しない**。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L288-308` 付近) で登録:

- `name="medication_monitoring"`, `stage=POST_RECORDS`, `order=65`,
  `enabled=lambda c: True`。
- `care_level` (order=60) の後、`health_checkup` (order=70) の前に
  実行 — 全 cross-record enricher が record shape を populate した後、
  JP-only opt-in の `health_checkup` が CHECKUP encounter を追加する
  前に走る。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py:301`](../../simulator/enrichers.py) | POST_RECORDS order=65 登録。 |
| 慢性外来スケジューラ | [`clinosim/simulator/phases/_healthcare_calendar.py`](../../simulator/phases/_healthcare_calendar.py) | `chronic_visit` event ごとに `monitoring_labs_for_patient` を呼ぶ。 |
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
- [`tests/unit/test_monitoring_intervals.py`](../../../tests/unit/test_monitoring_intervals.py)
  — `interval_months` スケジューリング (Issue #2143)。
- [`tests/unit/test_monitoring_doac.py`](../../../tests/unit/test_monitoring_doac.py)
  — DOAC → eGFR mapping。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
