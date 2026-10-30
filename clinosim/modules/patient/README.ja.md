# `clinosim.modules.patient` — Layer-1 person → Layer-2 patient 活性化

## 概要

Layer-1 `PersonRecord`
([`clinosim.modules.population`](../population/README.ja.md) 由来) を
Layer-2 `PatientProfile` に promote する — 生理予備能 (腎 / 肝 / 心 /
免疫 / 薬物代謝) の付与、年齢 + 性別スケールの baseline vitals
(HR / SBP / DBP / RR / SpO₂ / 体温) の設定、per-condition stage サンプリング
(`"CKD G3a"` / `"NYHA III"` / `"GOLD 2"` 等) と physiology engine が読む
severity score 付きの慢性疾患活性化、disease profile 由来の常用薬
組立、保険選択、locale 順の表示名 (JP は姓先) と緊急連絡先の
サンプリング。simulator は `(person_id, as_of_year)` cache key ごとに
1 回これを呼び、返却 profile が全 encounter simulator の入力になる。

## Scope

- **In scope**: `activate_patient(person, rng, demo, as_of_year=None)` orchestrator、
  身長 + 体重 (60 歳超の年齢別 shrinkage 込)、
  `PatientPhysiologicalProfile` field (immune / metabolism / renal /
  cardiac / hepatic reserve、`AGE_PENALTY_*` スケーリング付)、
  年齢 + 性別スケールの baseline vitals (BP 4 種 / HR / RR / SpO₂ /
  体温)、delirium-risk beta parameter (高齢 + dementia premium 付)、
  `_generate_stage` の重み付き stage サンプリングと
  `STAGE_SEVERITY` score lookup による慢性疾患活性化 (Issue #637
  PR-D refactor)、disease profile 由来の常用薬導出、国 / 年齢別
  保険サンプリング、表示名の並び + 緊急連絡先氏名サンプリング。加えて `test_patient.py` の
  決定論的 `create_test_patient()` fixture。
- **Out of scope**: 患者 *生成*
  ([`clinosim.modules.population`](../population/README.ja.md))、疾患
  protocol 定義
  ([`clinosim.modules.disease`](../disease/README.ja.md))、physiology
  state 進行
  ([`clinosim.modules.physiology`](../physiology/README.ja.md))、
  encounter simulation ([`clinosim.simulator`](../../simulator/))、
  常用薬カタログ
  ([`clinosim.locale`](../../locale/) の `chronic_medications.yaml`)。

## Public API

`__init__.py` は空。呼び出し側は entry point を直接 import:

```python
from clinosim.modules.patient.activator import activate_patient
# (person: PersonRecord, rng: np.random.Generator, demo: dict,
#  as_of_year: int | None = None) -> PatientProfile

from clinosim.modules.patient.test_patient import create_test_patient
# () -> PatientProfile  (決定論的 72 歳 JP 女性、HT + T2DM)
```

`_severity_activation.py` の stage / severity table は `activator.py`
の名前空間に import されている (`__all__` なし) ため、caller は
どちらの module からも import できる:

```python
from clinosim.modules.patient.activator import (
    STAGE_SEVERITY,           # {condition_code: {stage_text: severity_score in [0.0, 1.0]}}
    # …慢性疾患 ICD ごとの stage weight tuple 群…
)
```

## 決定論

- **`ENRICHER_SEED_OFFSETS` にサブ seed 未登録**。本モジュールは
  simulator から必要時に明示 `rng` を伴い呼ばれるため、per-patient
  決定論は caller の契約。`simulator/_setup.py::_activate_cached_person`
  が `(person_id, as_of_year)` キーで profile を cache し、miss 時に
  `derive_phase_rng(master_seed, PHASE_INPATIENT_SIM,
  "activate|<person_id>")` で活性化するため、key あたり exactly-once
  かつ encounter 順序に依存しない。
- 慢性疾患 stage サンプリングは
  `rng.choice(p=…)` を使い、weight vector は import 時に合計 1.0 に
  validation 済み (`_severity_activation.py`)。previous inline literal
  を named tuple に置換する変更は byte-diff clean。
- 常用薬付与 (`_derive_home_medications`) は caller の `rng` を
  消費しない: `seeding.chronic_medication_seed(patient_id)` (chemo
  regimen は `chemotherapy_regimen_seed(patient_id, code)`) で seed
  した per-patient sub-RNG を使うため、(patient, conditions, country,
  age) について決定論的。
- **慢性継続薬の跨 encounter 引き継ぎ (v0.5.x fix)**: disease YAML
  の `continue_at_discharge` block から派生した常用薬 (抗凝固 / スタチン
  / 降圧 / 抗血小板等の生涯 secondary prevention 薬) が encounter を
  跨いで生存するよう修正済み。実装は
  [`clinosim/simulator/discharge_rx.py`](../../simulator/discharge_rx.py)
  (`_append_item(chronic_continuation=True)` は default 28 日)と
  [`clinosim/simulator/helpers.py`](../../simulator/helpers.py)
  (`_deactivate_to_layer1` の急性 filter が `0 < d <= 14` を gate
  するようになり、`atrial_fibrillation_rvr.yaml` 等が使う「長期 /
  未指定」marker である `duration_days=0` は chronic として fall-through)。
  regression: `test_continue_at_discharge_items_default_to_28_day_chronic_duration`、
  `test_duration_days_zero_is_chronic_and_carries_forward`、
  `test_duration_days_seven_is_acute_and_dropped`、
  `test_anticoag_from_admission1_carries_forward_to_admission2_home_meds`。
- **新生児 (newborn) Patient 生成**: 分娩が発火すると、対になる新生児
  `PatientProfile` を `activate_patient` ではなく
  [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py)
  (`_build_newborn_patient`) が構築する — id は `"<mother_id>-BABY"`
  (2 人目以降は `"<mother_id>-<N>-BABY"`)、世帯と姓は母親から継承、
  性別は per-mother sub-RNG でサンプリング、`birthDate` = 分娩日、
  新生児 baseline vitals は `perinatal.yaml` 由来。分娩は母親 + 新生児
  の 2 `CIFPatientRecord` を返し、新生児側の `Encounter.partOf` で
  紐付く。その後新生児は `population/newborn.py::register_newborn` で
  population に登録され、出生入院退院の翌日から在籍 (`enrolled_from`)
  し、以降の encounter では通常の cache 経由で活性化される。詳細:
  [`docs/reference/oncology-obstetric-service-lines.ja.md`](../../../docs/reference/oncology-obstetric-service-lines.ja.md)。

## 依存

- `clinosim.modules._shared` — `is_jp`, `normalize_probabilities`,
  `resolve_lang`。
- `clinosim.modules.patient._patient_activator_thresholds` — 586
  LOC の baseline / reserve / delirium / 慢性疾患 threshold
  (Issue #637 sweep)。
- `clinosim.modules.patient._severity_activation` — per-condition
  stage weight vector + `STAGE_SEVERITY` score table。
- `clinosim.modules.longitudinal.engine` — `state_at` (遅延 import。
  糖尿病の `HbA1c x.x%` stage text と engine 所有の慢性 stage を
  `person.longitudinal_history` から読む)。
- `clinosim.modules.population.engine` — `PersonRecord` +
  `_sample_given_name` (緊急連絡先氏名サンプリング)、
  `pick_active_chemo_regimen` (遅延)。
- `clinosim.modules.population._pediatric_anthropometry` — 小児分岐の
  成長曲線身長 parameter。
- `clinosim.locale.loader` — `load_names(country)` (緊急連絡先の
  名)、`load_chronic_medications`、`load_chemo_regimens`。
- `clinosim.seeding` — `chronic_medication_seed`、
  `chemotherapy_regimen_seed`。
- `clinosim.modules.drug_safety`、`clinosim.codes.drugs` (遅延) —
  常用薬の安全性 check と薬剤解決。
- `clinosim.types.patient` — `PatientProfile`,
  `PatientPhysiologicalProfile`, `BaselineVitals`, `HomeMedication`,
  `ChronicCondition`, `PersonName`。
- `numpy` — `np.random.Generator` (rng.beta / rng.choice / rng.normal)。

## 定数と設定

- **Threshold 表**: [`_patient_activator_thresholds.py`](_patient_activator_thresholds.py)
  — `activator.py` から lift された全 scalar (Issue #637)。主な cluster:
  - `BASELINE_{HR,SBP,DBP,RR,SPO2,TEMPERATURE}_*` — 6 vital-sign
    種別の年齢 / 性別 スケール、平均、標準偏差、ceiling。
  - `AGE_PENALTY_{MIN_AGE,SCALE,HEPATIC_RATIO}` —
    `AGE_PENALTY_MIN_AGE` 超えの reserve depletion。
  - `RESERVE_FLOOR`, `IMMUNE_REACTIVITY_BETA_PARAMS` — 生理予備能
    sampling shape (共通 reserve Beta `_RESERVE_BETA_PARAMS = (30, 2)`
    は `activator.py` 側にある)。
  - `DRUG_METABOLISM_{LABELS,JP_PROBS,US_PROBS}` — 国別 poor /
    normal / rapid / ultra_rapid 確率 vector。
  - `DELIRIUM_{BETA_PARAMS,ELDERLY_AGE_THRESHOLD,ELDERLY_PREMIUM,DEMENTIA_PREMIUM,PARKINSON_PREMIUM}`
    — delirium-risk model。
  - `DVT_{BETA_PARAMS,ELDERLY_AGE_THRESHOLD,ELDERLY_PREMIUM}` — DVT
    susceptibility。
  - `CHRONIC_{ONSET_YEAR_MIN,ONSET_YEAR_MAX_EXCLUSIVE,ONSET_MONTH_MIN,…}`
    — 慢性疾患発症日サンプリング。
  - `CHRONIC_{CONTROLLED_PROBABILITY,SEVERITY_MILD_PROBABILITY}`。
- **Stage + severity 表**: [`_severity_activation.py`](_severity_activation.py)
  (Issue #637 PR-D) —
  - per-condition stage weight tuple (CKD / NYHA / GOLD 等)、
    import 時に合計 1.0 を validate。
  - `STAGE_SEVERITY: dict[str, dict[str, float]]` — condition code
    ごとに stage テキストを `[0.0, 1.0]` の severity score に写像。
    [`clinosim.modules.physiology.engine.initialize_state`](../physiology/README.ja.md)
    が消費する。各条件の severe 閾値
    (`clinosim/modules/physiology/_coupling_coefficients.py` 定義)
    を超える score は "severe" physiology 分岐を発火する。
- **Test-patient fixture**: [`test_patient.py`](test_patient.py) —
  `create_test_patient()` は決定論的 72 歳 JP 女性 (HT + T2DM) を
  返す。full population module を起動せず安定 patient が欲しい
  legacy v0.1-alpha test 向け。

## ディレクトリ構造

```
clinosim/modules/patient/
  __init__.py                          空
  activator.py                         activate_patient orchestrator (~1150 LOC)
  _patient_activator_thresholds.py     named threshold (586 LOC, Issue #637)
  _severity_activation.py              慢性疾患 stage + severity table (Issue #637 PR-D)
  test_patient.py                      決定論的 create_test_patient() fixture
  SPEC.md                              拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` / `reference_data/` は存在しない** —
activator は simulator が直接呼び、常用薬 data は
`clinosim/locale/`、検証は下記 test で担保。

## Enricher 配線

該当なし — 本モジュールは臨床 profile が初めて必要になった時点で
simulator から直接呼ばれ、`register_builtin_enrichers` には登録
されない。`ENRICHER_SEED_OFFSETS` にも seed 未登録。`activate_patient`
呼び出しは caller 側の `(person_id, as_of_year)` キー cache 内で走り、
key あたり exactly-once 活性化する。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Patient cache | [`clinosim/simulator/_setup.py`](../../simulator/_setup.py) (`_activate_cached_person`) | cache miss 時に activate。`_dispatch.py` と `phases/` runner (`_readmission`, `_post_discharge`, `_healthcare_calendar`, `_ed_slot`) から呼ばれる。 |
| Forced scenarios | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`L387` 付近) | 合成 `FORCED-NNNN` person を activate。 |
| Enumeration path | [`clinosim/simulator/enumerate.py`](../../simulator/enumerate.py) (`L581`, `L647` 付近) | enumeration entry で `activate_patient` を遅延 import。 |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) (`L14`, `L110`, `L190` 付近) | smoke run で 1 患者ずつ activate。 |
| Outpatient encounter | [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py) | activator が set した `PatientProfile` field を使用。 |
| Types layer | [`clinosim/types/patient.py`](../../types/patient.py) | activator が `PatientProfile` + child 型の全 field を populate。 |

## テスト

```bash
pytest tests/unit -k "patient or activator" -q
pytest tests/integration -k "patient_cache" -q
```

個別ファイル:

- [`tests/unit/test_patient_profile.py`](../../../tests/unit/test_patient_profile.py)
  — `PatientProfile` 型 shape。
- [`tests/unit/test_patient_factory_fixture.py`](../../../tests/unit/test_patient_factory_fixture.py)
  — `create_test_patient()` fixture の安定性。
- [`tests/unit/test_patient_cache_current_meds_sync.py`](../../../tests/unit/test_patient_cache_current_meds_sync.py)
  — patient-cache 常用薬 sync (「同一患者は複数 encounter 通じて同じ
  常用薬」契約)。
- [`tests/unit/test_activator_chronic_medications_exclusive.py`](../../../tests/unit/test_activator_chronic_medications_exclusive.py)
  — 常用薬が疾患別に排他的付与。
- [`tests/integration/test_patient_cache_current_meds_carryforward.py`](../../../tests/integration/test_patient_cache_current_meds_carryforward.py)
  — encounter 跨ぎの cache 引き継ぎ end-to-end。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
