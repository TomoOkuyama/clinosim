# `clinosim.modules.patient` — Layer-1 person → Layer-2 patient 活性化

## 概要

Layer-1 `PersonRecord`
([`clinosim.modules.population`](../population/README.md) 由来) を
Layer-2 `PatientProfile` に promote する — 生理予備能 (腎 / 肝 / 心 /
免疫 / 薬物代謝) の付与、年齢 + 性別スケールの baseline vitals
(HR / SBP / DBP / RR / SpO₂ / 体温) の設定、per-condition stage サンプリング
(`"CKD G3a"` / `"NYHA III"` / `"GOLD 2"` 等) と physiology engine が読む
severity score 付きの慢性疾患活性化、disease profile 由来の常用薬
組立、保険選択、JP kana / romaji 表記処理。simulator は 1 患者 1 回
これを呼び、返却 profile が全 encounter simulator の入力になる。

## Scope

- **In scope**: `activate_patient(person, rng, demo)` orchestrator、
  身長 + 体重 (60 歳超の年齢別 shrinkage 込)、
  `PatientPhysiologicalProfile` field (immune / metabolism / renal /
  cardiac / hepatic reserve、`AGE_PENALTY_*` スケーリング付)、
  年齢 + 性別スケールの baseline vitals (BP 4 種 / HR / RR / SpO₂ /
  体温)、delirium-risk beta parameter (高齢 + dementia premium 付)、
  `_generate_stage` の重み付き stage サンプリングと
  `STAGE_SEVERITY` score lookup による慢性疾患活性化 (Issue #637
  PR-D refactor)、disease profile 由来の常用薬導出、国 / 年齢別
  保険サンプリング、JP romaji 名生成。加えて `test_patient.py` の
  決定論的 `create_test_patient()` fixture。
- **Out of scope**: 患者 *生成*
  ([`clinosim.modules.population`](../population/README.md))、疾患
  protocol 定義
  ([`clinosim.modules.disease`](../disease/README.md))、physiology
  state 進行
  ([`clinosim.modules.physiology`](../physiology/README.md))、
  encounter simulation ([`clinosim.simulator`](../../simulator/))、
  常用薬カタログ
  ([`clinosim.locale`](../../locale/) の `chronic_medications.yaml`)。

## Public API

`__init__.py` は空。呼び出し側は entry point を直接 import:

```python
from clinosim.modules.patient.activator import activate_patient
# (person: PersonRecord, rng: np.random.Generator, demo: dict) -> PatientProfile

from clinosim.modules.patient.test_patient import create_test_patient
# () -> PatientProfile  (決定論的 72 歳 JP 女性、HT + T2DM)
```

`_severity_activation.py` の stage / severity モデルは `activator.py`
が import + 再 export しており、caller が table を直接必要とする際に
使える:

```python
from clinosim.modules.patient.activator import (
    STAGE_SEVERITY,           # {stage_text: severity_score in [0.0, 1.0]}
    # …慢性疾患 ICD ごとの stage weight tuple 群…
)
```

## 決定論

- **`ENRICHER_SEED_OFFSETS` にサブ seed 未登録**。本モジュールは
  simulator の population pass 内で明示 `rng` を伴い呼ばれるため、
  per-patient 決定論は caller の契約 — patient cache
  (`person_id` キー) が run あたり exactly-once 活性化を保証する
  (`simulator/engine.py:399-410` 参照)。
- 慢性疾患 stage サンプリングは
  `rng.choice(p=…)` を使い、weight vector は import 時に合計 1.0 に
  validation 済み (`_severity_activation.py`)。previous inline literal
  を named tuple に置換する変更は byte-diff clean。
- 常用薬付与は (patient, disease profile) について決定論的 — 追加
  RNG draw なし。
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
- **新生児 (newborn) Patient 生成**: Z34 保有女性の周産期分娩 LifeEvent
  が発火した場合、対になる新生児 `PatientProfile` を構築 —
  `id = "<mother_id>-BABY"`、世帯は母親から継承、性別は per-mother
  sub-RNG でサンプリング、`birthDate` = 分娩日、身体計測は 0 歳
  default。新生児は自身の population sampler を回さない — 活性化は
  [`clinosim/simulator/perinatal.py`](../../simulator/perinatal.py)
  で行われ、母親 + 新生児の 2 `CIFPatientRecord` が返却され、新生児側
  の `Encounter.partOf` で紐付く。詳細:
  [`docs/reference/oncology-obstetric-service-lines.ja.md`](../../../docs/reference/oncology-obstetric-service-lines.ja.md)。

## 依存

- `clinosim.modules._shared` — `is_jp`, `normalize_probabilities`,
  `resolve_lang`。
- `clinosim.modules.patient._patient_activator_thresholds` — 586
  LOC の baseline / reserve / delirium / 慢性疾患 threshold
  (Issue #637 sweep)。
- `clinosim.modules.patient._severity_activation` — per-condition
  stage weight vector + `STAGE_SEVERITY` score table。
- `clinosim.modules.physiology.engine` — `hba1c_from_glycemic_control`
  (HbA1c 導出時に使用)。
- `clinosim.modules.population.engine` — `PersonRecord` +
  `_sample_given_name` (name-formatting 再利用)。
- `clinosim.locale.loader` — `load_names(country)` (kana / romaji
  format)。
- `clinosim.types.patient` — `PatientProfile`,
  `PatientPhysiologicalProfile`, `BaselineVitals`, `HomeMedication`,
  `ChronicCondition`。
- `numpy` — `np.random.Generator` (rng.beta / rng.choice / rng.normal)。

## 定数と設定

- **Threshold 表**: [`_patient_activator_thresholds.py`](_patient_activator_thresholds.py)
  — `activator.py` から lift された全 scalar (Issue #637)。主な cluster:
  - `BASELINE_{HR,SBP,DBP,RR,SPO2,TEMPERATURE}_*` — 6 vital-sign
    種別の年齢 / 性別 スケール、平均、標準偏差、ceiling。
  - `AGE_PENALTY_{MIN_AGE,SCALE,HEPATIC_RATIO}` —
    `AGE_PENALTY_MIN_AGE` 超えの reserve depletion。
  - `RESERVE_FLOOR`, `_RESERVE_BETA_PARAMS`,
    `IMMUNE_REACTIVITY_BETA_PARAMS` — 生理予備能 sampling shape。
  - `DRUG_METABOLISM_{LABELS,JP_PROBS,US_PROBS}` — 国別 fast /
    normal / slow 確率 vector。
  - `DELIRIUM_{BETA_PARAMS,ELDERLY_AGE_THRESHOLD,ELDERLY_PREMIUM,DEMENTIA_PREMIUM}`
    — delirium-risk model。
  - `CHRONIC_{ONSET_YEAR_MIN,ONSET_YEAR_MAX_EXCLUSIVE,ONSET_MONTH_MIN,…}`
    — 慢性疾患発症日サンプリング。
  - `CHRONIC_{CONTROLLED_PROBABILITY,SEVERITY_MILD_PROBABILITY}`。
- **Stage + severity 表**: [`_severity_activation.py`](_severity_activation.py)
  (Issue #637 PR-D) —
  - per-condition stage weight tuple (CKD / NYHA / GOLD 等)、
    import 時に合計 1.0 を validate。
  - `STAGE_SEVERITY: dict[str, float]` — stage テキストを
    `[0.0, 1.0]` の severity score に写像。
    [`clinosim.modules.physiology.engine.initialize_state`](../physiology/README.md)
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
  activator.py                         activate_patient orchestrator (629 LOC)
  _patient_activator_thresholds.py     named threshold (586 LOC, Issue #637)
  _severity_activation.py              慢性疾患 stage + severity table (Issue #637 PR-D)
  test_patient.py                      決定論的 create_test_patient() fixture
  SPEC.md                              拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` / `reference_data/` は存在しない** —
activator は simulator が直接呼び、常用薬 data は
`clinosim/locale/`、検証は下記 test で担保。

## Enricher 配線

該当なし — 本モジュールは population pass 中に simulator から直接
呼ばれる形で、`register_builtin_enrichers` には登録されない。
`ENRICHER_SEED_OFFSETS` にも seed 未登録。`activate_patient` 呼び出しは
caller 側 `person_id` キーの cache 内で走り、run あたり exactly-once
活性化する。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Simulator boot | [`clinosim/simulator/engine.py`](../../simulator/engine.py) (`L19` 付近, `L399-410`, `L970`) | 全 population member を patient cache に activate してから per-encounter simulation を回す。`unknown_condition` walkthrough でも再 activate。 |
| Enumeration path | [`clinosim/simulator/enumerate.py`](../../simulator/enumerate.py) (`L581`, `L647` 付近) | enumeration entry で `activate_patient` を遅延 import。 |
| CLI single-encounter driver | [`clinosim/simulator/cli_test_encounter.py`](../../simulator/cli_test_encounter.py) (`L15`, `L111`, `L191` 付近) | smoke run で 1 患者ずつ activate。 |
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
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
