# BNP heart-failure specificity (ventricular wall-stress model)

**Date:** 2026-06-20
**Status:** **IMPLEMENTED** (2026-06-20) — see commits `ac36ff63` (initial coupling)
and `1c22a3e6` (audit-tuned coefficients). Current `engine.py:283` reads
`labs["BNP"] = 30.0 * math.exp((1 - cardiac) * 2.0 + max(0.0, state.volume_status) * (1 - cardiac) * 5.0)`
— the audit-tuned `(2.0, 5.0)` finalize the spec's starting `(2.5, 6.0)`.
Retained as a historical design record so the BNP-pattern surgical approach
(later reused in PR #62 sepsis SBP and PR #69 AKI Cr / DKA HCO3) has its
rationale and audit method documented in-repo.

Follow-up tracked separately: post-PR-#69 data-quality review observed I50
admit-day BNP p50 = 95 (US) / 79 (JP), below the spec's 800-1500 HF band.
The discrepancy is a **cohort-composition** question (I50 admit primary
diagnosis includes mild HF severity and chronic-I50 admits whose acute
event is not heart_failure_exacerbation), not a formula problem — the unit
test `test_bnp_discriminates_hf_from_mi` validates the formula on the
synthesized severe-HF state (cardiac=0.27, volume=+0.56 → BNP in band).
See `docs/reviews/2026-06-22-aki-dka-surgical-calibration-data-quality-review.md`
§3 for the cohort data.

---


**Scope:** physiology engine BNP mapping + observation clamp + tests + docs + generation audit. No new state axis, no new module, no disease/encounter YAML change.

## Problem

Data-quality audit (US/JP catchment 20k each, 2026-06-20) found BNP poorly
discriminates heart failure: HF median 324 vs non-HF 226 pg/mL — only 1.4x, with
non-HF too high (normal should be <100). Acute decompensated HF should reach
800–1500 pg/mL.

### Root cause

`physiology/engine.py:246`:

```python
labs["BNP"] = 30 * math.exp((1 - cardiac) * 4)
```

BNP is driven by `cardiac_function` **alone**. Both HF and MI lower `cardiac_function`,
so BNP cannot tell them apart. Worse, acute MI drops `cardiac_function` more steeply
(myocardial necrosis) than HF exacerbation, so the current mapping produces a *higher*
BNP for MI (~405) than for HF (~270) — backwards from the audit's discrimination goal.

Approximate state after `initialize_state` (chronic baseline) + `apply_disease_onset`
(acute onset), confirmed from disease YAML `initial_state_impact`:

| Scenario | cardiac_function | volume_status |
|---|---|---|
| Normal / non-cardiac (pneumonia, UTI) | ~0.88 | 0 |
| MI (severe) | ~0.35 | −0.10 |
| HF exacerbation (moderate) | ~0.43 (chronic I50 ×0.8 + acute −0.25) | **+0.65** |
| HF exacerbation (severe) | ~0.28 | **+0.85** |
| Cirrhosis ascites / AKI overload (heart preserved) | ~0.85 | +0.5 |

The physiological discriminator already exists in state: `volume_status`. HF =
volume/pressure overload (+0.65–0.85); MI = ischemia with normal/low volume (≈0).
The fix adds a `volume_status` term to the BNP mapping; **no state-setting change is
needed** because HF (`+0.30/+0.50/+0.70`) and MI (`−0.10`) already set `volume_status`
via their disease YAML `initial_state_impact`.

## Design

BNP physiologically reflects **ventricular wall stress = volume/pressure load ON a
stressed ventricle**. The chosen form couples the volume term to cardiac dysfunction
(`max(0, volume) × (1 − cardiac)`), so volume overload elevates BNP *only when the heart
is failing*. This is more clinically coherent than a purely additive volume term: it
keeps BNP low in non-cardiac fluid overload (cirrhosis ascites, AKI over-resuscitation)
where the ventricle is preserved, while HF (low cardiac × high volume) rises
synergistically and uncomplicated MI (low cardiac, normal volume) stays moderate.

### 1. Core mapping — `clinosim/modules/physiology/engine.py` (BNP line, ~246)

```python
# BNP reflects ventricular wall stress = volume/pressure load ON a stressed ventricle.
# The volume term is gated by cardiac dysfunction (coupling), so volume overload only
# elevates BNP when the heart is failing: HF (low cardiac x high volume) rises sharply,
# uncomplicated MI (low cardiac, normal volume) stays moderate, and non-cardiac fluid
# overload in a preserved heart (cirrhosis ascites, AKI) stays low. Deterministic
# (state -> lab, no rng).
labs["BNP"] = 30.0 * math.exp(
    (1 - cardiac) * 2.5 + max(0.0, state.volume_status) * (1 - cardiac) * 6.0
)
```

- Coefficients `(2.5, 6.0)` and base `30.0` are **starting values** — finalized by the
  generation audit (see Verification). They live inline in the engine like the existing
  troponin/CRP/Na coefficients (no new config file; consistent with current style).
- `max(0.0, volume_status)`: dehydration (negative volume) does not suppress BNP below
  the cardiac-driven floor — physiologically correct.
- No `numpy` rng — pure deterministic state→lab mapping (AD-16 preserved).

### 2. Upper clamp — `clinosim/modules/observation/engine.py` `PHYSIOLOGIC_LIMITS`

```python
"BNP": (0.0, 5000.0),   # pg/mL — assay reporting ceiling
```

The exponential can diverge for severe HF; the assay ceiling caps it post-noise via the
existing re-clamp mechanism (same path that bounds K/CRP tails, PR #16). BNP currently
has no entry, so this is a new key.

### 3. Invariance guarantees

- Every other lab / vital / diagnosis / blood-gas value is **mathematically unchanged** —
  only BNP changes intentionally.
- Normal patient (cardiac ≈ 0.9, volume 0): `30·exp(0.1·2.5)` ≈ 39 pg/mL ≈ current ~39,
  so no regression for non-cardiac patients.
- Main random stream is not perturbed (mapping-only change, identical draw count) → e2e
  golden differs only in BNP observation values; all other fields byte-identical.

### Expected discrimination (starting coefficients; tuned by audit)

| Scenario | cardiac / volume | BNP (approx) | Clinical target |
|---|---|---|---|
| Normal / non-cardiac | 0.88 / 0 | ~40 | <100 |
| MI (severe) | 0.35 / −0.1 | ~150 | 100–300 |
| Cirrhosis ascites / AKI overload | 0.85 / +0.5 | ~60 | <100 |
| HF exacerbation (moderate) | 0.43 / +0.65 | ~1150 | 800–1500 |
| HF exacerbation (severe) | 0.28 / +0.85 | clamp ~5000 | <5000 |

## Verification (generation audit)

Generate US + JP catchment 20k each into `/tmp` (never `output/`; delete after audit).
Extract BNP observations from CIF/FHIR and confirm:

- **(a)** HF (I50 primary or chronic) median ≫ non-HF median — target ≥5x (was 1.4x).
- **(b)** Normal / non-cardiac median <100 pg/mL.
- **(c)** HF exacerbation median in 800–1500 pg/mL.
- **(d)** Non-HF volume-overload diseases (cirrhosis, AKI) NOT spuriously elevated —
  validates the coupling form's advantage over an additive volume term.

If any target is missed, adjust `(2.5, 6.0)` / base `30.0` and regenerate. Audit
artifacts go to `/tmp` and are removed after.

## Testing

- **Unit** (`tests/unit/`, physiology lab derivation): add BNP discrimination
  properties — HF state (low cardiac, high volume) > MI state (low cardiac, ~0 volume)
  > normal state; normal BNP <100; coupling gate (high volume with preserved cardiac
  stays low).
- **Determinism / invariance**: e2e golden tolerates only BNP-value differences; all
  other fields unchanged. e2e is property/determinism-based and CPU-flaky — rerun the
  individual file to confirm, then full suite.

## Documentation

- `clinosim/modules/physiology/README.md` / `SPEC.md`: update the BNP mapping line and
  the `cardiac_function` / `volume_status` driver descriptions to reflect the wall-stress
  (volume × cardiac dysfunction) coupling.

## Out of scope (explicitly deferred)

- Renal-clearance BNP confounder (BNP rises in CKD independent of cardiac). Not flagged
  by the audit; would broaden scope. Track separately if a future audit flags it.
- The other audit gaps (GI bleeding incidence, CKD creatinine specificity, JP microbiology
  LOINC→JLAC10) are tracked in `project_realism_gaps` and handled separately.
