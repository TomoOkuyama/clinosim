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

[`clinical_course`](../clinical_course/README.md) は「翌日 state を
どう動かすか」を決定するのに対し、`physiology` は「その state が
現時点の患者 lab / vital にとって何を意味するか」を定義し、
clinical_course が要求する day-scale delta を適用する。

## Scope

- **In scope**: 患者予備能 + 慢性疾患から per-condition 重症度
  scale coupling (CKD、HF、肝硬変、心房細動、asthma、COPD、IHD 等)
  を伴う `PhysiologicalState` 初期化、`apply_state_delta` +
  `apply_coupling_rules` による in-place state 更新、新規入院時の
  `apply_disease_onset` shift、glycemic_control からの HbA1c 導出
  (`hba1c_from_glycemic_control`)、scenario / medication 起点の
  lab 上昇を単一 edit point で扱うための 2 flag helper
  `scenario_flags_from_protocol(protocol)` /
  `medication_flags_from_context(patient, medication_orders,
  admission_date, current_day)` (AD-57 J5 sibling pattern)、
  ~30 analyte をカバーする `derive_lab_values(**flags, …)`、
  `derive_vital_signs` (決定論 baseline + physiology delta)、
  `derive_observed_vitals` (circadian + 測定 noise 付与)、
  cross-module reflection 用 `canonical_state_vars()`。
- **Out of scope**: 時間軸 trajectory 選択
  ([`clinical_course`](../clinical_course/README.md))、CIF に着地
  する観測値 ([`observation`](../observation/README.md))、疾患定義
  ([`disease`](../disease/README.md))、ordering 規則
  ([`order`](../order/README.md))、FHIR emission
  ([`output`](../output/README.md))。

## Public API

`__init__.py` は空。呼び出し側は `clinosim.modules.physiology.engine`
から直接 import:

```python
from clinosim.modules.physiology.engine import (
    # State
    initialize_state,                 # (profile, conditions, patient_id="") -> PhysiologicalState
    apply_state_delta,                # (state, var, delta) -> None (in place)
    apply_disease_onset,              # (state, disease, severity, rng) -> None
    apply_coupling_rules,             # (state) -> None (in place)
    update,                           # per-day 進行 (state, ...) -> None
    canonical_state_vars,             # () -> frozenset[str]
    hba1c_from_glycemic_control,      # (glycemic_control) -> HbA1c
    clamp,                            # (value, lo, hi) -> float

    # Flag helper (AD-57 canonical single edit point)
    scenario_flags_from_protocol,     # (protocol) -> {"causes_X": bool, ...}
    medication_flags_from_context,    # (patient, medication_orders, admission_date, current_day) -> {"on_warfarin": bool, ...}

    # 導出
    derive_lab_values,                # (state, rng, **flags) -> dict[analyte, value]
    derive_vital_signs,               # (state, patient, rng) -> BaselineVitals
    derive_observed_vitals,           # (state, patient, ts, rng) -> ObservedVitals
)
```

## 決定論

- `ENRICHER_SEED_OFFSETS` にサブ seed 未登録。physiology 関数は
  caller が渡す `rng` に対して純粋。encounter simulator
  (`daily_loop.py`, `inpatient.py`, `outpatient.py`, `emergency.py`,
  `vitals_pipeline.py`, `medication_pipeline.py`) が呼び出し前に
  per-encounter / per-order のサブ RNG を導出する。
- **`PhysiologicalState` は `apply_state_delta` /
  `apply_coupling_rules` によって in-place mutation される** —
  immutable ではない。決定論は決定論的 caller + 決定論的 `rng` から
  来るのであり、fresh instance を返す設計からではない。
- **Per-order lab RNG 分離 (AD-59)**: `derive_lab_values` は
  per-order サブ RNG (`simulator/seeding.py` の
  `panel_specimen_seed` / `individual_lab_seed`) で呼ばれ、患者
  master RNG は使わない。新 lab を YAML に追加しても無関係な患者の
  stream が shift しない。

## 依存

- `clinosim.modules.physiology._coupling_coefficients` — 慢性疾患
  ごとの全 coupling 係数 (`CKD_RENAL_COUPLING`,
  `HF_CARDIAC_COUPLING`, `CIRRHOSIS_HEPATIC_COUPLING`,
  `IHD_CARDIAC_COUPLING` 等)。
- `clinosim.modules.physiology._lab_derivation_thresholds` —
  `derive_lab_values` の ~30 analyte を形作る全 scalar 定数
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
- `clinosim.types.clinical` — `PhysiologicalState` dataclass。
- `clinosim.types.patient` — `PatientPhysiologicalProfile`,
  `ChronicCondition`。
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
  ~966 LOC): `derive_lab_values` の全 analyte
  (albumin, ALT, AST, aPTT, BNP, BUN, creatinine, Hb, HbA1c, INR,
  K, lactate, LDL, Na, PT, PLT, WBC …) について baseline /
  coupling scale / physiologic min / max / noise SD 定数。
- **State-coupling 規則定数**
  ([`_state_coupling_thresholds.py`](_state_coupling_thresholds.py))
  — `apply_coupling_rules` が消費する定数 (14 変数 state を臨床的に
  整合させるための軸間 clamp と shift)。
- **Vital 導出式** ([`_vital_signs_thresholds.py`](_vital_signs_thresholds.py))
  — `derive_vital_signs` / `derive_observed_vitals` の coupling +
  noise 定数 (HR, SBP, DBP, RR, SpO₂, 体温)。
- **Dehydration 閾値** ([`dehydration_thresholds.py`](dehydration_thresholds.py)、
  Issue #561): モジュール全体で dehydration → BUN /
  hypernatremia 導出を gate する canonical `volume_status` 閾値。
- **Renal 閾値** ([`renal_thresholds.py`](renal_thresholds.py)、
  Issue #561): `medication_pipeline.py` + `discharge_rx.py` を通じて
  薬剤 hold / 減量を gate する canonical `renal_function` 閾値。
- Import 時 validator `_validate_complications_state_impact` +
  `_validate_initial_state_impact` (`engine.py`) が非 canonical
  state 変数を参照する YAML entry を捕捉する。

## ディレクトリ構造

```
clinosim/modules/physiology/
  __init__.py                        空
  engine.py                          initialize_state / apply_* / derive_* / flag helper (1116 LOC)
  _coupling_coefficients.py          慢性疾患ごとの coupling (Issue #637 PR-B)
  _lab_derivation_thresholds.py      analyte 式定数 (Issue #637)
  _state_coupling_thresholds.py      apply_coupling_rules 定数 (Issue #637)
  _vital_signs_thresholds.py         derive_vital_signs 定数 (Issue #637)
  dehydration_thresholds.py          canonical volume_status 閾値 (Issue #561)
  renal_thresholds.py                canonical renal_function 閾値 (Issue #561)
  SPEC.md                            拡張設計参考 (runtime data ではない)
```

**`enricher.py` / `audit.py` / `reference_data/` は存在しない** —
physiology は encounter simulator が直接呼び、YAML data は持たず、
`ModuleAuditSpec` も登録していない。

## Enricher 配線

該当なし — 本モジュールは encounter simulator が直接呼び、
`register_builtin_enrichers` には登録されない。`ENRICHER_SEED_OFFSETS`
にも seed 未登録。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | 入院時 + 日次回診で `initialize_state`, `derive_lab_values`, `derive_vital_signs` を呼び出す。 |
| Emergency + outpatient | [`clinosim/simulator/{emergency,outpatient,unknown_condition}.py`](../../simulator/) | ED / 外来 tier で同様 (日次 loop なし)。 |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | 入院 day ごとに state を進行 (`update`) し coupling 規則を適用。 |
| Vitals pipeline | [`clinosim/simulator/vitals_pipeline.py`](../../simulator/vitals_pipeline.py) | per-order サブ RNG で `derive_observed_vitals` を emit。 |
| Medication pipeline | [`clinosim/simulator/medication_pipeline.py`](../../simulator/medication_pipeline.py) | `renal_thresholds` を参照して dose hold を判定。 |
| Discharge rx | [`clinosim/simulator/discharge_rx.py`](../../simulator/discharge_rx.py) | 退院処方に対する同 renal-hold gate。 |
| Disease protocol 統合 | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | state impact token を cross-ref (load 時 validate)。 |
| Patient 活性化 | [`clinosim/modules/patient/activator.py`](../patient/activator.py) | `hba1c_from_glycemic_control` を使用。 |

## テスト

```bash
pytest tests/unit -k "physiology or i10_stage_physiology" -q
```

個別ファイル:

- [`tests/unit/test_physiology.py`](../../../tests/unit/test_physiology.py)
  — state 初期化 + 導出不変量。
- [`tests/unit/test_i10_stage_physiology.py`](../../../tests/unit/test_i10_stage_physiology.py)
  — I10 (高血圧) stage → physiology coupling の regression。

**coverage gap**: `derive_lab_values` の ~30 analyte 導出は現状
per-analyte 単体 test ではなく integration test で end-to-end に
カバーしている。新 analyte 追加時は `test_physiology.py` を拡張し、
その analyte の baseline / coupling / clamp 定数が想定方向に発火する
focused check (audit-module の lift-firing-proof に相当) を加える。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
