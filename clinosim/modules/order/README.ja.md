# `clinosim.modules.order` — 発注 + panel grouping + treatment classifier

## 概要

encounter timeline 上で labs / imaging / medication / supportive
treatment をスケジュールするために simulator が使う「臨床発注構築」
一切を所有する。3 責務を包含:

1. **発注配置** (`engine.py`) — admission + 日次 lab + imaging 発注
   構築、medication order enrichment (自由テキスト dose を構造化
   dose / route / frequency に parse)、結果時刻計算 (STAT / routine
   base + shift + weekend modifier + M/M/1 風 hospital-state 遅延)。
2. **Panel grouping** (`panel_grouping.py`) — lab spec のリストを
   panel (ABG, CBC, BMP, LFT, Lipid, Coag, UA, Checkup) と stand-alone
   に分類する単一 edit point。`reference_data/lab_panel_groups.yaml`
   駆動。全 lab-ordering call site は `classify_lab_specs` を経由
   MUST ([`AGENTS.md`](../../../AGENTS.md) — `derive_lab_values` flag
   helper と同じ AD-59 兄弟 pattern)。
3. **Treatment classifier** (`treatment_classifier.py`) — supportive
   / treatment 文字列を `MEDICATION` / `PROCEDURE` / `THERAPY`
   `Order` に振り分ける単一 keyword 表。以前 inpatient
   `supportive[]` と encounter `treatment[]` が各々自前の inline
   keyword 表を持ち drift していた J5 pattern を解消する。

さらに本モジュール専用の [`audit.py`](audit.py) を所有 — HAI と
antibiotic に続く 3 番目の AD-60 per-module audit plug-in。canonical
constants cross-check、`_bb_service_requests` に対する synthetic-Order
`lift_firing_proof`、および全 LAB Observation の 100 % が existing
ServiceRequest への `basedOn` を持つことを要求する
`basedon_coverage` clinical-axis gate を含む。

## Scope

- **In scope**: `place_admission_orders`, `place_daily_lab_orders`,
  `place_imaging_orders` (Tier 1 #2 imaging-chain DRY entry point)、
  `enrich_medication_order` + `parse_dose_string`、
  `calculate_lab_result_time` (STAT / routine + 夜勤 deferral)、
  `calculate_imaging_result_time` (scheduling + reporting delay)、
  `calculate_result_time_from_state` (`facility.HospitalState` 経由
  の M/M/1 遅延)、`order_resource_type` (`MEDICATION` / `PROCEDURE`
  / `THERAPY` / `LAB` / `IMAGING` への単一 dispatch)、
  `replay_order_to_state` (queue-replay test 用)、
  `classify_lab_specs` + `load_panel_definitions` +
  `PANEL_PRIORITY_ORDER` (`("ABG", "CBC", "BMP", "LFT", "Lipid",
  "Coag", "UA", "Checkup")`)、3 種 `classify_*` treatment
  classifier。
- **Out of scope**: lab 値そのものの導出
  ([`observation.engine.generate_lab_result`](../observation/README.md))、
  lab / imaging 結果が依存する physiology state
  ([`physiology`](../physiology/README.md))、hospital state
  ([`facility.HospitalState`](../facility/README.md))、FHIR
  ServiceRequest emission
  ([`output/fhir_r4/labs/service_request.py`](../output/fhir_r4/labs/service_request.py))、
  抗菌薬 regimen 構築 ([`antibiotic`](../antibiotic/README.md))。

## Public API

`__init__.py` は panel-grouping 3 symbol を再 export。それ以外の
entry は submodule から直接 import:

```python
# 再 export
from clinosim.modules.order import (
    PANEL_PRIORITY_ORDER,               # tuple[str, ...]
    classify_lab_specs,                 # (specs, ...) -> (panel_groups, stand_alone)
    load_panel_definitions,             # () -> dict (@lru_cache=1)
)

# Order engine (各 simulator が直接 import)
from clinosim.modules.order.engine import (
    place_admission_orders,             # (protocol, patient_id, encounter_id, admission_time, rng, ...)
    place_daily_lab_orders,             # (protocol, encounter_id, admission_time, day_number, rng, ...)
    place_imaging_orders,               # (protocol, patient_id, encounter_id, admission_time, rng)
    enrich_medication_order,            # (order, dose_str="") -> Order
    parse_dose_string,                  # (dose_str) -> dict
    calculate_lab_result_time,          # (order_time, urgency, ...) -> datetime
    calculate_imaging_result_time,      # (order_time, urgency, ...) -> datetime
    calculate_result_time_from_state,   # (order, hospital_state, hospital_ops) -> datetime
    order_resource_type,                # (order) -> "MEDICATION" | "PROCEDURE" | "THERAPY" | "LAB" | "IMAGING" | None
    replay_order_to_state,              # (order, hospital_state, hospital_ops) -> None
)

# Treatment classifier (単一情報源 keyword 表)
from clinosim.modules.order.treatment_classifier import (
    classify_encounter_treatment,       # (display_name) -> OrderType
    classify_inpatient_supportive,      # (display_name, type_hint) -> OrderType
    classify_escalation_treatment,      # (esc_drug: object) -> OrderType
)
```

## 決定論

- **`panel_specimen_seed(parent_order_id)`** と
  **`individual_lab_seed(order_id)`** ([`clinosim/seeding.py`](../../seeding.py))
  — AD-59 per-order sub-seed。panel order は 1 検体を共有し、
  individual scalar order は各自 per-order seed。本モジュールの発注
  関数は両 helper が seed する id を持った `Order` を返すため、
  新 lab 追加は無関係な患者 stream を shift しない。
- 本モジュール専用のサブ seed offset は `ENRICHER_SEED_OFFSETS` に
  存在しない。発注構築は encounter simulator が imperative に呼び、
  per-encounter RNG を渡す。
- Panel-priority 分類は決定論的 (pin された `PANEL_PRIORITY_ORDER`
  tuple の dict lookup)。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`, `is_jp`,
  `is_us`, `normalize_probabilities`。
- `clinosim.modules.order._imaging_result_timing`,
  `_lab_result_timing`, `_order_placement_timing`,
  `_state_delay_thresholds` — 全 timing / delay scalar (Issue #637
  4-file sweep)。
- `clinosim.codes.loader._load_system` — `_code_in_data` panel
  validation (`hai/engine.py` 兄弟 pattern)。
- `clinosim.audit.registry` (`audit.py` 経由) — AD-60 audit 登録。
- `clinosim.types.encounter` — `Order`, `OrderType`, `OrderStatus`。
- `numpy`, `yaml`。

## 定数と設定

- **Panel 優先順** (`PANEL_PRIORITY_ORDER`, `panel_grouping.py`):
  `("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA", "Checkup")`。
  順序は load-bearing — HCO3 は ABG ∧ BMP 両方に属するが、ABG が
  先に現れるため classifier は ABG に割り当てる。
- **Panel YAML**: [`reference_data/lab_panel_groups.yaml`](reference_data/lab_panel_groups.yaml)
  — panel は本来「発注概念」のため `output/reference_data/` から
  ここに移動。header コメントに priority tuple が列挙されており
  import 時に cross-verify (`_validate_panel_definitions`)。
- **Timing threshold** (Issue #637 4-file sweep):
  - [`_lab_result_timing.py`](_lab_result_timing.py) — STAT vs
    routine base delay、夜勤の翌朝 deferral 挙動、urgency 乗数。
  - [`_imaging_result_timing.py`](_imaging_result_timing.py) —
    scheduling delay (order → exam) + reporting delay を分離管理。
  - [`_order_placement_timing.py`](_order_placement_timing.py) —
    encounter event からの per-order placement offset。
  - [`_state_delay_thresholds.py`](_state_delay_thresholds.py) —
    `calculate_result_time_from_state` の hospital-state 遅延。
- **Treatment classifier keyword** (`treatment_classifier.py`) —
  display 名を `MEDICATION` / `PROCEDURE` / `THERAPY` に dispatch
  する 4 keyword tuple。text-based 部分文字列 match で、英語
  encounter-YAML 名と英語 disease-YAML detail の両方をカバー。
  JP への localization は FHIR builder に意図的に deferred。

## ディレクトリ構造

```
clinosim/modules/order/
  __init__.py                        panel 3 symbol を再 export
  engine.py                          admission + 日次 + imaging 発注、結果時刻計算
  panel_grouping.py                  classify_lab_specs + load_panel_definitions + PANEL_PRIORITY_ORDER
  treatment_classifier.py            classify_{encounter,inpatient,escalation}_* keyword 表
  audit.py                           AD-60 audit plug-in (per-module) — 7-check lift_firing_proof + basedon_coverage
  _lab_result_timing.py              STAT / routine / 夜勤 定数 (Issue #637)
  _imaging_result_timing.py          scheduling + reporting delay 定数 (Issue #637)
  _order_placement_timing.py         placement offset 定数 (Issue #637)
  _state_delay_thresholds.py         hospital-state delay 定数 (Issue #637)
  reference_data/
    lab_panel_groups.yaml            panel → components + priority header
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`enricher.py` は存在しない** — 発注は encounter simulator が
imperative に呼び出す (`register_builtin_enrichers` 経由でない)。

## Enricher 配線

enricher としては該当なし — 本モジュールは imperative に呼ばれる。
ただし `audit.py` module は import 時に audit framework に
(`register_audit_module`) 登録される — 3 番目の AD-60 per-module
plug-in。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | `place_admission_orders` + `place_daily_lab_orders` + `place_imaging_orders` を呼び、`supportive[]` に対して classifier を呼ぶ。 |
| Emergency encounter | [`clinosim/simulator/emergency.py`](../../simulator/emergency.py) | ED tier で同じ発注面 + `treatment[]` に `classify_encounter_treatment` を適用。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | 日次 lab + medication 発注を配置。 |
| Unknown-condition walkthrough | [`clinosim/simulator/unknown_condition.py`](../../simulator/unknown_condition.py) | 探索 path で同 order 面。 |
| Lab pipeline | [`clinosim/simulator/lab_pipeline.py`](../../simulator/lab_pipeline.py) | `panel_specimen_seed` + `individual_lab_seed` で observation engine を sub-seed。 |
| Medication pipeline | [`clinosim/simulator/medication_pipeline.py`](../../simulator/medication_pipeline.py) | `enrich_medication_order` + `parse_dose_string` で MedicationRequest / MedicationAdministration 入力を構築。 |
| FHIR ServiceRequest builder | [`clinosim/modules/output/fhir_r4/labs/service_request.py`](../output/fhir_r4/labs/service_request.py) | panel classification と `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` 定数を消費 (`audit.py` が cross-verify)。 |

## テスト

```bash
pytest tests/unit -k "order or panel_grouping or treatment_classifier" -q
pytest tests/integration -k "order or lab_pipeline" -q
clinosim audit run -d <cohort_dir> --module order   # AD-60 axis 実行
```

`audit run --module order` が [`audit.py`](audit.py) docstring 記載の
7 `lift_firing_proof` equality check + `basedon_coverage`
clinical-axis gate を exercise する。green audit run が本モジュールの
load-bearing 検証。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
