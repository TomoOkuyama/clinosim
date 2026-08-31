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
  admission, HbA1c derivation from glycemic control
  (`hba1c_from_glycemic_control`), the two flag-derivation helpers
  `scenario_flags_from_protocol(protocol)` and
  `medication_flags_from_context(patient, medication_orders,
  admission_date, current_day)` — the canonical single edit points
  for scenario / medication-driven lab lifts (AD-57 sibling J5
  pattern), `derive_lab_values(**flags, …)` covering ~30 analytes,
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
    apply_disease_onset,              # (state, disease, severity, rng) -> None
    apply_coupling_rules,             # (state) -> None (in place)
    update,                           # per-day advance (state, ...) -> None
    canonical_state_vars,             # () -> frozenset[str]
    hba1c_from_glycemic_control,      # (glycemic_control) -> HbA1c
    clamp,                            # (value, lo, hi) -> float

    # Flag helpers (AD-57 canonical single edit points)
    scenario_flags_from_protocol,     # (protocol) -> {"causes_X": bool, ...}
    medication_flags_from_context,    # (patient, medication_orders, admission_date, current_day) -> {"on_warfarin": bool, ...}

    # Derivations
    derive_lab_values,                # (state, rng, **flags) -> dict[analyte, value]
    derive_vital_signs,               # (state, patient, rng) -> BaselineVitals
    derive_observed_vitals,           # (state, patient, ts, rng) -> ObservedVitals
)
```

## Determinism

- No sub-seed offset in `ENRICHER_SEED_OFFSETS`. Physiology functions
  are pure with respect to the `rng` the caller passes in; the
  encounter simulators (`daily_loop.py`, `inpatient.py`,
  `outpatient.py`, `emergency.py`, `vitals_pipeline.py`,
  `medication_pipeline.py`) each derive per-encounter / per-order
  sub-RNGs before calling.
- **`PhysiologicalState` is mutated in place** by
  `apply_state_delta` and `apply_coupling_rules` — it is NOT
  immutable. Determinism comes from the deterministic caller +
  deterministic `rng`, not from returning fresh instances.
- **Per-order lab RNG isolation (AD-59)**: `derive_lab_values` is
  called with a per-order sub-RNG (via `simulator/seeding.py`
  helpers `panel_specimen_seed` / `individual_lab_seed`), NOT the
  patient master RNG, so a YAML edit adding a new lab does not
  shift unrelated patients' streams.

## Dependencies

- `clinosim.modules.physiology._coupling_coefficients` — every
  per-chronic-condition coupling coefficient
  (`CKD_RENAL_COUPLING`, `HF_CARDIAC_COUPLING`,
  `CIRRHOSIS_HEPATIC_COUPLING`, `IHD_CARDIAC_COUPLING`, …).
- `clinosim.modules.physiology._lab_derivation_thresholds` — every
  scalar constant that shapes `derive_lab_values` for the ~30
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
- `clinosim.types.clinical` — `PhysiologicalState` dataclass.
- `clinosim.types.patient` — `PatientPhysiologicalProfile`,
  `ChronicCondition`.
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
  ~966 LOC): baseline / coupling-scale / physiologic-min / physiologic-max
  / noise-SD constants for every analyte in `derive_lab_values`
  (albumin, ALT, AST, aPTT, BNP, BUN, creatinine, Hb, HbA1c, INR,
  K, lactate, LDL, Na, PT, PLT, WBC, …).
- **State-coupling rule constants** ([`_state_coupling_thresholds.py`](_state_coupling_thresholds.py))
  — the constants `apply_coupling_rules` consumes (e.g. state-to-state
  clamps and shifts that keep the 14-variable state clinically
  coherent when one axis moves).
- **Vital-signs formulae** ([`_vital_signs_thresholds.py`](_vital_signs_thresholds.py))
  — coupling + noise constants for `derive_vital_signs` /
  `derive_observed_vitals` (HR, SBP, DBP, RR, SpO₂, temperature).
- **Dehydration thresholds** ([`dehydration_thresholds.py`](dehydration_thresholds.py),
  Issue #561): the canonical `volume_status` cutoffs that gate
  dehydration → BUN / hypernatremia derivation across the module.
- **Renal thresholds** ([`renal_thresholds.py`](renal_thresholds.py),
  Issue #561): the canonical `renal_function` cutoffs that gate
  medication holds and dose adjustments across
  `medication_pipeline.py` + `discharge_rx.py`.
- Import-time validators `_validate_complications_state_impact` +
  `_validate_initial_state_impact` (in `engine.py`) catch YAML
  entries that reference non-canonical state variables.

## Directory contents

```
clinosim/modules/physiology/
  __init__.py                        empty
  engine.py                          initialize_state / apply_* / derive_* / flag helpers (1116 LOC)
  _coupling_coefficients.py          per-chronic-condition coupling (Issue #637 PR-B)
  _lab_derivation_thresholds.py      analyte-formula constants (Issue #637)
  _state_coupling_thresholds.py      apply_coupling_rules constants (Issue #637)
  _vital_signs_thresholds.py         derive_vital_signs constants (Issue #637)
  dehydration_thresholds.py          canonical volume_status cutoffs (Issue #561)
  renal_thresholds.py                canonical renal_function cutoffs (Issue #561)
  SPEC.md                            extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`, no
`reference_data/`** — physiology is called directly by every
encounter simulator, has no YAML data, and no `ModuleAuditSpec` is
registered.

## Enricher wiring

Not applicable — this module is invoked directly by every encounter
simulator, not through `register_builtin_enrichers`. It has no seed
offset in `ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Inpatient encounter | [`clinosim/simulator/inpatient.py`](../../simulator/inpatient.py) | Calls `initialize_state`, `derive_lab_values`, `derive_vital_signs` at admission + daily rounds. |
| Emergency + outpatient | [`clinosim/simulator/{emergency,outpatient,unknown_condition}.py`](../../simulator/) | Same at ED / outpatient tier (no daily loop). |
| Daily loop | [`clinosim/simulator/daily_loop.py`](../../simulator/daily_loop.py) | Advances state (`update`) per admission day + applies coupling rules. |
| Vitals pipeline | [`clinosim/simulator/vitals_pipeline.py`](../../simulator/vitals_pipeline.py) | Emits vitals via `derive_observed_vitals` with per-order sub-RNG. |
| Medication pipeline | [`clinosim/simulator/medication_pipeline.py`](../../simulator/medication_pipeline.py) | Consults `renal_thresholds` for dose holds. |
| Discharge rx | [`clinosim/simulator/discharge_rx.py`](../../simulator/discharge_rx.py) | Same renal-hold gate for discharge medication. |
| Disease protocol integration | [`clinosim/modules/disease/protocol.py`](../disease/protocol.py) | Cross-refers state impact tokens (validated at load). |
| Patient activation | [`clinosim/modules/patient/activator.py`](../patient/activator.py) | Uses `hba1c_from_glycemic_control`. |

## Testing

```bash
pytest tests/unit -k "physiology or i10_stage_physiology" -q
```

Individual files:

- [`tests/unit/test_physiology.py`](../../../tests/unit/test_physiology.py)
  — state initialisation + derivation invariants.
- [`tests/unit/test_i10_stage_physiology.py`](../../../tests/unit/test_i10_stage_physiology.py)
  — I10 (hypertension) stage → physiology coupling regression.

Coverage gap: the ~30 analyte derivations in `derive_lab_values` are
covered end-to-end via integration tests rather than per-analyte
unit tests today. When adding a new analyte, extend
`test_physiology.py` with a focused check that the analyte's
baseline / coupling / clamp constants fire the expected direction
(a lift-firing-proof analogue of the audit-module pattern).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
