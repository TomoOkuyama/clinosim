# AKI Creatinine / DKA HCO3 surgical calibration (state-unchanged)

Date: 2026-06-22

## Problem

The simulator's admit-day labs for two acute conditions are clinically too extreme,
landing outside the established KDIGO / ADA severity bands:

- **AKI**: admit Creatinine median ≈ 8 mg/dL (ESRD / dialysis territory). Real KDIGO 1-3
  AKI admit Cr is 1.5-6 mg/dL (median ≈ 2.5-4).
- **DKA moderate**: admit HCO3 median ≈ 17.4 mEq/L (mild metabolic acidosis). ADA moderate
  DKA HCO3 is 10-15 mEq/L (the cutoff between mild and moderate).

A prior WIP attempt (`eda694c2`) tried to fix this by **reducing the AKI/DKA
`initial_state_impact` on `state.renal_function` / `state.ph_status`**. While the per-AKI/DKA
labs landed in the right ranges, a follow-up byte-diff vs `master` (same seed, US p=2000)
revealed an unintended large-scale cascade:

| Resource (US, p=2000) | Master | WIP branch | Patient delta |
|-----------------------|--------|------------|---------------|
| Patient.ndjson        | 1274 patients | 1299 patients | 214 master-only / 239 branch-only |
| Observation.ndjson    | baseline | +3.46 MB | 1509 non-AKI/DKA patients differ |
| MedicationAdministration | baseline | +727 KB | 104 patients differ |
| Encounter             | baseline | +90 KB | 1508 non-AKI/DKA patients differ |
| MedicationRequest     | baseline | +196 KB | 1100 non-AKI/DKA patients differ |

Only **1 AKI patient** and **0 DKA patients** existed in either run at this population
size; yet the **patient cohort itself shifted** (chronic-condition prefix counts:
E78 6347 vs 6357, M17 1328 vs 1373, etc.). The JP run, by contrast, was almost
byte-identical (only 12 patient Observations changed, all other NDJSON identical).

### Root cause: clinical_course shared-RNG cascade

`clinical_course/engine.py` (`evaluate_complications`) is the cascade vector:

```python
# line 234-241
for rf in comp.get("risk_factors", []):
    if _evaluate_risk_condition(condition, state, patient, day):
        prob *= mult
if rng.random() < prob:
    active_complications.add(name)
    triggered.append(comp)
```

`_evaluate_risk_condition` reads `state.renal_function < X`, `state.ph_status < X`, etc.
The `rng.random()` call itself consumes 1 draw regardless of outcome — but **the side
effects of a triggered complication** (state_impact, action prescriptions, extra
lab/medication orders) consume *additional* RNG draws that an un-triggered complication
does not. Because `clinical_course` operates on the **shared master RNG stream**, a
single patient's altered complication trajectory shifts every subsequent patient's
draws — including population generation downstream.

This is the same pattern the project hit in:

- **#62 (sepsis SBP)**: state-driven perfusion change cascaded → adopted observation-time
  surgical fix on `derive_vital_signs` instead.
- **BNP HF specificity (#28)**: BNP formula was modified to be state-conditional on
  `state.volume_status > 0 AND cardiac < full`, without mutating any state.

## Approach: BNP-pattern surgical lab-formula fix

Keep `state.renal_function` and `state.ph_status` exactly as `master` produces them
(YAML `initial_state_impact` unchanged from `master`). Modify only the lab-derivation
formulas in `derive_lab_values()` so they map the *existing* extreme states to
clinically realistic Cr / HCO3 values.

Because `state` does not change, `clinical_course` branches identically to `master` and
**no patient-cohort cascade occurs**.

### Changes (only in `clinosim/modules/physiology/engine.py::derive_lab_values`)

**Creatinine** (line 252-254, low-renal branch):

```diff
 if renal > 0.5:
     labs["Creatinine"] = base_cr / renal
 else:
-    labs["Creatinine"] = base_cr / 0.5 + (0.5 - renal) * 15
+    # The low-renal slope was tuned to push severe AKI into the ESRD range (Cr ~9 at
+    # renal=0). Real KDIGO 3 admit Cr is ~5-6 and CKD3 (renal~0.3) is ~2.5, not ~5.
+    # 6.5 lands severe AKI at Cr ~5 and CKD3 at Cr ~2.75 without touching state.
+    labs["Creatinine"] = base_cr / 0.5 + (0.5 - renal) * 6.5
```

Mapping check (base_cr = 0.9, male):

| `state.renal_function` | Master Cr | New Cr | Clinical band |
|------------------------|-----------|--------|---------------|
| 0.0 (severe AKI, anuric state) | 9.3 | 5.05 | KDIGO 3 mid-high |
| 0.1                    | 7.8       | 4.40 | KDIGO 3 |
| 0.2                    | 6.3       | 3.75 | KDIGO 2 |
| 0.3 (CKD3)             | 4.8       | 3.10 | CKD3 typical |
| 0.4                    | 3.3       | 2.45 | early CKD |
| 0.5 (baseline)         | 1.80      | 1.80 | unchanged (continuous) |

The CKD-side improvement is a side benefit, not a goal: `master` was overestimating
CKD3 Cr too. The new coefficient lands both AKI and CKD into clinically published bands.

**HCO3** (line 320, metabolic axis):

```diff
-hco3 = 24.0 + ph * mf * 24.0   # metabolic load drives bicarbonate
+# The metabolic axis gain was tuned for a milder DKA profile. Real ADA moderate DKA
+# HCO3 is 10-15 mEq/L; master's `ph_status = -0.35` lands HCO3 at 15.6, just outside
+# the moderate band. 31.0 lands moderate DKA at HCO3 ~13 (mid-band).
+hco3 = 24.0 + ph * mf * 31.0   # metabolic load drives bicarbonate
```

Mapping check (`respiratory_fraction = 0`, `mf = 1`):

| `state.ph_status` | Master HCO3 | New HCO3 | Clinical band |
|-------------------|-------------|----------|---------------|
| -0.10 (CKD chronic) | 21.6 | 20.9 | mild metabolic, mostly unchanged |
| -0.15 (sepsis)    | 20.4 | 19.35 | mild metabolic, slight deepening |
| -0.35 (DKA mod)   | 15.6 | 13.15 | **ADA moderate (10-15)** |
| -0.60 (DKA sev)   | 9.6  | 5.40 | **ADA severe (<10)** |
| 0 (no disturbance) | 24 | 24 | unchanged |

The Winter's respiratory-compensation block (line 322-325) reads `hco3` after this
line, so pCO2 / pH will follow the new HCO3 automatically. No separate Winter's tweak
needed.

### What is NOT changed

- `acute_kidney_injury.yaml`, `diabetic_ketoacidosis.yaml` — `initial_state_impact`
  reverts to master values.
- `_variable_range("renal_function")` — stays at `(0.0, 1.0)` (master). The 0.05 floor
  in `initialize_state` line 79 and `apply_coupling_rules` line 176 already exists for
  the chronic / dynamic paths; only the disease-onset clamp tolerates a brief excursion
  to 0, which is fine for an acute snapshot.
- All other diseases — their `state` and their derived non-Cr / non-HCO3 labs are
  unchanged.
- BUN / K / eGFR formulas — they share `renal` but their clinical ranges already match
  `master` reasonably (BUN 150 at severe AKI, K 6.2 at severe AKI, eGFR 0 at anuric).
  No change.
- pH formula — recomputes from the new HCO3 + pCO2 via Henderson-Hasselbalch, so DKA
  moderate pH drifts from ~7.30 (master) to ~7.26 (new). Still inside the loose
  KDIGO/ADA `≤ 7.27` bound and improves directional realism.

## Trade-offs

1. **State / lab semantic drift**: `state.renal_function = 0` continues to mean
   "anuric" for coupling rules / clinical_course, but the lab now reads Cr ~5 (KDIGO 3,
   not ESRD). The same kind of drift was already present in `master` (state semantics
   are abstract magnitudes; labs map them to clinical numbers); this PR widens that gap
   slightly for the AKI case. Documented as a known limitation of the BNP-pattern path.

2. **Global Observation byte-diff vs master**: Every patient with `renal < 0.5` or
   non-zero `ph_status` will have a different Cr / HCO3 / pH in their Observation
   output. This is the expected and intended surgical change. Other resources (Patient,
   Encounter, MedAdmin, Condition, etc.) must remain **identical** to master, by the
   same byte-diff invariant #62 and BNP exercised.

3. **CKD3 Cr also shifts** (4.8 → 2.75). This is a side benefit per published CKD3
   ranges, not a regression. Should be documented in the data-quality audit report.

## Validation criteria (acceptance)

### Invariant: no clinical_course cascade

Generate `master` vs branch at fixed seed (US -p8000, JP -p4000):

- **Patient.ndjson, Encounter.ndjson, Condition.ndjson, MedicationAdministration.ndjson,
  MedicationRequest.ndjson, Immunization.ndjson, FamilyMemberHistory.ndjson,
  Specimen.ndjson, DiagnosticReport.ndjson, Procedure.ndjson, AllergyIntolerance.ndjson,
  Coverage.ndjson (JP)**: must be **byte-identical** to master.
- **Observation.ndjson**: differs only in Cr / HCO3 / pH numerical values; resource
  ids and structure unchanged.

Failure of any "must be byte-identical" file means the fix is leaking state somehow
and the PR cannot ship.

### Calibration target

- AKI cohort admit Cr median ∈ [2.0, 6.0] (KDIGO 1-3 envelope), with CKD-excluded
  subgroup median ∈ [2.0, 5.0].
- DKA moderate cohort admit HCO3 median ∈ [10, 15] (ADA moderate band).
- DKA severe cohort admit HCO3 median ≤ 10.

Coefficients (Cr `6.5`, HCO3 `31.0`) are first-order analytical picks. A small
re-tune (e.g. `6` or `7` for Cr) is acceptable if the post-implementation audit lands
just outside the band. The audit IS the source of truth; the spec value is a starting
point.

### Test plan

1. **Unit (`tests/unit/test_physiology.py`)**:
   - `test_aki_creatinine_not_anuric_on_elderly_baseline`: keep but recompute the
     ceilings against the new formula. With `renal_reserve = 0.60` and master AKI
     impacts (-0.25 / -0.45 / -0.65), end state = 0.35 / 0.15 / 0.0 → Cr = 2.78 / 4.08
     / 5.05. Ceilings shift from `(3.0, 5.0, 6.5)` to `(3.0, 4.5, 5.5)`.
   - `test_dka_moderate_acidosis_in_clinical_range`: keep; assertion `10 ≤ HCO3 ≤ 15`
     still holds for `state.ph_status = -0.35 * mf` → HCO3 = 13.15.
   - Drop `test_renal_function_clamp_floor_via_onset` (the WIP-only floor invariant
     test) — the floor change is no longer part of this PR.
   - Add `test_creatinine_curve_matches_clinical_bands` pinning the (renal → Cr) table
     above (regression guard for accidental re-steepening).
   - Add `test_hco3_metabolic_axis_matches_ada_bands` pinning the (ph_status → HCO3)
     table.

2. **Integration**: existing `tests/integration/` should pass unchanged. The lab-value
   integration tests must not assert exact Cr / HCO3 magnitudes outside the new bands.

3. **e2e**: 39/39 expected to pass. The golden patient (pneumonia) doesn't depend on
   Cr / HCO3 magnitudes, so `test_alpha_golden.py` is unaffected.

4. **Byte-diff (gold criterion)**: as defined above.

5. **Audit**: generate US -p10000 / JP -p6000, run `/tmp/audit_admit.py`
   (regenerate if `/tmp` is volatile) and compare admit-day Cr / HCO3 medians /
   percentiles to clinical bands.

## Out of scope

- Refactoring `clinical_course/engine.py` to use per-patient sub-seeds (architectural
  fix that would also unblock state-changing physiology calibrations). Logged as a
  follow-up architecture backlog item.
- Adjusting BUN / K / eGFR / Lactate formulas. They're "OK" in master under current
  state inputs and changing them is out of this PR's scope.
- DKA pH cutoff (≤ 7.0 for severe). Master pH already lands ~7.05 for `ph_status =
  -0.60`; the new HCO3 mult pulls it slightly lower, still within ADA severe band.
- Improving the AKI / DKA YAML severity_distribution shape. This PR keeps it at master.

## Risks

- **Coefficient miscalibration**: if the post-implementation audit shows Cr / HCO3
  outside target bands, tweak the coefficient (single-number edit) and re-audit.
  Cheap to iterate.
- **Hidden state dependency in non-derive_lab_values path**: a non-zero probability
  that some module other than `clinical_course` reads `renal_function` / `ph_status`
  in a way that materially differs from master's behavior. Mitigation: the byte-diff
  invariant catches this — any "must be byte-identical" file that drifts is the smoking
  gun.
- **DKA pH lower bound**: aggressive HCO3 gain (31.0) at very negative ph_status could
  push pH below the `6.80` clamp floor and the `≤ 7.0` ADA severe boundary. The
  Henderson-Hasselbalch + Winter's compensation chain is non-linear; check the audit.
  Easy to soften coefficient if needed.
