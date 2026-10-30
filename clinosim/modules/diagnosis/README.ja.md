# `clinosim.modules.diagnosis` — Bayesian 鑑別診断 engine

## 概要

encounter timeline 上で Bayesian 差別診断を維持する: disease YAML の
prior から per-encounter 差別を初期化、新規 lab / vital / imaging
結果ごとに候補確率を likelihood-ratio Bayesian 更新、
current working / confirmed / discharge の診断コードを解決する。
Issue #551 で 6 sites に散在していた非特異 / fallback ICD-10 コードの
named canonical 定数、FHIR emit 層が gate に使う ICD-10 code 分類
predicate (Z-chapter visit-reason code、主診断不可 code)、および
lab 由来 AKI (N17.9) working diagnosis を追記する RNG-free な
POST_ENCOUNTER enricher 1 本 (`lab_derived_dx.py`、Issue #1326) も所有する。

## Scope

- **In scope**: `initialize_differential` (disease protocol の
  `diagnostic.differential` から seed、無ければ disease id キーの
  built-in table に fallback); `update_differential`
  (`(finding, is_positive)` findings 単位の likelihood-ratio update);
  `get_current_diagnosis_code` (working diagnosis — 未設定なら最上位
  候補 — を confidence キーの `diagnosis_progression` table で解決、
  患者の性別に解剖学的に不適合な候補は skip (Issue #947)、何も解決
  できなければ `UNRESOLVED_DIAGNOSIS_ICD` sentinel); named 非特異 /
  fallback コード (`UNRESOLVED_DIAGNOSIS_ICD = "R69"`,
  `ICD_COUGH = "R05"`。R50.9 / R53.1 / R68.8 / Z09 は follow-up sweep
  で抽出予定で未実装); ICD-10 predicate `is_visit_reason_zcode`
  (Issue #916)、`is_never_principal_dx` (Issue #2157)、
  `encounter_primary_dx_code` (Issue #1215); `lab_derived_dx` enricher
  (N17.x も CKD 4-5 / ESRD baseline も無い入院 encounter で
  Creatinine peak >= 4.0 mg/dL → N17.9 の `working_diagnoses` entry)。
- **Out of scope**: disease protocol 定義
  ([`clinosim.modules.disease`](../disease/README.ja.md))、ICD /
  SNOMED registry ([`clinosim/codes/`](../../codes/))、FHIR
  `Condition` / `ClinicalImpression` emission
  ([`clinosim.modules.output`](../output/README.ja.md))、diagnosis の
  trajectory feedback (それは
  [`clinosim.modules.clinical_course`](../clinical_course/README.ja.md)
  で走る)。

## Public API

`__init__.py` は空。呼び出し側は submodule から直接 import:

```python
from clinosim.modules.diagnosis.engine import (
    initialize_differential,         # (disease_id, age, protocol_diagnostic=None) -> DifferentialDiagnosis
    update_differential,             # (diff, findings, confirmation_threshold=0.90, protocol_lr_table=None) -> DifferentialDiagnosis
    get_current_diagnosis_code,      # (diff, protocol_progression=None, patient_sex=None) -> (icd_code, display)
)
from clinosim.modules.diagnosis.nonspecific_codes import (
    UNRESOLVED_DIAGNOSIS_ICD,        # "R69"
    ICD_COUGH,                       # "R05" — 実症状、決して wrong-dx sentinel ではない
    is_visit_reason_zcode,           # (code) -> bool — Z-chapter visit-reason (Issue #916)
    is_never_principal_dx,           # (code) -> bool — Z37 / R65 (Issue #2157)
    encounter_primary_dx_code,       # (record_dict, encounter_id) -> str (Issue #1215)
)
from clinosim.modules.diagnosis.lab_derived_dx import (
    enrich_lab_derived_dx,           # POST_ENCOUNTER enricher (Issue #1326)
)
from clinosim.modules.diagnosis._diagnosis_thresholds import (
    WORKING_DIAGNOSIS_MIN_PROB,      # 0.5 — "more likely than not" cutoff
    # …DEFAULT_CONFIRMATION_THRESHOLD (0.90)、ELDERLY_HF_PRIOR_AGE_THRESHOLD (75)、
    # ELDERLY_HF_PRIOR_MULTIPLIER (1.5)、NEUTRAL_LIKELIHOOD_RATIO (1.0)…
)
```

## 決定論

該当なし — 本モジュールは乱数を引かない。差別初期化と Bayesian
update は observation 列 + prior 確率の純粋関数。
`get_current_diagnosis_code` は確率順にソート済みの候補列の決定論的
walk。`enrich_lab_derived_dx` は lab 値のみを走査する (RNG 無し、
seed offset 無し)。

## 依存

- `clinosim.codes` — `lookup` (ICD-10-CM display 解決)。
- `clinosim.simulator.sex_gating` — `is_sex_locked_for`、
  `pick_sex_compatible_dx_code` (`patient_sex` 指定時のみ遅延 import)。
- `clinosim.simulator.enrichers` — `EnricherContext`
  (`lab_derived_dx.py`)。
- `clinosim.modules.diagnosis._diagnosis_thresholds` — 全 working /
  confirmed cutoff、age-prior 調整、neutral-LR fallback
  (Issue #637)。
- `clinosim.modules.diagnosis.nonspecific_codes` — Issue #551 の
  named fallback / 非特異 ICD-10 定数。
- `clinosim.types.diagnosis` — `DifferentialDiagnosis`,
  `DiagnosisCandidate`。
- `yaml`。

## 定数と設定

- **Threshold** ([`_diagnosis_thresholds.py`](_diagnosis_thresholds.py)、
  Issue #637 sweep):
  - Family 1 — working / confirmed cutoff
    (`WORKING_DIAGNOSIS_MIN_PROB = 0.5` — "more likely than not"、
    `DEFAULT_CONFIRMATION_THRESHOLD = 0.90` — 最上位候補がこれ以上で
    `diff.confirmed = True`)。
  - Family 2 — 年齢別 prior 調整 (年齢 >=
    `ELDERLY_HF_PRIOR_AGE_THRESHOLD = 75` で `heart_failure` の prior を
    正規化前に `ELDERLY_HF_PRIOR_MULTIPLIER = 1.5` 倍)。
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
  — disease id をキーとした built-in table: `differentials`、
  `diagnosis_progression`、`lr_table` (disease YAML が
  `diagnostic.differential` / progression / LR を持たないときの
  fallback。未知の disease id は `bacterial_pneumonia` の差別に fallback)。
- **Lab 由来 AKI** ([`lab_derived_dx.py`](lab_derived_dx.py)):
  `CREATININE_KDIGO_STAGE3_ABSOLUTE_MG_DL = 4.0`、
  `LAB_DERIVED_AKI_DIAGNOSIS_CODE = "N17.9"`、source tag
  `lab_derived_aki_kdigo_stage3`。

## ディレクトリ構造

```
clinosim/modules/diagnosis/
  __init__.py                    空
  engine.py                      initialize_differential + update_differential + get_current_diagnosis_code
  nonspecific_codes.py           Issue #551 named ICD-10 fallback 定数
  _diagnosis_thresholds.py       working / confirmed cutoff + age prior + neutral LR fallback (Issue #637)
  lab_derived_dx.py              POST_ENCOUNTER enricher: Creatinine peak -> N17.9 working dx (Issue #1326)
  reference_data/
    builtin_differentials.yaml   built-in 差別ライブラリ
  SPEC.md                        拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` は存在しない** (enricher 1 本は
`lab_derived_dx.py` にある)。

## Enricher 配線

差別診断 engine は encounter simulator が imperative に呼ぶ。
`register_builtin_enrichers`
([`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)) は
本モジュールから enricher を 1 本登録する:

| Name | Stage | Order | Seed offset |
| --- | --- | --- | --- |
| `lab_derived_dx` | `POST_ENCOUNTER` | 94 (`nursing_assignment` と同順、name 順で先に走る) | なし (RNG-free) |

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | 入院時に `initialize_differential`、退院時に `get_current_diagnosis_code`。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | 新規 observation ごとに `update_differential`。 |
| FHIR Condition / Encounter / Procedure emit | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) (`conditions/conditions.py`、`encounters/encounter.py`、`procedures/procedures.py`、`procedures/oxygen_therapy.py`、`lib/inline_bb.py`) | `is_visit_reason_zcode` / `is_never_principal_dx` / `encounter_primary_dx_code` で gate。 |
| FHIR Condition emit | `conditions/conditions.py` の `working_diagnoses` walker | `lab_derived_dx` が追記した N17.9 entry を Condition 化。 |
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
  — [`clinosim.modules.clinical_course`](../clinical_course/README.ja.md)
  への diagnosis feedback (cross-module integration)。
- [`tests/unit/test_types_diagnosis.py`](../../../tests/unit/test_types_diagnosis.py)
  — dataclass shape。
- [`tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py`](../../../tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py)
  — Issue #551 guard: `R05` (咳) が古い sentinel との単純比較で
  誤診扱いされないことを保証。
- [`tests/unit/test_lab_derived_dx_1326.py`](../../../tests/unit/test_lab_derived_dx_1326.py)
  — `lab_derived_dx` enricher。
- `tests/unit/output/test_fhir_condition_zcode_visit_reason_916.py`、
  `test_principal_dx_ranking_2157.py`、
  `test_fhir_encounter_reason_code_per_encounter_1215.py` —
  FHIR emit 層での `nonspecific_codes` predicate。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
