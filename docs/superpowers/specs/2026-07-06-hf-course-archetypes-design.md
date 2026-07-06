# FP-ARCH-1 — heart_failure_exacerbation course_archetypes + complications — design

Date: 2026-07-06
Status: approved (recon-grounded authoring), no architecture change
Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` FP-ARCH-1
Goal linkage: closes a C3 (missing-structure) instance — HF has no `course_archetypes`
so it falls back to the generic infection/inflammation-tuned trajectories, which are
clinically wrong for a volume-driven decompensated-HF course.

## Background

`heart_failure_exacerbation` (and 8 trauma/fracture diseases) lack a `course_archetypes`
block, so `select_archetype` uses `_FALLBACK_PROBABILITIES` and `get_daily_directive`
uses `_FALLBACK_TRAJECTORIES` (inflammation-centric). HF is the highest-value gap: its
course is diuresis-driven (volume_status down, cardiac_function up), not inflammation.
It also lacks a `complications` block (no cardiorenal AKI / arrhythmia / cardiogenic
shock events → ICU transfer under-fires). Engine reads these YAML blocks already; this
is pure authoring, no code change.

## Clinical basis (grounding the trajectories)

- `initial_state_impact` (moderate) pushes `volume_status +0.5`, `cardiac_function -0.25`,
  `perfusion_status -0.1`, `renal_function -0.05`, `inflammation_level +0.15`. Recovery =
  reversing these; the KEY axis is diuresis (`volume_status` toward 0) with cardiac recovery.
- `outcome_benchmarks`: readmission 0.22-0.23, ICU transfer 0.12 (JP), mortality 0.04-0.06.
- Recognized trajectory state vars (engine): anemia_level, cardiac_function,
  coagulation_status, glucose_status, hepatic_function, inflammation_level,
  perfusion_status, ph_status, renal_function, volume_status. (NOTE: HF's
  `initial_state_impact` uses `sodium_status`, which is NOT recognized and is silently
  dropped — a separate latent issue, filed as a follow-up, not fixed here.)

## Design — 6 archetypes (canonical names, volume/cardiac focused)

| archetype | prob | clinical shape |
|---|---|---|
| smooth_recovery | 0.42 | steady diuresis: volume_status ↓, cardiac_function ↑, perfusion ↑ |
| dip_then_recovery | 0.18 | early cardiorenal worsening (renal ↓, volume ↑) then diuresis |
| plateau_then_recovery | 0.13 | slow diuretic response, plateau days 0-3 then diuresis (order_mod: BNP/renal recheck day 3) |
| treatment_resistant | 0.13 | diuretic-resistant: slow volume ↓, order_mod day 3 (add BNP, renal panel), reflects escalation |
| gradual_deterioration | 0.09 | progressive pump failure: volume stays high, cardiac ↓, perfusion ↓, renal ↓ (→ ICU via complication) |
| sudden_deterioration | 0.05 | flash pulmonary edema / arrhythmia: sharp perfusion + cardiac drop day 2-3 |

Trajectory deltas are per-day directional (engine interpolates between listed days over
the LOS). Magnitudes kept modest and physiologically coherent with the onset impact.
`daily_trajectory` (Japanese SOAP narrative) is OPTIONAL and deferred — absence falls back
to the generic SOAP; the physiology-trajectory fix is the primary C3 closure here.

## Complications

- `acute_kidney_injury` (cardiorenal syndrome): probability_per_day ~0.02, risk
  severity_severe ×3 / age_over_75 ×1.5, state_impact renal_function -0.05; actions:
  order renal panel.
- `atrial_fibrillation_rvr`: probability_per_day ~0.015; state_impact cardiac_function
  -0.03, perfusion_status -0.03; actions: order ECG, rate control.
- `cardiogenic_shock`: probability_per_day ~0.004, risk severity_severe ×5; state_impact
  perfusion_status -0.15, cardiac_function -0.10; actions: icu_transfer.
- `respiratory_failure` (acute pulmonary edema): probability_per_day ~0.006, risk
  severity_severe ×4; state_impact perfusion_status -0.10; actions: icu_transfer.

These give HF a real ICU-transfer / AKI event source (was absent), matching the ~0.12
ICU benchmark.

## Verification

1. Unit: `load_disease_protocol("heart_failure_exacerbation").course_archetypes` has the
   6 canonical archetypes + validates (severity + archetype_modifiers validators pass;
   no archetype_modifiers authored so that validator is a no-op). complications present.
2. Integration/fire: a small HF-forced cohort selects non-fallback archetypes and fires
   at least one complication over enough patients (audit / CIF grep).
3. Full suite unit/integration/e2e; regenerate goldens (AD-66) — HF is not a profile
   fixture disease (profiles are acute_mi/DKA/sepsis/pneumonia/COPD/hemorrhagic_stroke),
   so profile goldens should be byte-unchanged; cohort HF output shifts. audit 0 FAIL.
4. Clinical read (AD-66 Rule 2): HF cohort volume/cardiac trajectories move toward
   recovery (diuresis), ICU transfers now occur for severe HF.

## Scope

In: HF course_archetypes (6) + complications. Out (registry/TODO): the 8 trauma diseases
(FP-ARCH-2/3), HF `daily_trajectory` narrative, the `sodium_status` unrecognized-state-var
latent issue.

## Files

- `clinosim/modules/disease/reference_data/heart_failure_exacerbation.yaml` (add 2 blocks).
- `tests/unit/test_hf_course_archetypes.py` (presence + validation + fallback-not-used).
- Regenerated goldens (if any change), registry update.
</content>
