# `clinosim.modules.physiology` — 生理 state engine + lab / vital 導出

## 概要

clinosim の隠れ生理 state モデルを所有する — 下流の lab 値、vital
sign、薬物応答が導出元とする軸。患者の
`PatientPhysiologicalProfile` + `ChronicCondition` list から
`initialize_state` が `PhysiologicalState` を構築し、
`apply_state_delta` + `apply_coupling_rules` が state を進行させ、
`derive_lab_values` + `derive_vital_signs` +
`derive_observed_vitals` が或る瞬間の具体的 lab / vital 測定値に
projection する。simulator 外部から見える臨床値はすべてこの state
の projection である「リアリズム core」。

[`clinical_course`](../clinical_course/README.ja.md) は「翌日 state を
どう動かすか」を決定するのに対し、`physiology` は「その state が
現時点の患者 lab / vital にとって何を意味するか」を定義し、
clinical_course が要求する day-scale delta を適用する。

## Scope

- **In scope**: 患者予備能 + 慢性疾患から per-condition 重症度
  scale coupling (CKD、HF、肝硬変、心房細動、asthma、COPD、IHD 等)
  を伴う `PhysiologicalState` 初期化、`apply_state_delta` +
  `apply_coupling_rules` による in-place state 更新、新規入院時の
  `apply_disease_onset` shift、HbA1c 解決 (`hba1c_latent_at` が
  longitudinal latent を読み、`hba1c_from_glycemic_control` は
  protocol override / fallback path)、scenario / medication 起点の
  lab 上昇を単一 edit point で扱うための 2 flag helper
  `scenario_flags_from_protocol(protocol)` /
  `medication_flags_from_context(patient, medication_orders,
  admission_date, current_day)` (AD-57 J5 sibling pattern)、
  40 analyte をカバーする `derive_lab_values(**flags, …)`、
  `derive_vital_signs` (決定論 baseline + physiology delta)、
  `derive_observed_vitals` (circadian + 測定 noise 付与)、
  cross-module reflection 用 `canonical_state_vars()`。
- **Out of scope**: 時間軸 trajectory 選択
  ([`clinical_course`](../clinical_course/README.ja.md))、CIF に着地
  する観測値 ([`observation`](../observation/README.ja.md))、疾患定義
  ([`disease`](../disease/README.ja.md))、ordering 規則
  ([`order`](../order/README.ja.md))、FHIR emission
  ([`output`](../output/README.ja.md))。

## Public API

`__init__.py` は空。呼び出し側は `clinosim.modules.physiology.engine`
から直接 import:

```python
from clinosim.modules.physiology.engine import (
    # State
    initialize_state,                 # (profile, conditions, patient_id="") -> PhysiologicalState
    apply_state_delta,                # (state, var, delta) -> None (in place)
    apply_disease_onset,              # (state, severity, initial_impact, acid_base_type="metabolic") -> PhysiologicalState
    apply_coupling_rules,             # (state) -> None (in place)
    update,                           # (state, directive: StateChangeDirective, time_step: timedelta) -> PhysiologicalState
    canonical_state_vars,             # () -> frozenset[str]
    hba1c_from_glycemic_control,      # (glycemic_control) -> float (HbA1c %)
    hba1c_latent_at,                  # (patient, when) -> float | None (longitudinal HbA1c latent)
    clamp,                            # (value, lo, hi) -> float
    room_air_saturation,              # (state, baseline_spo2) -> float
    po2_from_saturation,              # (saturation_pct) -> float

    # Flag helper (AD-57 canonical single edit point)
    scenario_flags_from_protocol,     # (protocol) -> {"causes_X": bool, ...}
    medication_flags_from_context,    # (patient, medication_orders, admission_date, current_day) -> {"on_warfarin": bool, ...}

    # 導出
    derive_lab_values,                # (state, sex, age, has_diabetes=False, rng=None, hour=6, **flags,
                                      #  hba1c_latent=None) -> dict[analyte, float]
    derive_vital_signs,               # (state, baseline: BaselineVitals, timestamp) -> dict[str, float]
    derive_observed_vitals,           # (state, baseline: BaselineVitals, timestamp, rng) -> dict[str, float]
)
```

## 決定論

- `ENRICHER_SEED_OFFSETS` にサブ seed 未登録。physiology 関数は
  caller が渡す `rng` に対して純粋。encounter simulator
  (`daily_loop.py`, `inpatient.py`, `outpatient.py`, `emergency.py`,
  `unknown_condition.py`, `vitals_pipeline.py`) と `monitoring`
  enricher が呼び出し前に per-encounter / per-order のサブ RNG を
  導出する。
- **`PhysiologicalState` は `apply_state_delta` /
  `apply_coupling_rules` / `apply_disease_onset` / `update` によって
  in-place mutation される** (後 2 者は同じ instance を返す) —
  immutable ではない。決定論は決定論的 caller + 決定論的 `rng` から
  来るのであり、fresh instance を返す設計からではない。
- **Per-order lab RNG 分離 (AD-59)**: `derive_lab_values` は
  per-order サブ RNG (`clinosim/seeding.py` の
  `panel_specimen_seed` / `individual_lab_seed`) で呼ばれ、患者
  master RNG は使わない。新 lab を YAML に追加しても無関係な患者の
  stream が shift しない。

## 依存

- `clinosim.modules.physiology._coupling_coefficients` — 慢性疾患
  ごとの全 coupling 係数 (`CKD_RENAL_COUPLING`,
  `HF_CARDIAC_COUPLING`, `CIRRHOSIS_HEPATIC_COUPLING`,
  `IHD_CARDIAC_COUPLING` 等)。
- `clinosim.modules.physiology._lab_derivation_thresholds` —
  `derive_lab_values` の 40 analyte を形作る全 scalar 定数
  (baseline / coupling scale / physiologic min-max / noise SD)。
- `clinosim.modules.physiology._state_coupling_thresholds` —
  `apply_coupling_rules` が適用する coupling-rule 定数。
- `clinosim.modules.physiology._vital_signs_thresholds` — vital
  baseline coupling + noise SD 定数。
- `clinosim.modules.physiology.dehydration_thresholds` —
  dehydration 起点の BUN / hypernatremia lift を gate する
  `volume_status` 閾値 (Issue #561 canonical anchor)。
- `clinosim.modules.physiology.renal_thresholds` — 薬剤 hold /
  減量を gate する `renal_function` 閾値 (Issue #561 canonical
  anchor)。
- `reference_data/chronic_glycemic_thresholds.yaml` (HbA1c /
  glucose / acid-base scalar) と `reference_data/state_variable_ranges.yaml`
  (state 変数ごとの min / max)。いずれも `@cache` で 1 回 load。
- `clinosim.modules.longitudinal.engine` — `state_at`
  (`hba1c_latent_at` 内で遅延 import)。
- `clinosim.types.clinical` — `PhysiologicalState`,
  `StateChangeDirective`。
- `clinosim.types.patient` — `PatientPhysiologicalProfile`,
  `ChronicCondition`, `BaselineVitals`。
- `numpy` — `np.random.Generator`、`math` (exp / log coupling)。

## 定数と設定

- **Coupling 係数** ([`_coupling_coefficients.py`](_coupling_coefficients.py)、
  Issue #637 PR-B): `initialize_state` が使う慢性疾患 → state 軸の
  全 multiplier。(condition, axis) ごとに引用付きで命名
  (`CKD_RENAL_COUPLING`, `HF_SEVERE_VOLUME_COUPLING`,
  `CIRRHOSIS_COAGULATION_COUPLING`, `AFIB_CARDIAC_COUPLING` 等、
  `severity_score` が閾値を超えたときのみ発火する `*_SEVERE_THRESHOLD`
  split 込)。
- **Lab 導出式** ([`_lab_derivation_thresholds.py`](_lab_derivation_thresholds.py)、
  ~1085 LOC): `derive_lab_values` の全 analyte
  (albumin, ALT, AST, aPTT, BNP, BUN, creatinine, Hb, HbA1c, INR,
  K, lactate, LDL, Na, PT, PLT, WBC …) について baseline /
  coupling scale / physiologic min / max / noise SD 定数。
- **State-coupling 規則定数**
  ([`_state_coupling_thresholds.py`](_state_coupling_thresholds.py))
  — `apply_coupling_rules` が消費する定数 (18 変数の canonical state を臨床的に
  整合させるための軸間 clamp と shift)。
- **Vital 導出式** ([`_vital_signs_thresholds.py`](_vital_signs_thresholds.py))
  — `derive_vital_signs` / `derive_observed_vitals` の coupling +
  noise 定数 (HR, SBP, DBP, RR, SpO₂, 体温)。
- **症状軸** (`sympathetic_activation`, `pain_level`,
  `oxygenation_impairment`, `consciousness_impairment`、Issue #2052):
  vital への coupling と AVPU / pain score の尺度は
  [`_vital_signs_thresholds.py`](_vital_signs_thresholds.py)、OA の慢性疼痛
  baseline は [`_coupling_coefficients.py`](_coupling_coefficients.py)、
  血液ガス定数 (`LAB_REFERENCE_SAO2_PCT`、
  `PCO2_HYPOXIC_HYPERVENTILATION_MMHG`) は
  [`_lab_derivation_thresholds.py`](_lab_derivation_thresholds.py)。日次回復・
  慢性 floor・退院 / 酸素 / エスカレーション規則は [`SPEC.md`](SPEC.md) の
  "Symptom axes" にまとめている。
- **Dehydration 閾値** ([`dehydration_thresholds.py`](dehydration_thresholds.py)、
  Issue #561): モジュール全体で dehydration → BUN /
  hypernatremia 導出を gate する canonical `volume_status` 閾値。
- **Renal 閾値** ([`renal_thresholds.py`](renal_thresholds.py)、
  Issue #561): `medication_pipeline.py` + `discharge_rx.py` を通じて
  薬剤 hold / 減量を gate する canonical `renal_function` 閾値。
- **YAML data** ([`reference_data/`](reference_data/)):
  `chronic_glycemic_thresholds.yaml` (HbA1c / glucose / acid-base
  scalar) と `state_variable_ranges.yaml` (delta 駆動 state 変数ごとの
  min / max。未記載の変数は `(0.0, 1.0)`)。
- validator `_validate_complications_state_impact` +
  `_validate_initial_state_impact` (`engine.py`、protocol load 時に
  `disease/protocol.py` から呼ばれる) が非 canonical state 変数を
  参照する YAML entry を捕捉する。

## ディレクトリ構造

```
clinosim/modules/physiology/
  __init__.py                        空
  engine.py                          initialize_state / apply_* / derive_* / flag helper (~1340 LOC)
  _coupling_coefficients.py          慢性疾患ごとの coupling (Issue #637 PR-B)
  _lab_derivation_thresholds.py      analyte 式定数 (Issue #637)
  _state_coupling_thresholds.py      apply_coupling_rules 定数 (Issue #637)
  _vital_signs_thresholds.py         derive_vital_signs 定数 (Issue #637)
  dehydration_thresholds.py          canonical volume_status 閾値 (Issue #561)
  renal_thresholds.py                canonical renal_function 閾値 (Issue #561)
  reference_data/
    chronic_glycemic_thresholds.yaml HbA1c / glucose / acid-base scalar
    state_variable_ranges.yaml       state 変数ごとの min / max range
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` は存在しない** — physiology は
encounter simulator が直接呼び、`ModuleAuditSpec` も登録していない。

## Enricher 配線

該当なし — 本モジュールは encounter simulator が直接呼び、
`register_builtin_enrichers` には登録されない。`ENRICHER_SEED_OFFSETS`
にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | 入院時に `initialize_state`, `apply_disease_onset`, `apply_state_delta` を呼び出す。 |
| Emergency + outpatient | [`clinosim/simulator/{emergency,outpatient,unknown_condition}.py`](../../simulator/) | `initialize_state`、flag helper、`derive_lab_values` (+ `hba1c_latent_at`)。ED / 外来は `derive_observed_vitals`、ED は `apply_disease_onset` も。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | 入院 day ごとに `update` (内部で `apply_coupling_rules`) + `apply_state_delta` で state を進行し、flag helper + `derive_lab_values` で日次 lab を導出。 |
| Vitals pipeline | [`clinosim/simulator/vitals_pipeline.py`](../../simulator/vitals_pipeline.py) | `derive_observed_vitals` で vitals を emit。AVPU / pain 定数を `_vital_signs_thresholds.py` から読む。 |
| Medication pipeline | [`clinosim/simulator/medication_pipeline.py`](../../simulator/medication_pipeline.py) | `renal_thresholds` (`METFORMIN_*`) を参照して metformin hold を判定。 |
| Monitoring enricher | [`clinosim/modules/monitoring/enricher.py`](../monitoring/enricher.py) | 慢性薬 monitoring lab 用に flag helper + `derive_lab_values`。 |
| Health checkup | [`clinosim/modules/health_checkup/engine.py`](../health_checkup/engine.py) | `hba1c_latent_at`, `hba1c_from_glycemic_control`, `HBA1C_NONDM_BASE`。 |
| HAI lab lift | [`clinosim/modules/hai/lab_lift.py`](../hai/lab_lift.py) | `_lab_derivation_thresholds.py` の `WBC_*` 定数を再利用。 |
| Clinical course | [`clinosim/modules/clinical_course/engine.py`](../clinical_course/engine.py) | `canonical_state_vars`。 |
| Discharge rx | [`clinosim/simulator/discharge_rx.py`](../../simulator/discharge_rx.py) | 退院処方に対する同 renal-hold gate。 |
| Disease protocol 統合 | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | load 時に `_validate_*_state_impact` validator を呼ぶ。 |

## テスト

```bash
pytest tests/unit -k "physiology or i10_stage_physiology" -q
```

個別ファイル:

- [`tests/unit/test_physiology.py`](../../../tests/unit/test_physiology.py)
  — state 初期化 + 導出不変量。
- [`tests/unit/test_i10_stage_physiology.py`](../../../tests/unit/test_i10_stage_physiology.py)
  — I10 (高血圧) stage → physiology coupling の regression。

**coverage gap**: `derive_lab_values` の 40 analyte 導出は現状
per-analyte 単体 test ではなく integration test で end-to-end に
カバーしている。新 analyte 追加時は `test_physiology.py` を拡張し、
その analyte の baseline / coupling / clamp 定数が想定方向に発火する
focused check (audit-module の lift-firing-proof に相当) を加える。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
