# Septic shock: distributive perfusion coupling

**Date:** 2026-06-21
**Status:** approved (design)
**Type:** physiology model extension (data-quality follow-up A)

## Background

The 2026-06-21 data-quality audit found that sepsis encounters are essentially
never hypotensive: per-encounter min SBP median ~122 mmHg, and **0% reach septic
shock (SBP < 90)**. Yet `sepsis.yaml` codes `R65.21` (severe sepsis *with septic
shock*) at probability 0.20 — so the diagnosis code and the physiology contradict
each other.

### Root cause

`perfusion_status` is a **derived** variable. In `apply_coupling_rules`
(`physiology/engine.py`):

```python
perfusion_status = clamp(cardiac_function * 0.8 + 0.2 + volume_effect, 0, 1)
```

and `apply_disease_onset` calls `apply_coupling_rules` *after* applying a disease's
`initial_state_impact`, so any `perfusion_status` delta a scenario sets is
**overwritten**. Sepsis is not cardiogenic, so `cardiac_function` stays ~1.0 →
perfusion ~1.0. The volume drop (`-0.40`) does not reach the `volume_effect`
threshold (`< -0.5`), so it does not lower perfusion either. SBP =
`baseline + volume*15 - (1-perfusion)*40` ≈ `baseline - 6`.

There is **no path for distributive (vasodilatory) shock** — the actual mechanism
of septic shock, where inflammatory vasodilation drops perfusion independent of
cardiac output and volume.

## Goal

Add a physiologically-correct distributive-shock path so that severe systemic
inflammation lowers perfusion, producing coherent septic shock: low SBP +
elevated lactate + AKI together. Calibrated so that:

- Sepsis SBP < 90 occurs in roughly **15–25%** of sepsis encounters (consistent
  with the `R65.21` ~20% coding), up from 0%.
- `moderate` sepsis stays normal-to-borderline; only `severe` (and comparably
  inflamed conditions) becomes hypotensive.
- No flood of the SBP floor (`< 60` clamp); the distribution should look clinical,
  not binary.

## Design

### Mechanism (single change in `apply_coupling_rules`)

Add a distributive term to the perfusion calculation:

```python
# Distributive (vasodilatory) shock: severe systemic inflammation lowers
# perfusion independent of cardiac function/volume — the mechanism of septic
# shock. Couples through to SBP, lactate (pH), and renal function below.
distributive = -max(0.0, state.inflammation_level - DISTRIBUTIVE_THRESHOLD) * DISTRIBUTIVE_COEFF
state.perfusion_status = clamp(
    state.cardiac_function * 0.8 + 0.2 + volume_effect + distributive, 0.0, 1.0
)
```

The coefficients are module-level constants (named, audit-tuned, like the existing
`HBA1C_*` constants), not magic numbers inline.

### Coupling consequences (already in `apply_coupling_rules`, now reachable)

Lowered perfusion already drives, in the same function:
- **Lactate / metabolic acidosis** — `if perfusion_status < 0.4: lactic_acid ...`
- **Pre-renal AKI** — `if perfusion_status < 0.5: renal_function -= ...`

and at vitals-derivation time, lowered perfusion drives **SBP/DBP down and HR up**
(`baseline + vol*15 - (1-perf)*40`). So one perfusion change yields the full
coherent septic-shock picture without any ad-hoc per-vital logic — consistent with
the BNP wall-stress and acid-base two-axis models.

### Scope of effect

Only conditions whose `inflammation_level > DISTRIBUTIVE_THRESHOLD` are affected.
With `THRESHOLD ≈ 0.7`:

| condition (severity) | inflammation | affected? |
|---|---|---|
| sepsis severe | 0.85 | yes |
| bacterial / aspiration pneumonia severe | 0.75 | yes |
| UTI severe, acute pancreatitis severe | 0.70 | borderline (tune threshold) |
| sepsis moderate, cellulitis | 0.65 | no |
| everything ≤ 0.6 | ≤ 0.60 | no |

This is clinically correct: severe pneumonia and severe intra-abdominal sepsis can
also cause septic shock. The threshold is a calibration knob.

### Coefficient calibration (audit-driven, like BNP/HbA1c)

Start from `THRESHOLD = 0.7`, `COEFF = 4.0` and adjust via generation audit
(US/JP, a few thousand patients):
- Worked example: inflammation 0.85, baseline SBP 120, volume −0.40 →
  `distributive = -(0.85-0.7)*4.0 = -0.60` → perfusion ≈ 0.40 → SBP ≈ 90.
- Increasing `COEFF` deepens shock; raising `THRESHOLD` narrows which conditions
  qualify. Tune both so sepsis SBP<90 lands ~15–25% and SBP<60 stays rare.

Final coefficients are pinned in the spec/commit once the audit confirms them.

## Determinism (AD-16)

`distributive` is a deterministic function of the existing `inflammation_level`
state variable. **No new RNG draw** is introduced, so the master random stream is
unchanged. Outputs that depend on perfusion (SBP, DBP, HR, lactate, renal-derived
labs/creatinine, pH) change — an intentional golden change — but the change is
purely deterministic and affects only encounters with `inflammation > THRESHOLD`.

## Testing

TDD, pure-function level on `apply_coupling_rules`:

1. **High inflammation lowers perfusion** — a state with `inflammation_level` above
   threshold and healthy cardiac/volume gets `perfusion_status` strictly below the
   non-distributive baseline (`cardiac*0.8+0.2`).
2. **Below threshold is unchanged** — `inflammation_level ≤ THRESHOLD` yields the
   exact pre-change perfusion (byte-identical coupling).
3. **Determinism** — same input state → same perfusion (no draw).
4. **Coherent shock** — a severe-sepsis-like state yields SBP < 90 *and* depressed
   perfusion driving the lactate/renal couplings (assert perfusion < 0.4 so the
   existing lactate branch fires).

## Verification

- `pytest -m unit` / `-m integration` every iteration.
- **Generation audit**: sepsis SBP distribution (median, p10, %<90, %<60) US + JP,
  plus a regression check that a non-inflammatory cohort (e.g. hip fracture, AMI
  with preserved perfusion) is unaffected.
- **byte-diff** master vs branch: confirm only inflammation>threshold encounters'
  perfusion-derived fields change; low-inflammation encounters byte-identical.
- `pytest -m e2e` golden (CIF golden expected to change for affected vitals/labs;
  inspect and re-bless if the change is the intended one).

## Out of scope

- No new severity tier or `septic_shock` archetype in `sepsis.yaml`.
- No change to `R65.x` coding logic.
- No change to the SBP/HR derivation formulas themselves.
