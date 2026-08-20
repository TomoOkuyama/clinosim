# `clinosim.modules.disease` — 疾患プロトコル registry + 重症度 + acuity 定数

## 概要

疾患プロトコル registry を所有する — [`reference_data/`](reference_data/)
配下の 1 疾患 = 1 YAML を Pydantic `DiseaseProtocol` model 経由で
validate してロードし、加えて simulator が入院 / 回診 / 画像 /
発注 / 退院で参照する canonical な重症度 / acuity / 薬剤
vocabulary の定数と helper を提供する。新疾患追加は YAML 編集のみ
(engine code 変更不要)。

module 名は "disease" だが、実際には **入院 / encounter プロトコル
全般** を扱う: 内因性疾患 (肺炎、HF、MI、脳卒中、DKA…)、外傷
(手部挫滅、MVA 手骨折…)、労災 (工業熱傷、感電、高所墜落…)。
外来 / ED の短期プロトコルは兄弟 registry
[`clinosim.modules.encounter`](../encounter/README.md) 側に分離。

## Scope

- **In scope**: `DiseaseProtocol` schema + child model
  (`HpiTemplate`, `PhysicalExamSystemFindings`,
  `PhysicalExamDayFindings`, `DischargeInstructions`, `NarrativeSpec`,
  `ImagingOrderSpec`, `DailyTrajectoryEntry`)、per-disease と
  全 registry の 2 loader (共に `@lru_cache`)、条件ベース modifier +
  最低クランプ付きの重症度分布サンプリング、canonical な重症度
  category ↔ score mapping、canonical 3 acuity-tier 疾患集合
  (`EMERGENCY_PRIORITY_DISEASES`, `CRITICAL_MONITORING_DISEASES`,
  `NEURO_LOC_MONITORING_DISEASES`)、薬剤ブロック route + 期間
  validation (Issue #455 / #437 系)、chief-complaint /
  target-LOS / 部門の localization helper。
- **In scope (import 時 validation)**: 全 YAML を Pydantic
  (`extra="forbid"`) で round-trip し、追加の `_validate_drug_*`
  pass が dose ↔ route 矛盾 (fallback-relative)、無効な escalation
  `type`、長間隔 dose の duration 欠落、localised dose key の typo
  を reject する。
- **Out of scope**: シミュレーション時に protocol を読む
  physiology-state 更新ロジック
  ([`clinosim.modules.physiology`](../physiology/README.md))、
  clinical-course trajectory 選択
  ([`clinosim.modules.clinical_course`](../clinical_course/README.md))、
  外来 / ED 短期プロトコル data
  ([`clinosim.modules.encounter`](../encounter/README.md))、narrative
  templating
  ([`clinosim.modules.document.narrative`](../document/narrative/README.md))、
  疾患駆動の encounter emission ロジック
  ([`clinosim.simulator`](../../simulator/))。

## Public API

`__init__.py` は空。呼び出し側は 4 submodule から直接 import:

```python
# Schema + loaders
from clinosim.modules.disease.protocol import (
    DiseaseProtocol,
    HpiTemplate,
    PhysicalExamSystemFindings,
    PhysicalExamDayFindings,
    DischargeInstructions,
    NarrativeSpec,
    ImagingOrderSpec,
    DailyTrajectoryEntry,
    load_disease_protocol,        # (disease_id) -> DiseaseProtocol  (lru_cache=64)
    load_all_disease_protocols,   # () -> dict[str, DiseaseProtocol]  (lru_cache=1)
    # 薬剤 vocabulary helper
    DRUG_BLOCK_ROUTE_FALLBACKS,
    ROUTE_DOSE_TOKENS,
    dose_route_tokens,
    dose_contradicts_fallback,
    dose_names_long_interval,
)

# 重症度モデル
from clinosim.modules.disease.severity import (
    SEVERITY_CATEGORIES,          # ("mild", "moderate", "severe")
    SEVERITY_SCORE_RANGES,        # canonical 半開範囲
    category_from_score,          # (score) -> "mild"|"moderate"|"severe"
    sample_severity_category,     # (dist, modifiers, minimum, person, rng)
    sample_severity,              # (protocol, person, rng) -> (category, score)
    EVALUABLE_CONDITIONS,
    RESERVED_INTRINSIC_CONDITIONS,
    KNOWN_MODIFIER_CONDITIONS,
)

# Acuity 別 canonical 疾患集合
from clinosim.modules.disease.acuity import (
    EMERGENCY_PRIORITY_DISEASES,      # Encounter.priority = "EM"
    CRITICAL_MONITORING_DISEASES,     # q1-2h vitals
    NEURO_LOC_MONITORING_DISEASES,    # LOC (AVPU) 入院 day 0-2
)

# Localization (国 → YAML キー、chief complaint、部門)
from clinosim.modules.disease.localization import (
    _country_to_yaml_key,
    target_los_config,
    _disease_chief_complaint,
    _disease_chief_complaint_ja,
    _disease_to_department,
)
```

`load_disease_protocol` は cache 済み同一 instance を返す (read-only
扱い)。`load_all_disease_protocols` は one-shot 便利関数。いずれも
schema / validation 失敗時に `ValueError` / Pydantic
`ValidationError` を raise。

## 決定論

- 重症度サンプリング (`sample_severity_category`,
  `sample_severity`) は `rng` に対して決定論的。seed 導出は caller
  ([`clinosim.modules.population`](../population/README.md) の入院
  gate + [`clinosim.modules.patient.activator`](../patient/README.md))
  が握る。本モジュールは enricher ではなく必要な consumer が直接
  import する形態のため、サブ seed オフセットは未登録。
- その他 (loader / validator / 薬剤 vocabulary helper / acuity
  集合 / localization) はすべて pure。

## 依存

- `pydantic` — schema + `extra="forbid"` validation。
- `yaml` — YAML パーサ。
- `numpy` — 重症度サンプリング用 `np.random.Generator`。
- `clinosim.modules._shared` — `normalize_probabilities`
  (`fallback="raise"`)。
- `clinosim.simulator` には依存しない (厳格な one-way 境界 —
  simulator が disease を読むだけで逆流しない)。

## 定数と設定

- **疾患 YAML registry**: [`reference_data/`](reference_data/) —
  現在 32 file (1 疾患 = 1 file、filename = disease_id + `.yaml`)。
  各 file は国別疫学、重症度分布 + modifier、提示症状、physiology
  impact、日次 trajectory archetype、合併症、発注プロトコル
  (labs / vitals / imaging / medications)、鑑別 + 尤度比 +
  コード進展、国 × 役割別薬剤プロトコル (`first_line`,
  `alternative_penicillin_allergy`, `mrsa_coverage`, `escalation`,
  `post_op`, `discharge_oral`, `hyperkalemia_management`,
  `alternative_beta_blocker_contraindicated` …)、target LOS +
  退院 benchmark を持つ。
- **重症度 canonical モデル** (`severity.py`):
  - `SEVERITY_CATEGORIES = ("mild", "moderate", "severe")`。
  - `SEVERITY_SCORE_RANGES = {"mild": (0.0, 0.3), "moderate":
    (0.3, 0.7), "severe": (0.7, 1.0)}` — 半開 (`severe` 上限のみ
    包含)。`category_from_score` は完全整合しており、範囲内の
    uniform draw は同 category を再導出する。
  - `EVALUABLE_CONDITIONS` — `person` に対して評価可能な modifier
    条件 (ICD prefix 集合 + 年齢閾値集合); `RESERVED_INTRINSIC_CONDITIONS`
    — caller 側に評価を委ねる予約 token (例
    `is_covid_variant_delta`); `KNOWN_MODIFIER_CONDITIONS =
    EVALUABLE_CONDITIONS | RESERVED_INTRINSIC_CONDITIONS`。YAML
    modifier key がこの union 外なら load 時に raise。
- **Acuity 別 canonical 集合** (`acuity.py`, Issue #563):
  重複を含む 3 `frozenset[str]` — 疾患 ID の集合参加は load-bearing
  な臨床事実。追加 / 削除は data-quality PR (refactor ではない)。
  以前の `subdural_hematoma` inconsistency
  (`EMERGENCY_PRIORITY_DISEASES` に居るが
  `CRITICAL_MONITORING_DISEASES` に居ない) が Issue #563 で捕捉された
  drift。
- **薬剤 vocabulary helper** (`protocol.py`, Issue #455 系):
  - `DRUG_BLOCK_ROUTE_FALLBACKS = {"discharge_oral": "PO",
    "escalation": "IV"}` — entry で `route` が欠落したときに reader
    が default route を代入する 2 block。代入 reader が無い block
    (`first_line`, `post_op`, `alternative_penicillin_allergy`,
    `mrsa_coverage` …) は build 破壊を避けるため意図的に validate
    しない。
  - `ROUTE_DOSE_TOKENS` — fallback check が free-text `dose` 内で
    tokenize する route 略記全て (`PO`, `IV`, `SC`, `IM`, `SL`,
    `PR`, `NG`, `TD`, `INH`, `NEB`)。word-boundary regex
    `_ROUTE_DOSE_RE` は load-bearing — 部分文字列 match は `PR` が
    `PRN` 内、`NG` が `remaining` 内で false-positive を起こす。
  - `dose_contradicts_fallback(dose, fallback)` — dose が route を
    名指ししていて、かつ fallback がその集合に含まれないとき True を
    返す。
  - 長間隔 helper `dose_names_long_interval` — `q<N><unit>` 系
    パターンで閾値以上を検出、`_validate_drug_block_duration_days`
    が消費する。

## ディレクトリ構造

```
clinosim/modules/disease/
  __init__.py                     空
  protocol.py                     DiseaseProtocol + child model + loader + 薬剤 validator
  severity.py                     重症度 category / range / sampler / modifier 評価
  acuity.py                       EMERGENCY_PRIORITY / CRITICAL_MONITORING / NEURO_LOC 集合
  localization.py                 国 → YAML key + chief complaint + 部門 + target_los
  reference_data/
    <disease_id>.yaml             32 file (疾患 1 file)
  SPEC.md                         拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` は存在しない**。enricher ではない。

## Enricher 配線

該当なし — 本モジュールは data + helper 層であり enricher ではない。
`register_builtin_enrichers` に登録なく、`ENRICHER_SEED_OFFSETS`
にも seed 未登録。各 consumer が必要なものを直接 import する。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) | run あたり 1 回 `load_all_disease_protocols()` を load。 |
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | 入院発注 / 日次 trajectory / 薬剤プロトコル / target LOS のため `DiseaseProtocol` を read。acuity 別集合を参照して `Encounter.priority` と vitals サンプリング頻度を gate。 |
| Emergency / outpatient / daily loop | [`clinosim/simulator/{emergency,outpatient,daily_loop,vitals_pipeline}.py`](../../simulator/) | 各 encounter tier で同 read pattern。 |
| Discharge gate + rx | [`clinosim/simulator/{discharge_gate,discharge_rx}.py`](../../simulator/) | `DiseaseProtocol.discharge_criteria` + `discharge_oral` 薬剤 block を使用。 |
| Simulator helper | [`clinosim/simulator/helpers.py`](../../simulator/helpers.py) | `disease.localization` helper を deprecation 期間中 1 cycle だけ再 export (Issue #544)。 |
| Narrative | [`clinosim/modules/document/narrative/{passes,template_generator}.py`](../document/narrative/) | `DiseaseProtocol.narrative` template + `HpiTemplate` + `DischargeInstructions` を read。 |

## テスト

```bash
pytest tests/unit -k disease -q
```

個別ファイル:

- [`tests/unit/test_disease_yaml_drug_code_consistency.py`](../../../tests/unit/test_disease_yaml_drug_code_consistency.py)
  — 全薬剤 entry の code が `clinosim/codes/` で解決。
- [`tests/unit/test_disease_yaml_key_coverage.py`](../../../tests/unit/test_disease_yaml_key_coverage.py)
  — 32 YAML 全体の canonical key coverage。
- [`tests/unit/test_disease_protocol_extra_forbid.py`](../../../tests/unit/test_disease_protocol_extra_forbid.py)
  — Pydantic `extra="forbid"` の未知 key guard。
- [`tests/unit/test_cli_test_disease_format.py`](../../../tests/unit/test_cli_test_disease_format.py)
  — CLI disease-format helper。
- [`tests/unit/modules/test_disease_acuity_sets.py`](../../../tests/unit/modules/test_disease_acuity_sets.py)
  — 3 acuity 集合の consistency (Issue #563 guard)。
- [`tests/unit/modules/disease/`](../../../tests/unit/modules/disease/)
  — module-scoped unit test (重症度 sampler、薬剤 validator、
  localization helper)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
