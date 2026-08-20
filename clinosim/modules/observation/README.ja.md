# `clinosim.modules.observation` — lab 結果、看護 flowsheet、microbiology

## 概要

観測される臨床データの emission 層で 3 関連責務を持つ:

1. **Lab 値 engine** (`engine.py`) — 検査 canonical 命名 + panel 展開
   (`lab_aliases.yaml`, `lab_panels.yaml`)、性別帯 reference range、
   physiologic clamp、noise / variability 注入、精度 rounding、
   reference-range flag 付与。`generate_lab_result` は全 simulator
   が lab `OrderResult` を書く単一 emission point。
2. **看護 flowsheet 観測** (`nursing.py` + `nursing_enricher.py`)
   — vital + ADL データからの NEWS2 / GCS / Braden 褥瘡 / Morse
   転倒リスクスコア計算と、`simulator/enrichers.py` に `name="nursing"`
   で登録される POST_RECORDS `enrich_nursing` enricher。
   ([`clinosim.modules.nursing`](../nursing/README.md) が所有する
   `nursing_assignment` — primary_nurse_id 割当 — とは別。)
3. **Microbiology culture + 感受性** (`microbiology.py`) — 決定論的
   culture organism サンプリング、antibiogram からの S/I/R
   susceptibility 生成、`hai_event_id` による HAI event backref
   (PR3b-2 chain)。

companion threshold file (`fluid_balance.py`, `oxygenation.py`,
`pre_analytical.py`, `vitals_thresholds.py`,
`_nursing_score_thresholds.py`, `_variability_defaults.py`) が
previously-inline scalar を全て lift し、単一 edit が全経路に伝播する。

## Scope

- **In scope**: `canonical_lab_name` + `lab_panel_components` (lab
  alias 解決 + panel 展開の単一 edit point)、`generate_lab_result`
  (baseline + noise + clamp + rounding + reference-range flag)、
  `apply_realistic_variability`, `clamp_to_physiologic_limits`,
  `round_to_precision`, `determine_flag`,
  `_generate_qualitative_result`, `_reference_ranges_by_sex`、
  `get_lab_unit`、`compute_news2` / `compute_gcs` / `compute_braden`
  / `compute_morse_fall_risk` (看護スコア)、`enrich_nursing`
  POST_RECORDS enricher (各 vital record に NEWS2/GCS を埋め、
  日次 Braden/Morse を生成)、`has_microbiology(disease_id)` +
  `generate_microbiology(...)` + `antibiotic_loinc_lookup()`、
  臨床引用付きの 4 threshold sub-module。
- **Out of scope**: lab 値を駆動する physiology state
  ([`physiology`](../physiology/README.md))、order placement
  ([`order`](../order/README.md))、vitals / imaging 導出
  ([`physiology`](../physiology/README.md) +
  `simulator/vitals_pipeline.py`)、FHIR emission
  ([`output`](../output/README.md))、microbiology の抗菌薬レジメン
  選定 ([`antibiotic`](../antibiotic/README.md))。

## Public API

`__init__.py` は空。呼び出し側は 4 submodule から直接 import:

```python
# Lab engine
from clinosim.modules.observation.engine import (
    canonical_lab_name,                  # (name) -> canonical str
    lab_panel_components,                # (panel_name) -> list[str]
    get_lab_unit,                        # (lab_name) -> unit str
    clamp_to_physiologic_limits,         # (lab_name, value) -> float
    apply_realistic_variability,         # (lab_name, value, rng) -> float
    round_to_precision,                  # (lab_name, value) -> float
    generate_lab_result,                 # (lab_name, state, patient, rng, **flags) -> OrderResult
    determine_flag,                      # (lab_name, value, sex, country) -> "L" | "H" | ""
)

# 看護 flowsheet
from clinosim.modules.observation.nursing import (
    compute_news2,                       # (vs: dict) -> int
    compute_gcs,                         # (consciousness_level, perfusion_status, rng) -> int
    compute_braden,                      # (adl, consciousness_level, volume_status, rng) -> dict
    compute_morse_fall_risk,             # (…) -> dict
)
from clinosim.modules.observation.nursing_enricher import enrich_nursing

# Microbiology
from clinosim.modules.observation.microbiology import (
    has_microbiology,                    # (disease_id) -> bool
    generate_microbiology,               # (…) -> list[MicrobiologyResult]
    antibiotic_loinc_lookup,             # () -> dict[antibiotic_key, LOINC code]
)
```

## 決定論

- サブ seed オフセット `0x4E55` (`"NU"`) は
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["nursing"]` に登録済み。本モジュールの
  `enrich_nursing` (POST_RECORDS order=20、`name="nursing"` で登録)
  と [`clinosim.modules.nursing`](../nursing/README.md) の
  primary-nurse enricher (POST_ENCOUNTER order=94、`name="nursing_assignment"`)
  で共有される。両者は異なる stage で動くため、共有 offset は衝突しない。
- Microbiology サンプリングは **encounter 単位**の sub-seed
  (`hai_event_id` / encounter から派生) を使う。`generate_microbiology`
  に新 organism を追加しても無関係な患者 stream を shift しない
  (PR3b-2 pattern)。
- Lab 結果 variability は **per-order** RNG
  (`simulator/seeding.py:panel_specimen_seed` /
  `individual_lab_seed` — AD-59) で呼ばれ、患者 master RNG は使わない。
  YAML edit で新 analyte を追加しても無関係な患者は byte-clean。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`, `set_attr_or_key`,
  `is_jp`, `is_us`, `normalize_probabilities`。
- `clinosim.modules.observation.{fluid_balance,oxygenation,pre_analytical,vitals_thresholds,_nursing_score_thresholds,_variability_defaults}`
  — 上記 3 engine が使う全 clamp / noise / trigger 閾値
  (Issue #561 + #637 sweep)。
- `clinosim.locale.loader` — 性別帯 reference-range YAML
  (`reference_range_lab.yaml`) と lab code mapping
  (`code_mapping_lab.yaml`)。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.types.encounter` — `OrderResult`, `MicrobiologyResult`。
- `clinosim.types.clinical` — `PhysiologicalState` (lab 導出の
  入力)。
- `yaml`, `numpy`。

## 定数と設定

- **Reference data** ([`reference_data/`](reference_data/)):
  - `lab_aliases.yaml` — canonical lab-name 解決
    (`canonical_lab_name`)。
  - `lab_panels.yaml` — panel → component lab list
    (`lab_panel_components`)。
  - `microbiology.yaml` — culture organism カタログ + susceptibility
    分布 + `antibiotic_loinc_lookup` source。import 時に
    `_validate_microbiology` が `HAI_TYPES` / `ANTIBIOTIC_DRUGS` /
    SNOMED / LOINC canonical に対する 7 cross-reference で検証
    (PR-A pattern)。
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
    `inpatient.py` の 2 site から lift された specimen-rejection /
    hemolysis / technician-error rate。単一 edit が両経路に伝播する。
  - [`vitals_thresholds.py`](vitals_thresholds.py) — vital 別
    physiologic min / max clamp と reference band。
  - [`_nursing_score_thresholds.py`](_nursing_score_thresholds.py)
    — compute_* 関数のスコア band 境界。
  - [`_variability_defaults.py`](_variability_defaults.py) —
    reference YAML に該当 entry が無いときの analyte 別 default
    variability SD。

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
  vitals_thresholds.py               vital 別 clamp + band
  _nursing_score_thresholds.py       スコア band 境界 (Issue #637)
  _variability_defaults.py           default variability SD (Issue #637)
  reference_data/
    lab_aliases.yaml                 canonical lab-name alias
    lab_panels.yaml                  panel → components
    microbiology.yaml                organism + susceptibility カタログ
    nursing_scores.yaml              NEWS2 / GCS / Braden / Morse band
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`audit.py` は存在しない** — 検証は import 時
(`_validate_microbiology`) と下記 test で担保。

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
で登録:

- **`nursing`** — `stage=POST_RECORDS`, `order=20`, always-on。entry
  は `clinosim.modules.observation.nursing_enricher.enrich_nursing`。
  各 vital record に NEWS2 + GCS を埋め、日次 Braden + Morse を生成。

[`clinosim.modules.nursing`](../nursing/README.md) が登録する
`nursing_assignment` enricher (POST_ENCOUNTER order=94) は別 enricher。
両者は `0x4E55` sub-seed offset を共有するが、異なる stage で動くため
衝突しない。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:148`](../../simulator/enrichers.py) | POST_RECORDS `nursing` 登録。 |
| Lab pipeline | [`clinosim/simulator/lab_pipeline.py`](../../simulator/lab_pipeline.py) | 発注 lab ごとに `generate_lab_result` を呼び出す。 |
| Vitals pipeline | [`clinosim/simulator/vitals_pipeline.py`](../../simulator/vitals_pipeline.py) | `fluid_balance.py` + `oxygenation.py` 閾値を消費。 |
| Inpatient / outpatient / emergency / daily_loop / unknown_condition | [`clinosim/simulator/*.py`](../../simulator/) | lab canonicalisation、看護 compute_*、microbiology helper を消費。 |
| Order module | [`clinosim/modules/order/panel_grouping.py`](../order/panel_grouping.py) | `lab_panel_components` を消費して panel order を展開。 |
| HAI lab lift | [`clinosim/modules/hai/lab_lift.py`](../hai/lab_lift.py) | `enrich_nursing` 後の lab 結果 WBC / CRP を read。 |
| Monitoring enricher | [`clinosim/modules/monitoring/enricher.py`](../monitoring/enricher.py) | 慢性薬 monitoring の lab result flag を消費。 |
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
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
