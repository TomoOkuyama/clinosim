# Septic shock: distributive hypotension

**Date:** 2026-06-21
**Status:** implemented
**Type:** physiology model extension (data-quality follow-up A)

## Background

The 2026-06-21 data-quality audit found that sepsis encounters are essentially
never hypotensive: per-encounter min SBP median ~122 mmHg, **0% reach septic
shock (SBP < 90)**. Yet `sepsis.yaml` codes `R65.21` (severe sepsis *with septic
shock*) at probability 0.20 — the diagnosis code and the physiology contradict
each other.

### Root cause

`perfusion_status` is **derived** (`apply_coupling_rules`):
`perfusion = clamp(cardiac*0.8 + 0.2 + volume_effect, 0, 1)`, and
`apply_disease_onset` re-runs the coupling *after* a disease's
`initial_state_impact`, overwriting any perfusion delta. Sepsis is not cardiogenic
(cardiac ~1.0) and the volume drop (`-0.40`) does not reach the `volume_effect`
threshold (`< -0.5`), so perfusion stays ~1.0 and
`SBP = baseline + volume*15 - (1-perfusion)*40 ≈ baseline - 6`. There is no
distributive (vasodilatory) path — the mechanism of septic shock.

## What changed vs the first design (important)

The original design lowered `perfusion_status` itself (a coupling term). **A
generation audit of that implementation rejected it:**

1. **Lab regression.** Driving perfusion < 0.4 to reach SBP < 90, over the
   multi-day course, over-accumulated the existing cumulative renal/lactate
   couplings: sepsis Creatinine median 2.9 → **8.1**, BUN 45 → **166**, Lactate
   4.6 → **11.2** — clinically absurd for the median sepsis patient.
2. **Master-stream perturbation.** `perfusion_status` feeds the
   clinical-course / complication / LOS / mortality RNG branches. Changing it
   shifted draw counts, and because the master RNG is threaded across patients,
   **76% of (unrelated) patients' demographics changed and the population set
   shifted** — a determinism (AD-16) violation, not a realism gain.
3. **The labs were already coherent.** Master sepsis already has elevated Lactate
   (4.6) and Creatinine (2.9) via `initial_state_impact` (renal −0.25, etc.). The
   **only** missing piece was hypotension (SBP).

## Design (implemented)

Apply distributive hypotension **at vitals derivation only**, in
`derive_vital_signs`, without mutating `perfusion_status`:

```python
distributive_drop = max(0.0, inflammation_level - DISTRIBUTIVE_THRESHOLD) * DISTRIBUTIVE_SBP_COEFF
sbp = baseline.systolic_bp + vol*15 - (1-perf)*40 - distributive_drop
dbp = baseline.diastolic_bp + vol*8 - (1-perf)*20 - distributive_drop * 0.6
```

`DISTRIBUTIVE_THRESHOLD = 0.7`, `DISTRIBUTIVE_SBP_COEFF = 60.0` (audit-tuned).
Because `perfusion_status` is untouched, the clinical-course/complication/LOS/
mortality logic sees identical state — **no master-stream perturbation**. The
already-elevated lactate/AKI labs are preserved, so the FHIR output is a coherent
septic shock: SBP↓ + lactate↑ + creatinine↑. NEWS2 (which has SBP as a
component) recomputes deterministically to reflect the hypotension.

### Scope of effect

Only `inflammation > 0.7` conditions get hypotension: sepsis severe (0.85),
severe bacterial/aspiration pneumonia (0.75), borderline severe UTI/pancreatitis
(0.70). Moderate sepsis (0.65) and everything ≤ 0.6 are unchanged. Clinically
correct — severe pneumonia and intra-abdominal sepsis can also cause septic shock.

### Calibration (audit, US p9000 seed 7, n=20 sepsis)

`COEFF=60`: sepsis min SBP median 104, **SBP<90 = 25%** (target 15–25%,
consistent with R65.21 ~20%), worst 82, **SBP<60 = 0%** (no floor flooding).
Labs unchanged from master (Lactate 4.6, Creatinine 2.9). Non-inflammatory
cohort (hip fracture) byte-identical.

## Determinism (AD-16)

`distributive_drop` is a pure function of the existing `inflammation_level`,
computed at output time; it does not mutate state and adds no RNG draw. The master
stream is unchanged. Byte-diff (same seed, master vs branch): **only
Observation.ndjson differs** — Systolic/Diastolic blood pressure and the derived
NEWS2 of `inflammation > 0.7` encounters. Patient, Condition, labs, all other
resources are byte-identical (no cascade).

## Testing

TDD on `derive_vital_signs`: high inflammation lowers SBP vs threshold; at/below
threshold SBP unchanged; severe-shock state reaches SBP < 90; `perfusion_status`
not mutated; determinism. Plus generation audit + golden byte-diff above.

## Out of scope

- No change to `apply_coupling_rules`, `sepsis.yaml` severity tiers, or `R65.x`.
- No re-architecture of the shared master RNG stream (the deeper cause of the
  rejected design's cascade) — out of scope for this follow-up.
