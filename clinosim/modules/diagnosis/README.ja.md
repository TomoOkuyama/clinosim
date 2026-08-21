# `clinosim.modules.diagnosis` — Bayesian 鑑別診断 engine

## 概要

encounter timeline 上で Bayesian 差別診断を維持する: disease YAML の
prior から per-encounter 差別を初期化、新規 lab / vital / imaging
結果ごとに候補確率を likelihood-ratio Bayesian 更新、
current working / confirmed / discharge の診断コードを解決する。
Issue #551 で 6 sites に散在していた非特異 / fallback ICD-10 コードの
named canonical 定数も所有する。

## Scope

- **In scope**: `initialize_differential` (disease protocol の
  `differential` block から seed); `update_differential` (新規
  observation ごとの likelihood-ratio update); `get_current_diagnosis_code`
  (最高確率候補を返す。working-diagnosis 閾値を超える候補が無い場合は
  `UNRESOLVED_DIAGNOSIS_ICD` sentinel); named 非特異 / fallback コード
  (`UNRESOLVED_DIAGNOSIS_ICD = "R69"`, `ICD_COUGH = "R05"`、
  R50.9 / R53.1 / R68.8 / Z09 の拡張スロット)。
- **Out of scope**: disease protocol 定義
  ([`clinosim.modules.disease`](../disease/README.md))、ICD /
  SNOMED registry ([`clinosim/codes/`](../../codes/))、FHIR
  `Condition` / `ClinicalImpression` emission
  ([`clinosim.modules.output`](../output/README.md))、diagnosis の
  trajectory feedback (それは
  [`clinosim.modules.clinical_course`](../clinical_course/README.md)
  で走る)。

## Public API

`__init__.py` は空。呼び出し側は 2 submodule から直接 import:

```python
from clinosim.modules.diagnosis.engine import (
    initialize_differential,         # (encounter, protocol) -> DifferentialDiagnosis
    update_differential,             # (diff, observation, ...) -> None
    get_current_diagnosis_code,      # (diff) -> ICD-10 code str
)
from clinosim.modules.diagnosis.nonspecific_codes import (
    UNRESOLVED_DIAGNOSIS_ICD,        # "R69"
    ICD_COUGH,                       # "R05" — 実症状、決して wrong-dx sentinel ではない
)
from clinosim.modules.diagnosis._diagnosis_thresholds import (
    WORKING_DIAGNOSIS_MIN_PROB,      # 0.5 — "more likely than not" cutoff
    # …confirmed-diagnosis cutoff + age prior + neutral LR fallback…
)
```

## 決定論

該当なし — 本モジュールは乱数を引かない。差別初期化と Bayesian
update は observation 列 + prior 確率の純粋関数。
`get_current_diagnosis_code` は差別 map の決定論的 argmax。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`。
- `clinosim.modules.diagnosis._diagnosis_thresholds` — 全 working /
  confirmed cutoff、age-prior 調整、neutral-LR fallback
  (Issue #637)。
- `clinosim.modules.diagnosis.nonspecific_codes` — Issue #551 の
  named fallback / 非特異 ICD-10 定数。
- `clinosim.types.diagnosis` — `DifferentialDiagnosis`,
  `DifferentialCandidate`。
- `yaml`。

## 定数と設定

- **Threshold** ([`_diagnosis_thresholds.py`](_diagnosis_thresholds.py)、
  Issue #637 sweep):
  - Family 1 — working / confirmed cutoff
    (`WORKING_DIAGNOSIS_MIN_PROB = 0.5` — "more likely than not"、
    confirmed cutoff は差別を凍結する上位閾値)。
  - Family 2 — 年齢別 prior 調整 (高齢患者は年齢関連条件に prior
    lift)。
  - Family 3 — 欠落 likelihood-ratio entry の neutral fallback
    (`dict.get(default=1.0)` に埋没しないよう grep 可能に extract)。
- **非特異コード** ([`nonspecific_codes.py`](nonspecific_codes.py)、
  Issue #551): ICD-10 タイトルを verbatim 引用した named 定数 —
  rename は silent drift ではなく `ImportError` を発生させる。
  file docstring が `R05` (咳) と `R69` (原因不明の症状) の
  混同で正当な咳症状が silent に「誤診」扱いされていた過去問題を
  詳述している。
- **Reference data**:
  [`reference_data/builtin_differentials.yaml`](reference_data/builtin_differentials.yaml)
  — 主訴 pattern をキーとした built-in 差別ライブラリ (disease YAML
  が `differential` block を持たないときの fallback)。

## ディレクトリ構造

```
clinosim/modules/diagnosis/
  __init__.py                    空
  engine.py                      initialize_differential + update_differential + get_current_diagnosis_code
  nonspecific_codes.py           Issue #551 named ICD-10 fallback 定数
  _diagnosis_thresholds.py       working / confirmed cutoff + age prior + neutral LR fallback (Issue #637)
  reference_data/
    builtin_differentials.yaml   built-in 差別ライブラリ
  SPEC.md                        拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` は存在しない**。

## Enricher 配線

該当なし — 本モジュールは encounter simulator が imperative に呼ぶ。
`register_builtin_enrichers` に登録なく、`ENRICHER_SEED_OFFSETS` にも
seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | 入院時に `initialize_differential`、退院時に `get_current_diagnosis_code`。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | 新規 observation ごとに `update_differential`。 |
| Wall-clock sentinel test | [`tests/unit/test_wallclock_sentinel_defaults.py`](../../../tests/unit/test_wallclock_sentinel_defaults.py) | `DifferentialDiagnosis` sentinel default を import。 |

## テスト

```bash
pytest tests/unit -k "diagnosis or r05_cough" -q
```

個別ファイル:

- [`tests/unit/test_diagnosis.py`](../../../tests/unit/test_diagnosis.py)
  — `initialize_differential` + `update_differential` 挙動。
- [`tests/unit/test_diagnosis_code_coverage.py`](../../../tests/unit/test_diagnosis_code_coverage.py)
  — 差別 ICD code coverage。
- [`tests/unit/test_diagnosis_code_mapping.py`](../../../tests/unit/test_diagnosis_code_mapping.py)
  — code → display mapping。
- [`tests/unit/test_diagnosis_feedback.py`](../../../tests/unit/test_diagnosis_feedback.py)
  — [`clinosim.modules.clinical_course`](../clinical_course/README.md)
  への diagnosis feedback (cross-module integration)。
- [`tests/unit/test_types_diagnosis.py`](../../../tests/unit/test_types_diagnosis.py)
  — dataclass shape。
- [`tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py`](../../../tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py)
  — Issue #551 guard: `R05` (咳) が古い sentinel との単純比較で
  誤診扱いされないことを保証。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
