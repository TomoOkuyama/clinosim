# `clinosim.modules.clinical_course` — trajectory archetype + 日次 directive engine

## 概要

日 scale の臨床 trajectory を所有する: 入院時に disease YAML の
`course_archetypes` (例 `smooth_recovery`, `gradual_deterioration`,
`sudden_deterioration`, `treatment_resistant`) から 1 つを選出し、
[`clinosim.modules.physiology`](../physiology/README.ja.md) が state
vector に適用する日次 `StateChangeDirective` を評価し、疾患スコープの
リスク条件による合併症を評価し、診断有効度の feedback で trajectory
を補正する。`physiology` が「現時点 state の意味」を決めるのに対し、
`clinical_course` は「翌日以降 state をどう動かすか」を決める。

## Scope

- **In scope**: `select_archetype` (YAML archetype 確率 — または
  built-in fallback 表 — + 重症度 tier multiplier + per-disease
  `archetype_modifiers` の患者リスク調整、すべて
  `normalize_probabilities(fallback="raise")` を通して正規化);
  `get_daily_directive` (年齢による速度 / 時間伸縮、
  treatment-sensitivity による回復スケール、免疫反応性による
  amplitude modulation、任意の日次 noise を伴う trajectory 補間);
  `evaluate_complications` (合併症ごとの onset window、parent cascade、
  日次確率、`risk_factors` multiplier。条件は `_evaluate_risk_condition`
  が `_complication_risk_conditions.py` の語彙 — 年齢 / 性別 / 重症度 /
  不動 / state 変数閾値 / ICD alias / stay context 条件 — で解決、
  Issue #2093); `compute_diagnosis_effectiveness` +
  `apply_diagnosis_modifier` (診断駆動の補正を trajectory に戻す);
  `natural_recovery_directive` (archetype directive に毎日加算する
  小さな自然回復 directive); disease YAML の `course_archetypes` /
  `archetype_modifiers` / `complications[].risk_factors` に対する
  load 時 validator。
- **Out of scope**: state vector 意味論 + coupling
  ([`clinosim.modules.physiology`](../physiology/README.ja.md))、disease
  YAML schema 本体
  ([`clinosim.modules.disease`](../disease/README.ja.md))、encounter
  timeline ([`clinosim.modules.encounter`](../encounter/README.ja.md))、
  日次 loop mechanics
  ([`clinosim.simulator.daily_loop`](../../simulator/daily_loop.py))。

## Public API

`__init__.py` は空。呼び出し側は `engine.py` から直接 import:

```python
from clinosim.modules.clinical_course.engine import (
    select_archetype,                # (severity, profile, rng, protocol_archetypes=None, protocol_modifiers=None, patient=None) -> archetype_name
    get_daily_directive,             # (archetype_name, day, profile, protocol_archetypes=None, age=70, rng=None) -> StateChangeDirective
    evaluate_complications,          # (day, state, patient, complications, active_complications, rng, severity="moderate", context=None) -> list[dict]
    compute_diagnosis_effectiveness, # (working_diagnosis, ground_truth_disease, diagnosis_confidence, day, diagnostic_difficulty=0.3) -> float
    apply_diagnosis_modifier,        # (directive, effectiveness, current_volume=0.0, current_ph=0.0) -> StateChangeDirective
    natural_recovery_directive,      # (day, disease_id, severity, profile, treatment_effectiveness=1.0) -> StateChangeDirective
    validate_complication_risk_factors,  # (disease_id, complications) -> None — 語彙の fail-loud check
    is_supported_risk_condition,     # (condition) -> bool
)
from clinosim.modules.clinical_course._complication_risk_conditions import (
    ComplicationContext,             # context risk factor 用の stay context (薬剤 / device / 処置)
    DRUG_CLASSES,
)
```

## 決定論

- `ENRICHER_SEED_OFFSETS` にサブ seed 未登録。全 entry は caller が
  渡す `rng` に対して pure。encounter simulator (`inpatient.py`) が
  呼び出し前に per-encounter サブ RNG を導出する。
- Archetype 選出は `rng.choice(names, p=weights)` を
  `normalize_probabilities(fallback="raise")` 経由で使う — 総和 0 の
  weight は silent bias にならず raise する。
- 日次 directive 補間は `rng` が `None` のとき
  `(archetype, day, age, profile)` に対して決定論的。caller が `rng` を
  渡すと (daily loop は常に渡す)、trajectory 変数ごとに比例 noise と
  ~10% の "bump day" 摂動を引く。`TRAJECTORY_STATE_VARS` の反復順序は
  RNG 再現性に load-bearing。
- `evaluate_complications` は適格 (未 active・onset window 内・parent
  成立) な合併症ごとに `rng.random()` を 1 回引く。

## 依存

- `clinosim.modules._shared` — `normalize_probabilities`
  (`fallback="raise"`)。
- `clinosim.modules.clinical_course._archetype_modifiers` —
  archetype / 重症度別 multiplier 定数 (Issue #637 refactor)。
- `clinosim.modules.clinical_course._clinical_course_thresholds` —
  `_archetype_modifiers.py` に含まれない残余 threshold
  (Issue #637 refactor)。
- `clinosim.modules.clinical_course._complication_risk_conditions` —
  合併症 risk factor 語彙 + `ComplicationContext` (Issue #2093)。
- `clinosim.modules.disease.severity` — `EVALUABLE_CONDITIONS` /
  `_evaluate_condition` (患者レベル risk factor 語彙)。
- `clinosim.modules.physiology.engine` — `canonical_state_vars`。
- `clinosim.types.clinical` — `StateChangeDirective`。
- `clinosim.types.patient` — `PatientPhysiologicalProfile`。
- `numpy` — `np.random.Generator`; `yaml`。

## 定数と設定

- **Fallback archetype 表**
  ([`reference_data/fallback_archetypes.yaml`](reference_data/fallback_archetypes.yaml)、
  `engine._FALLBACK_TRAJECTORIES` / `_FALLBACK_PROBABILITIES` に load):
  6 archetype (`smooth_recovery` 0.55、`dip_then_recovery` 0.20、
  `plateau_then_recovery` 0.10、`treatment_resistant` 0.08、
  `gradual_deterioration` 0.05、`sudden_deterioration` 0.02) — disease
  YAML が `course_archetypes` を持たないときの baseline 確率と
  trajectory の単一情報源。重症度 multiplier logic は baseline をここから
  引き、inline 再入力しない — fallback dict 再調整時の drift risk
  排除。
- **Archetype-shape modifier** ([`_archetype_modifiers.py`](_archetype_modifiers.py)、
  Issue #637):
  - `SEVERE_{GRADUAL,SUDDEN}_DETERIORATION_MULT`,
    `SEVERE_SMOOTH_RECOVERY_MULT`,
    `MILD_{SMOOTH_RECOVERY,GRADUAL_DETERIORATION,SUDDEN_DETERIORATION}_MULT`
    — fallback baseline (もしくは YAML 供給 baseline) の上に適用する
    severity tier multiplier。
  - `AGE_SPEED_FACTOR_BANDS`, `AGE_SPEED_FACTORS` — 年齢帯別
    回復速度係数。
  - `AGED_DETERIORATION_AMPLIFIER_BASE` — 高齢者の deterioration
    amplifier baseline。
  - `IMMUNE_REACTIVITY_SCALE` — inflammation amplitude の除数。
  - `TRAJECTORY_NOISE_PROP_SCALE`, `TRAJECTORY_NOISE_FLOOR` — 日次 noise。
- **残余 threshold** ([`_clinical_course_thresholds.py`](_clinical_course_thresholds.py)、
  Issue #637): `ARCHETYPE_PROBABILITY_DEFAULT` /
  `ARCHETYPE_WEIGHT_FLOOR` (archetype 確率欠落時の default と floor)、
  bump-day noise、合併症 default、診断有効度係数、自然回復 / 貧血 /
  症状軸の回復率。
- **合併症 risk factor 語彙**
  ([`_complication_risk_conditions.py`](_complication_risk_conditions.py)、
  Issue #2093): `PATIENT_CONDITIONS` (`codes/data/valuesets.yaml` の internal value set、severity modifier と共通)、`STATE_ALIASES`、
  `SEVERITY_ALIASES`、`CONTEXT_RESOLVED` (`ComplicationContext` から
  解決)、`CONTEXT_CONDITIONS` (宣言済みだが False 評価)、`DRUG_CLASSES`。
- **Load 時 validator** (`_validate_course_archetypes`、
  `_validate_archetype_modifiers`、`validate_complication_risk_factors`、
  `clinosim/modules/disease/protocol.py` から呼ばれる) は disease YAML
  が未知の trajectory state 変数を使う / 未知 archetype 名を参照する /
  modifier の `condition` 文字列が壊れている / 未知の合併症 risk factor
  を使うケースを fail-loud に検出 — silent-no-op 防御。

## ディレクトリ構造

```
clinosim/modules/clinical_course/
  __init__.py                        空
  engine.py                          select_archetype / get_daily_directive / evaluate_complications / 診断 feedback
  _archetype_modifiers.py            重症度 + 年齢 multiplier 定数 (Issue #637)
  _clinical_course_thresholds.py     残余 threshold 定数 (Issue #637)
  _complication_risk_conditions.py   合併症 risk factor 語彙 + ComplicationContext (Issue #2093)
  reference_data/
    fallback_archetypes.yaml         built-in 6 archetype (trajectory + 確率)
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` は存在しない** — 疾患別 archetype データは
disease YAML (`clinosim/modules/disease/reference_data/`) に在る。

## Enricher 配線

該当なし — 本モジュールは encounter simulator が imperative に呼び出す
形態で、`register_builtin_enrichers` に登録されない。
`ENRICHER_SEED_OFFSETS` にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) (`L12`, `L643` 付近) | 入院時に `select_archetype` を呼び、結果を `encounter.clinical_course_archetype` に書き込む。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) (`L21` 付近) | 入院日ごとに `get_daily_directive` → `compute_diagnosis_effectiveness` / `apply_diagnosis_modifier` → `natural_recovery_directive` を呼び、合算 directive を `physiology.update` に渡す。`ComplicationContext` 付きで `evaluate_complications` を呼ぶ。 |
| Disease-protocol integration | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | 全 disease YAML に対し load 時に `_validate_archetype_modifiers`、`_validate_course_archetypes`、`validate_complication_risk_factors` を実行。 |

## テスト

```bash
pytest tests/unit -k "clinical_course or diagnosis_feedback" -q
```

個別ファイル:

- [`tests/unit/test_clinical_course.py`](../../../tests/unit/test_clinical_course.py)
  — `select_archetype` 分布 + `get_daily_directive` 決定論。
- [`tests/unit/test_diagnosis_feedback.py`](../../../tests/unit/test_diagnosis_feedback.py)
  — `compute_diagnosis_effectiveness` + `apply_diagnosis_modifier`
  補正。
- [`tests/unit/modules/clinical_course/`](../../../tests/unit/modules/clinical_course/)
  — module-scoped unit test (`archetype_modifiers`)。
- [`tests/unit/test_complication_risk_factors.py`](../../../tests/unit/test_complication_risk_factors.py)、
  [`tests/unit/test_context_risk_factors.py`](../../../tests/unit/test_context_risk_factors.py)
  — risk factor 語彙 / context 解決 (Issue #2093)。
- [`tests/unit/test_symptom_recovery_effectiveness.py`](../../../tests/unit/test_symptom_recovery_effectiveness.py)
  — `natural_recovery_directive` の症状軸スケーリング (Issue #2097)。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
