# `clinosim.modules.observation` — lab 結果、看護 flowsheet、microbiology

## 概要

観測される臨床データの emission 層で 3 関連責務を持つ:

1. **Lab 値 engine** (`engine.py`) — 検査 canonical 命名 + panel 展開
   (`lab_aliases.yaml`, `lab_panels.yaml`)、性別帯 reference range、
   physiologic clamp、noise / variability 注入、精度 rounding、
   reference-range flag 付与。`generate_lab_result` は各 simulator
   が lab `OrderResult` を組み立てる前に呼ぶ共通の値生成ステップ
   (variability + rounding、qualitative test は categorical draw)。
   H / L / critical flag は `determine_flag` が付与。
2. **看護 flowsheet 観測** (`nursing.py` + `nursing_enricher.py`)
   — vital + ADL データからの NEWS2 / GCS / Braden 褥瘡 / Morse
   転倒リスクスコア計算と、`simulator/enrichers.py` に `name="nursing"`
   で登録される POST_RECORDS `enrich_nursing` enricher。
   ([`clinosim.modules.nursing`](../nursing/README.ja.md) が所有する
   `nursing_assignment` — primary_nurse_id 割当 — とは別。)
3. **Microbiology culture + 感受性** (`microbiology.py`) — 決定論的
   culture organism サンプリング、antibiogram からの S/I/R
   susceptibility 生成。(HAI 由来 culture の
   `MicrobiologyResult.hai_event_id` backref は本モジュールではなく
   [`clinosim.modules.hai`](../hai/README.ja.md) が設定。)

companion threshold file (`fluid_balance.py`, `oxygenation.py`,
`pre_analytical.py`, `vitals_thresholds.py`,
`_nursing_score_thresholds.py`, `_variability_defaults.py`) が
previously-inline scalar を全て lift し、単一 edit が全経路に伝播する。

## Scope

- **In scope**: `canonical_lab_name` + `lab_panel_components` (lab
  alias 解決 + panel 展開の単一 edit point)、`generate_lab_result`
  (noise + clamp + rounding、qualitative test は categorical 結果)、
  `is_qualitative_test`、`apply_realistic_variability`, `clamp_to_physiologic_limits`,
  `round_to_precision`, `determine_flag`,
  `_generate_qualitative_result`, `_reference_ranges_by_sex`、
  `get_lab_unit`、`compute_news2` / `compute_gcs` / `compute_braden`
  / `compute_morse_fall_risk` (看護スコア)、`enrich_nursing`
  POST_RECORDS enricher (各 vital record に NEWS2/GCS を埋め、
  日次 Braden/Morse を生成)、`has_microbiology(disease_id)` +
  `generate_microbiology(...)` + `antibiotic_loinc_lookup()`、
  臨床引用付きの threshold sub-module 群。
- **Out of scope**: lab 値を駆動する physiology state
  ([`physiology`](../physiology/README.ja.md))、order placement
  ([`order`](../order/README.ja.md))、vitals / imaging 導出
  ([`physiology`](../physiology/README.ja.md) +
  `simulator/vitals_pipeline.py`)、FHIR emission
  ([`output`](../output/README.ja.md))、microbiology の抗菌薬レジメン
  選定 ([`antibiotic`](../antibiotic/README.ja.md))。

## Public API

`__init__.py` は空。呼び出し側は submodule から直接 import:

```python
# Lab engine
from clinosim.modules.observation.engine import (
    canonical_lab_name,                  # (name) -> canonical str
    lab_panel_components,                # (panel_name) -> list[str]
    get_lab_unit,                        # (lab_name) -> unit str
    clamp_to_physiologic_limits,         # (lab_name, value) -> float
    apply_realistic_variability,         # (lab_name, true_value, rng) -> float
    round_to_precision,                  # (lab_name, value) -> float
    is_qualitative_test,                 # (lab_name) -> bool
    generate_lab_result,                 # (lab_name, true_value, rng) -> float | str
    determine_flag,                      # (lab_name, value, sex="F", country="US") -> "L" | "H" | "critical" | None
)

# 看護 flowsheet
from clinosim.modules.observation.nursing import (
    compute_news2,                       # (vs: dict) -> int
    compute_gcs,                         # (consciousness_level, perfusion_status, rng) -> int
    compute_braden,                      # (adl, consciousness_level, volume_status, rng) -> dict
    compute_morse_fall_risk,             # (age, adl, consciousness_level, has_iv, rng) -> (score, risk_level)
)
from clinosim.modules.observation.nursing_enricher import enrich_nursing

# Microbiology
from clinosim.modules.observation.microbiology import (
    has_microbiology,                    # (disease_id) -> bool
    generate_microbiology,               # (disease_id, collected_datetime, encounter_id, master_seed) -> list[MicrobiologyResult]
    antibiotic_loinc_lookup,             # () -> dict[antibiotic_key, LOINC code]
)
```

## 決定論

- サブ seed オフセット `0x4E55` (`"NU"`) は
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["nursing"]` に登録済み。本モジュールの
  `enrich_nursing` (POST_RECORDS order=20、`name="nursing"` で登録)
  と [`clinosim.modules.nursing`](../nursing/README.ja.md) の
  primary-nurse enricher (POST_ENCOUNTER order=94、`name="nursing_assignment"`)
  で共有される。`enrich_nursing` は `patient_id`、primary-nurse enricher は
  `encounter_id` を key にするため、共有 offset は衝突しない。
- Microbiology サンプリングは **encounter 単位**の sub-seed
  `derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["microbiology"]
  (770_077), encounter_id)` を使う。`generate_microbiology` に新
  organism を追加しても無関係な患者 stream を shift しない。
- Lab 結果 variability は **per-order** RNG
  (`clinosim/seeding.py:panel_specimen_seed` /
  `individual_lab_seed` — AD-59) で呼ばれ、患者 master RNG は使わない。
  YAML edit で新 analyte を追加しても無関係な患者は byte-clean。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`, `set_attr_or_key`
  (看護 enricher)、`normalize_probabilities` (microbiology)。
- `clinosim.modules.observation.{fluid_balance,oxygenation,pre_analytical,vitals_thresholds,_nursing_score_thresholds,_variability_defaults}`
  — 上記 3 engine が使う全 clamp / noise / trigger 閾値
  (Issue #561 + #637 sweep)。
- `clinosim.locale.loader` — 性別帯 reference-range YAML
  (`reference_range_lab.yaml`) を読む `load_reference_ranges`。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types` — `MicrobiologyResult`, `SusceptibilityResult`、
  `clinosim.types.encounter` — `NursingRiskAssessment`。
- `yaml`, `numpy`。

## 定数と設定

- **Reference data** ([`reference_data/`](reference_data/)):
  - `lab_aliases.yaml` — canonical lab-name 解決
    (`canonical_lab_name`)。
  - `lab_panels.yaml` — panel → component lab list
    (`lab_panel_components`)。
  - `microbiology.yaml` — culture organism カタログ + susceptibility
    分布 + `antibiotic_loinc_lookup` source。load 時に
    `_validate_microbiology` が 7 項目を検証: antibiogram →
    `antibiotics` key、disease organism → `organisms` key、culture
    specimen → `specimens` key、organism / specimen SNOMED と
    specimen / antibiotic LOINC が非空文字列であること。
  - `nursing_scores.yaml` — NEWS2 / GCS / Braden / Morse の
    authoritative 公表 instrument band (`_scores` が load し
    `compute_*` が消費)。
- **Threshold sub-module**:
  - [`fluid_balance.py`](fluid_balance.py) (Issue #561) — 日次
    intake / output balance 閾値: aggressive IV / maintenance /
    restrictive regimen の mean + SD、urine-output サンプリングの
    anuria floor。
  - [`oxygenation.py`](oxygenation.py) (Issue #561) — 酸素療法
    escalation の SpO₂ トリガー
    (`SPO2_HYPOXEMIA_TRIGGER = 92 %`、`SPO2_SEVERE_HYPOXEMIA = 88 %`)。
  - [`pre_analytical.py`](pre_analytical.py) (Issue #561) —
    specimen-rejection / hemolysis / technician-error rate。
    `simulator/lab_pipeline.py` が消費。
  - [`vitals_thresholds.py`](vitals_thresholds.py) (Issue #561) —
    発熱判定と発熱時再検 cadence (`FEVER_THRESHOLD_C = 38.0`、
    `HIGH_FEVER_RECHECK_C = 38.5`、`FEBRILE_RECHECK_PROB`、
    `FEBRILE_RECHECK_WINDOW_MIN`)。
  - [`_nursing_score_thresholds.py`](_nursing_score_thresholds.py)
    — compute_* 関数のスコア band 境界。
  - [`_variability_defaults.py`](_variability_defaults.py) —
    lab 別 CV が無い analyte 用の fallback biological / analytical CV
    (`DEFAULT_BIOLOGICAL_CV`, `DEFAULT_ANALYTICAL_CV`) と、qualitative
    test の categorical 結果分布。

## ディレクトリ構造

```
clinosim/modules/observation/
  __init__.py                        空
  engine.py                          lab canonicalisation + result 生成
  nursing.py                         NEWS2 / GCS / Braden / Morse compute_* 関数
  nursing_enricher.py                POST_RECORDS enricher (enrich_nursing)
  microbiology.py                    culture + susceptibility + antibiogram
  fluid_balance.py                   IV regimen + urine-output 閾値 (Issue #561)
  oxygenation.py                     SpO₂ escalation trigger (Issue #561)
  pre_analytical.py                  specimen error rate (Issue #561)
  vitals_thresholds.py               発熱 / 再検閾値 (Issue #561)
  _nursing_score_thresholds.py       スコア band 境界 (Issue #637)
  _variability_defaults.py           default CV + qualitative 分布 (Issue #637)
  reference_data/
    lab_aliases.yaml                 canonical lab-name alias
    lab_panels.yaml                  panel → components
    microbiology.yaml                organism + susceptibility カタログ
    nursing_scores.yaml              NEWS2 / GCS / Braden / Morse band
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`audit.py` は存在しない** — 検証は load 時
(`_validate_microbiology`) と下記 test で担保。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
で登録:

- **`nursing`** — `stage=POST_RECORDS`, `order=20`, always-on。entry
  は `clinosim.modules.observation.nursing_enricher.enrich_nursing`。
  各 vital record に NEWS2 + GCS を埋め、日次 Braden + Morse を生成。

[`clinosim.modules.nursing`](../nursing/README.ja.md) が登録する
`nursing_assignment` enricher (POST_ENCOUNTER order=94) は別 enricher。
両者は `0x4E55` sub-seed offset を共有するが、異なる id (`patient_id` /
`encounter_id`) を key にし異なる stage で動くため衝突しない。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py:228`](../../simulator/enrichers.py) | POST_RECORDS `nursing` 登録。 |
| Lab pipeline | [`clinosim/simulator/lab_pipeline.py`](../../simulator/lab_pipeline.py) | 発注 lab ごとに `generate_lab_result` を呼び出す。 |
| Vitals pipeline | [`clinosim/simulator/vitals_pipeline.py`](../../simulator/vitals_pipeline.py) | `fluid_balance.py` + `oxygenation.py` 閾値を消費。 |
| Inpatient / outpatient / emergency / daily_loop / unknown_condition | [`clinosim/simulator/*.py`](../../simulator/) | lab canonicalisation / 結果生成を消費。`inpatient.py` が `generate_microbiology` を呼ぶ。 |
| Order module | [`clinosim/modules/order/panel_grouping.py`](../order/panel_grouping.py) | `lab_panel_groups.yaml` component を `lab_panel_components` と load 時に cross-validate (Layer 6b)。 |
| HAI lab lift | [`clinosim/modules/hai/lab_lift.py`](../hai/lab_lift.py) | lift した WBC / CRP 値を `determine_flag` + `round_to_precision` で再 flag / 再 rounding。 |
| Monitoring enricher | [`clinosim/modules/monitoring/enricher.py`](../monitoring/enricher.py) | 注入 monitoring lab に `canonical_lab_name`, `generate_lab_result`, `get_lab_unit`, `determine_flag` を使用。 |
| Antibiotic module | [`clinosim/modules/antibiotic/__init__.py`](../antibiotic/__init__.py) | regimen coding のため `antibiotic_loinc_lookup` を消費。 |

## テスト

```bash
pytest tests/unit -k "observation or nursing or microbiology" -q
```

Coverage cluster: 複数 test file が lab flag rule、看護スコア、
microbiology YAML validation、pre-analytical error rate を exercise。
`tests/unit -k` で上記モジュール名を検索すると個別 file が見つかる。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
