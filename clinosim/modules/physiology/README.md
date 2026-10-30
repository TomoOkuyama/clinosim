# `clinosim.modules.physiology` — physiology-state engine + lab / vital derivation

## Purpose

Owns clinosim's hidden physiological state model — the axes that
downstream lab values, vital signs, and medication responses derive
from. Given a patient's `PatientPhysiologicalProfile` +
`ChronicCondition` list, `initialize_state` builds a
`PhysiologicalState`; `apply_state_delta` +
`apply_coupling_rules` advance it; `derive_lab_values` +
`derive_vital_signs` + `derive_observed_vitals` project it into
concrete lab / vital measurements at a moment in time. This is the
"realism core" — every clinical value seen outside is a projection
of this state.

Where [`clinical_course`](../clinical_course/README.md) decides
"how the state should move on the next day", `physiology` defines
"what the state means for this patient's labs and vitals right now"
and applies day-scale deltas requested by clinical_course.

## Scope

- **In scope**: `PhysiologicalState` initialisation from patient
  reserves + chronic conditions with per-condition severity-scaled
  coupling (CKD, HF, cirrhosis, atrial fib, asthma, COPD, IHD, …),
  in-place state update via `apply_state_delta` +
  `apply_coupling_rules`, `apply_disease_onset` shift on a new
  admission, HbA1c resolution (`hba1c_latent_at` reads the
  longitudinal latent; `hba1c_from_glycemic_control` is the
  protocol-override / fallback path), the two flag-derivation helpers
  `scenario_flags_from_protocol(protocol)` and
  `medication_flags_from_context(patient, medication_orders,
  admission_date, current_day)` — the canonical single edit points
  for scenario / medication-driven lab lifts (AD-57 sibling J5
  pattern), `derive_lab_values(**flags, …)` covering 40 analytes,
  `derive_vital_signs` (deterministic baseline + physiology delta),
  `derive_observed_vitals` (adds circadian + measurement noise),
  `canonical_state_vars()` for cross-module reflection.
- **Out of scope**: temporal trajectory selection
  ([`clinical_course`](../clinical_course/README.md)); the observed
  values as they land in CIF ([`observation`](../observation/README.md));
  disease definitions ([`disease`](../disease/README.md)); ordering
  rules ([`order`](../order/README.md)); FHIR emission
  ([`output`](../output/README.md)).

## Public API

`__init__.py` is empty; consumers import directly from
`clinosim.modules.physiology.engine`:

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

    # Flag helpers (AD-57 canonical single edit points)
    scenario_flags_from_protocol,     # (protocol) -> {"causes_X": bool, ...}
    medication_flags_from_context,    # (patient, medication_orders, admission_date, current_day) -> {"on_warfarin": bool, ...}

    # Derivations
    derive_lab_values,                # (state, sex, age, has_diabetes=False, rng=None, hour=6, **flags,
                                      #  hba1c_latent=None) -> dict[analyte, float]
    derive_vital_signs,               # (state, baseline: BaselineVitals, timestamp) -> dict[str, float]
    derive_observed_vitals,           # (state, baseline: BaselineVitals, timestamp, rng) -> dict[str, float]
)
```

## Determinism

- No sub-seed offset in `ENRICHER_SEED_OFFSETS`. Physiology functions
  are pure with respect to the `rng` the caller passes in; the
  encounter simulators (`daily_loop.py`, `inpatient.py`,
  `outpatient.py`, `emergency.py`, `unknown_condition.py`,
  `vitals_pipeline.py`) and the `monitoring` enricher each derive
  per-encounter / per-order sub-RNGs before calling.
- **`PhysiologicalState` is mutated in place** by
  `apply_state_delta`, `apply_coupling_rules`, `apply_disease_onset`
  and `update` (the latter two also return the same instance) — it is
  NOT immutable. Determinism comes from the deterministic caller +
  deterministic `rng`, not from returning fresh instances.
- **Per-order lab RNG isolation (AD-59)**: `derive_lab_values` is
  called with a per-order sub-RNG (via `clinosim/seeding.py`
  helpers `panel_specimen_seed` / `individual_lab_seed`), NOT the
  patient master RNG, so a YAML edit adding a new lab does not
  shift unrelated patients' streams.

## Dependencies

- `clinosim.modules.physiology._coupling_coefficients` — every
  per-chronic-condition coupling coefficient
  (`CKD_RENAL_COUPLING`, `HF_CARDIAC_COUPLING`,
  `CIRRHOSIS_HEPATIC_COUPLING`, `IHD_CARDIAC_COUPLING`, …).
- `clinosim.modules.physiology._lab_derivation_thresholds` — every
  scalar constant that shapes `derive_lab_values` for the 40
  analytes (baselines, coupling scales, physiologic min / max
  ranges, noise SDs).
- `clinosim.modules.physiology._state_coupling_thresholds` — the
  coupling-rule constants applied by `apply_coupling_rules`.
- `clinosim.modules.physiology._vital_signs_thresholds` — vital-sign
  baseline coupling + noise SD constants.
- `clinosim.modules.physiology.dehydration_thresholds` — the
  `volume_status` thresholds that gate dehydration-driven BUN /
  hypernatremia lifts (Issue #561 canonical anchor).
- `clinosim.modules.physiology.renal_thresholds` — the
  `renal_function` thresholds that gate medication holds / dose
  adjustments (Issue #561 canonical anchor).
- `reference_data/chronic_glycemic_thresholds.yaml` (HbA1c / glucose /
  acid-base scalars) and `reference_data/state_variable_ranges.yaml`
  (per-state-variable min / max), each loaded once via `@cache`.
- `clinosim.modules.longitudinal.engine` — `state_at` (lazy, inside
  `hba1c_latent_at`).
- `clinosim.types.clinical` — `PhysiologicalState`,
  `StateChangeDirective`.
- `clinosim.types.patient` — `PatientPhysiologicalProfile`,
  `ChronicCondition`, `BaselineVitals`.
- `numpy` — `np.random.Generator`, `math` for exponential /
  logarithmic couplings.

## Constants and configuration

- **Coupling coefficients** ([`_coupling_coefficients.py`](_coupling_coefficients.py),
  Issue #637 PR-B): every chronic-condition → state axis multiplier
  used by `initialize_state`. Named per (condition, axis) with
  citation (e.g. `CKD_RENAL_COUPLING`, `HF_SEVERE_VOLUME_COUPLING`,
  `CIRRHOSIS_COAGULATION_COUPLING`, `AFIB_CARDIAC_COUPLING`, plus
  `*_SEVERE_THRESHOLD` splits that fire only when
  `severity_score` crosses the threshold).
- **Lab-derivation formulae** ([`_lab_derivation_thresholds.py`](_lab_derivation_thresholds.py),
  ~1085 LOC): baseline / coupling-scale / physiologic-min / physiologic-max
  / noise-SD constants for every analyte in `derive_lab_values`
  (albumin, ALT, AST, aPTT, BNP, BUN, creatinine, Hb, HbA1c, INR,
  K, lactate, LDL, Na, PT, PLT, WBC, …).
- **State-coupling rule constants** ([`_state_coupling_thresholds.py`](_state_coupling_thresholds.py))
  — the constants `apply_coupling_rules` consumes (e.g. state-to-state
  clamps and shifts that keep the 18-variable canonical state clinically
  coherent when one axis moves).
- **Vital-signs formulae** ([`_vital_signs_thresholds.py`](_vital_signs_thresholds.py))
  — coupling + noise constants for `derive_vital_signs` /
  `derive_observed_vitals` (HR, SBP, DBP, RR, SpO₂, temperature).
- **Symptom axes** (`sympathetic_activation`, `pain_level`,
  `oxygenation_impairment`, `consciousness_impairment`; Issue #2052):
  vital couplings and AVPU / pain-score scales in
  [`_vital_signs_thresholds.py`](_vital_signs_thresholds.py), the OA pain
  baseline in [`_coupling_coefficients.py`](_coupling_coefficients.py),
  blood-gas constants (`LAB_REFERENCE_SAO2_PCT`,
  `PCO2_HYPOXIC_HYPERVENTILATION_MMHG`) in
  [`_lab_derivation_thresholds.py`](_lab_derivation_thresholds.py). Daily
  recovery, chronic floor, discharge / oxygen / escalation rules are
  summarised in [`SPEC.md`](SPEC.md) under "Symptom axes".
- **Dehydration thresholds** ([`dehydration_thresholds.py`](dehydration_thresholds.py),
  Issue #561): the canonical `volume_status` cutoffs that gate
  dehydration → BUN / hypernatremia derivation across the module.
- **Renal thresholds** ([`renal_thresholds.py`](renal_thresholds.py),
  Issue #561): the canonical `renal_function` cutoffs that gate
  medication holds and dose adjustments across
  `medication_pipeline.py` + `discharge_rx.py`.
- **YAML data** ([`reference_data/`](reference_data/)):
  `chronic_glycemic_thresholds.yaml` (HbA1c / glucose / acid-base
  scalars) and `state_variable_ranges.yaml` (min / max range per
  delta-driven state variable; unlisted variables default to
  `(0.0, 1.0)`).
- Validators `_validate_complications_state_impact` +
  `_validate_initial_state_impact` (in `engine.py`, called from
  `disease/protocol.py` at protocol load) catch YAML entries that
  reference non-canonical state variables.

## Directory contents

```
clinosim/modules/physiology/
  __init__.py                        empty
  engine.py                          initialize_state / apply_* / derive_* / flag helpers (~1340 LOC)
  _coupling_coefficients.py          per-chronic-condition coupling (Issue #637 PR-B)
  _lab_derivation_thresholds.py      analyte-formula constants (Issue #637)
  _state_coupling_thresholds.py      apply_coupling_rules constants (Issue #637)
  _vital_signs_thresholds.py         derive_vital_signs constants (Issue #637)
  dehydration_thresholds.py          canonical volume_status cutoffs (Issue #561)
  renal_thresholds.py                canonical renal_function cutoffs (Issue #561)
  reference_data/
    chronic_glycemic_thresholds.yaml HbA1c / glucose / acid-base scalars
    state_variable_ranges.yaml       per-state-variable min / max ranges
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `enricher.py` and no `audit.py`** — physiology
is called directly by every encounter simulator and no
`ModuleAuditSpec` is registered.

## Enricher wiring

Not applicable — this module is invoked directly by every encounter
simulator, not through `register_builtin_enrichers`. It has no seed
offset in `ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Calls `initialize_state`, `apply_disease_onset`, `apply_state_delta` at admission. |
| Emergency + outpatient | [`clinosim/simulator/{emergency,outpatient,unknown_condition}.py`](../../simulator/) | `initialize_state`, flag helpers, `derive_lab_values` (+ `hba1c_latent_at`); ED / outpatient also `derive_observed_vitals`, ED also `apply_disease_onset`. |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | Advances state per admission day via `update` (which runs `apply_coupling_rules`) + `apply_state_delta`; derives daily labs with the flag helpers + `derive_lab_values`. |
| Vitals pipeline | [`clinosim/simulator/vitals_pipeline.py`](../../simulator/vitals_pipeline.py) | Emits vitals via `derive_observed_vitals`; reads AVPU / pain constants from `_vital_signs_thresholds.py`. |
| Medication pipeline | [`clinosim/simulator/medication_pipeline.py`](../../simulator/medication_pipeline.py) | Consults `renal_thresholds` (`METFORMIN_*`) for metformin holds. |
| Monitoring enricher | [`clinosim/modules/monitoring/enricher.py`](../monitoring/enricher.py) | Flag helpers + `derive_lab_values` for chronic-med monitoring labs. |
| Health checkup | [`clinosim/modules/health_checkup/engine.py`](../health_checkup/engine.py) | `hba1c_latent_at`, `hba1c_from_glycemic_control`, `HBA1C_NONDM_BASE`. |
| HAI lab lift | [`clinosim/modules/hai/lab_lift.py`](../hai/lab_lift.py) | Re-uses the `WBC_*` constants from `_lab_derivation_thresholds.py`. |
| Clinical course | [`clinosim/modules/clinical_course/engine.py`](../clinical_course/engine.py) | `canonical_state_vars`. |
| Discharge rx | [`clinosim/simulator/discharge_rx.py`](../../simulator/discharge_rx.py) | Same renal-hold gate for discharge medication. |
| Disease protocol integration | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | Calls the `_validate_*_state_impact` validators at load. |

## Testing

```bash
pytest tests/unit -k "physiology or i10_stage_physiology" -q
```

Individual files:

- [`tests/unit/test_physiology.py`](../../../tests/unit/test_physiology.py)
  — state initialisation + derivation invariants.
- [`tests/unit/test_i10_stage_physiology.py`](../../../tests/unit/test_i10_stage_physiology.py)
  — I10 (hypertension) stage → physiology coupling regression.

Coverage gap: the 40 analyte derivations in `derive_lab_values` are
covered end-to-end via integration tests rather than per-analyte
unit tests today. When adding a new analyte, extend
`test_physiology.py` with a focused check that the analyte's
baseline / coupling / clamp constants fire the expected direction
(a lift-firing-proof analogue of the audit-module pattern).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
