# `clinosim.modules.clinical_course` — trajectory archetype + 日次 directive engine

## 概要

日 scale の臨床 trajectory を所有する: 入院時に disease YAML の
`course_archetypes` (例 `smooth_recovery`, `gradual_deterioration`,
`sudden_deterioration`, `treatment_resistant`) から 1 つを選出し、
[`clinosim.modules.physiology`](../physiology/README.md) が state
vector に適用する日次 `StateChangeDirective` を評価し、疾患スコープの
リスク条件による合併症を評価し、診断有効度の feedback で trajectory
を補正する。`physiology` が「現時点 state の意味」を決めるのに対し、
`clinical_course` は「翌日以降 state をどう動かすか」を決める。

## Scope

- **In scope**: `select_archetype` (YAML archetype 確率 + 重症度 tier
  multiplier + per-disease `archetype_modifiers` の患者リスク調整 +
  age / immune-reactivity / treatment-sensitivity の速度係数、
  すべて `normalize_probabilities(fallback="raise")` を通して正規化);
  `get_daily_directive` (age スケールの trajectory 補間 + 免疫反応性
  による amplitude modulation); `evaluate_complications` (archetype
  ごとのリスク条件、`_evaluate_risk_condition` DSL で慢性疾患 / 年齢
  / lab トリガーを評価); `compute_diagnosis_effectiveness` +
  `apply_diagnosis_modifier` (診断駆動の補正を trajectory に戻す);
  `natural_recovery_directive` (fallback); disease YAML の
  `course_archetypes` / `archetype_modifiers` に対する import 時
  validator。
- **Out of scope**: state vector 意味論 + coupling
  ([`clinosim.modules.physiology`](../physiology/README.md))、disease
  YAML schema 本体
  ([`clinosim.modules.disease`](../disease/README.md))、encounter
  timeline ([`clinosim.modules.encounter`](../encounter/README.md))、
  日次 loop mechanics
  ([`clinosim.simulator.daily_loop`](../../simulator/daily_loop.py))。

## Public API

`__init__.py` は空。呼び出し側は `engine.py` から直接 import:

```python
from clinosim.modules.clinical_course.engine import (
    select_archetype,                # (severity, profile, rng, protocol_archetypes=None, protocol_modifiers=None, patient=None) -> archetype_name
    get_daily_directive,             # (archetype_name, day, profile, protocol_archetypes=None, age=70, rng=None) -> StateChangeDirective
    evaluate_complications,          # (archetype_name, day, patient, protocol_archetypes, rng) -> list[complication]
    compute_diagnosis_effectiveness, # (encounter, ...) -> effectiveness score
    apply_diagnosis_modifier,        # (directive, effectiveness, ...) -> StateChangeDirective
    natural_recovery_directive,      # archetype lookup 失敗時の fallback directive
)
```

## 決定論

- `ENRICHER_SEED_OFFSETS` にサブ seed 未登録。全 entry は caller が
  渡す `rng` に対して pure。encounter simulator (`inpatient.py`) が
  呼び出し前に per-encounter サブ RNG を導出する。
- Archetype 選出は `rng.choice(names, p=weights)` を
  `normalize_probabilities(fallback="raise")` 経由で使う — 総和 0 の
  weight は silent bias にならず raise する。
- 日次 directive 補間は `(archetype, day, age, immune_reactivity)` に
  対して決定論的。`rng` 引数は optional で、`sudden_deterioration`
  等の意図的な確率事件でのみ消費される。

## 依存

- `clinosim.modules._shared` — `normalize_probabilities`
  (`fallback="raise"`)。
- `clinosim.modules.clinical_course._archetype_modifiers` —
  archetype / 重症度別 multiplier 定数 (Issue #637 refactor)。
- `clinosim.modules.clinical_course._clinical_course_thresholds` —
  `_archetype_modifiers.py` に含まれない残余 threshold
  (Issue #637 refactor)。
- `clinosim.types.clinical` — `StateChangeDirective`,
  `PatientPhysiologicalProfile`。
- `numpy` — `np.random.Generator`。

## 定数と設定

- **Fallback archetype 表** (`engine.py`): `_FALLBACK_PROBABILITIES`
  は disease YAML が `course_archetypes` を持たないときの baseline
  確率の単一情報源。重症度 multiplier logic は baseline をここから
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
  - `ARCHETYPE_PROBABILITY_DEFAULT`, `ARCHETYPE_WEIGHT_FLOOR` —
    archetype 確率欠落時の default と floor。
- **残余 threshold** ([`_clinical_course_thresholds.py`](_clinical_course_thresholds.py)、
  Issue #637): `evaluate_complications`,
  `compute_diagnosis_effectiveness`, `_interpolate` から
  archetype-modifier に収まらない定数を lift。
- **Load 時 validator** (`_validate_course_archetypes` +
  `_validate_archetype_modifiers`) は disease YAML が未知 archetype
  名を参照する / modifier の `condition` 文字列が壊れているケースを
  fail-loud に検出 — silent-no-op 防御。

## ディレクトリ構造

```
clinosim/modules/clinical_course/
  __init__.py                        空
  engine.py                          select_archetype / get_daily_directive / evaluate_complications / 診断 feedback
  _archetype_modifiers.py            重症度 + 年齢 multiplier 定数 (Issue #637)
  _clinical_course_thresholds.py     残余 threshold 定数 (Issue #637)
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` / `reference_data/` は存在しない** —
archetype データは disease YAML
(`clinosim/modules/disease/reference_data/*.yaml`) に在る。

## Enricher 配線

該当なし — 本モジュールは encounter simulator が imperative に呼び出す
形態で、`register_builtin_enrichers` に登録されない。
`ENRICHER_SEED_OFFSETS` にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) (`L12`, `L252` 付近) | 入院時に `select_archetype` を呼び、結果を `encounter.clinical_course_archetype` に書き込む。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) (`L21` 付近) | 入院日ごとに `get_daily_directive` + `evaluate_complications` を呼び、directive を `physiology.update` に渡す。 |
| Disease-protocol integration | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | YAML `archetype_modifiers.condition` token 解決を load 時に cross-validate。 |

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
  — module-scoped unit test。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
