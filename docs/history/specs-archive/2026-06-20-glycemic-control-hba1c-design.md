# Glycemic Control Axis + HbA1c Physiology Model (DET-6)

**Date:** 2026-06-20
**Status:** Approved (design), pending implementation plan
**Related:** DET-6 (architecture review §3), AD-16 (determinism), AD-30 (CIF code-only),
AD-57 (physiology-driven labs), feedback "臨床的整合性は横断的"

## Problem

DET-6 asked to unify two divergent per-venue `baseline_values` fallback dicts
(`outpatient.py`, `emergency.py`). Investigation showed the **only live divergence**
is **HbA1c** (outpatient 6.5 = diabetes diagnostic threshold, emergency 5.6 = normal);
every other divergent key is dead config (the analyte is physiology-modeled, so the
baseline is never reached). Two deeper problems surfaced:

1. **HbA1c is not modeled by physiology.** It is a flat per-venue constant that ignores
   the patient's diabetes status and glycemic control. `inpatient.py` has no baseline
   fallback at all, so **inpatient HbA1c orders are never resulted** (silently dropped).
2. **Cross-module incoherence.** `ChronicCondition.stage` for E11/E10 is a *static
   random* string like `"HbA1c 7.2%"` (sampled in `_generate_stage`, keyed on
   `severity`), emitted into **FHIR `Condition.stage[0].summary.text`**. The independent
   `ChronicCondition.controlled` coin-flip (70%) is a *third* control signal. A flat
   HbA1c lab would contradict the Condition.stage text and neither reflects control.

A flat constant cannot be clinically coherent (a diabetic shown HbA1c 5.6, or a
non-diabetic shown 6.5). The fix is to model HbA1c from a **single continuous glycemic
control axis** shared by the lab value, the Condition.stage display, and the glucose
baseline — and to let scenarios that imply poor chronic control (DKA/HHS) drive it.

## Goals

- Single source of truth for a diabetic patient's chronic glycemic control:
  a continuous `glycemic_control ∈ [0,1]` (1.0 = excellent, 0.0 = very poor).
- HbA1c (lab), `Condition.stage` HbA1c display, and Glucose baseline all derive from it
  → mutually coherent.
- Inpatient HbA1c orders are now resulted (gap fixed).
- DKA/HHS scenarios force poor chronic control (data-driven, like
  `causes_myocardial_injury` / `acid_base_type`).
- DET-6 dedup: remaining non-divergent baseline normals unified into one
  `_BASELINE_LAB_NORMALS` in `observation/engine.py`.
- **Determinism (AD-16): the main random stream is not perturbed** — no new RNG draws.
  Non-HbA1c / non-Glucose output stays byte-identical.

## Non-Goals

- Narrative/discharge-summary text referencing HbA1c (narratives don't mention it today,
  so no incoherence is introduced). Optional future enhancement — noted in TODO, out of
  scope here.
- Modeling Type 1 vs Type 2 distinctly, prediabetes cohorts, or HbA1c temporal drift
  within a stay (HbA1c is a ~3-month average; treated as encounter-stable).
- Cleaning up the now-superseded `ChronicCondition.controlled` field (kept as-is to
  preserve the draw sequence; noted as dead).

## Design

### 1. Data model — `clinosim/types/patient.py`

Add to `ChronicCondition`:

```python
glycemic_control: float | None = None  # E11/E10 only; 1.0=excellent .. 0.0=very poor
```

`None` for non-diabetes conditions. Set only for E11*/E10* at activation.

### 2. Single HbA1c↔control formula — `clinosim/modules/physiology/engine.py`

One pure helper, imported by both physiology (lab) and the activator (stage display),
so there is exactly one formula:

```python
def hba1c_from_glycemic_control(glycemic_control: float) -> float:
    """Typical (noise-free) HbA1c % for a diabetic at this control level.
    Coefficients tuned by generation audit (see Calibration)."""
    gc = clamp(glycemic_control, 0.0, 1.0)
    return HBA1C_BEST + (1.0 - gc) * HBA1C_SPAN     # e.g. 6.0 + (1-gc)*K
```

Non-diabetic HbA1c is a separate near-constant (≈5.0–5.4, mild age term), handled in
`derive_lab_values`.

### 3. Sampling — `clinosim/modules/patient/activator.py` (determinism-preserving)

Today the E11/E10 branch of `_generate_stage` consumes **one** float draw
(`rng.uniform(...)`) to build the stage string, and `controlled` consumes one draw at
the condition loop. We **reinterpret the existing E11 stage draw** as the glycemic
control source — same draw count and position, so the main stream is unperturbed:

```python
# in the chronic-condition loop, for E11*/E10*:
gc_draw = float(rng.random())                       # replaces the E11 uniform (1 draw)
glycemic_control = _glycemic_control_from_draw(gc_draw)   # continuous mapping
stage = f"HbA1c {hba1c_from_glycemic_control(glycemic_control):.1f}%"
# non-diabetes: glycemic_control=None; stage = _generate_stage(code, sev, rng) as before
```

- `_glycemic_control_from_draw` maps the uniform to a realistic control distribution
  (most diabetics reasonably controlled, a poorly-controlled tail). Exact mapping fixed
  by Calibration so HbA1c distribution matches targets.
- The E11/E10 branch is **removed from `_generate_stage`** and handled inline in the loop
  (so glycemic_control is available to store on the condition). `_generate_stage` for all
  other codes is unchanged (same draws).
- `controlled=rng.random() < 0.7` (next line) is **kept verbatim** (preserves the stream;
  field is dead/unused — noted).
- `severity_score` draw unchanged.

Net: the *value* drawn at the E11 position is unchanged; only its *interpretation* and
the resulting stage string change. Every downstream draw sees the identical sequence.

### 4. Physiology integration — `clinosim/modules/physiology/engine.py`

- `initialize_state`: for an E11*/E10* chronic condition, set
  `state.glycemic_control = condition.glycemic_control` (new field on `PhysiologicalState`,
  default `None`). Chronic axis — **not** modified by `apply_disease_onset` (HbA1c is a
  3-month average; acute onset doesn't move it). Mirrors how CKD→renal_function is seeded.
- `derive_lab_values`:
  - `labs["HbA1c"]`:
    - diabetic (`has_diabetes` or `state.glycemic_control is not None`):
      `hba1c_from_glycemic_control(state.glycemic_control)` (fallback gc if has_diabetes
      but axis unset, e.g. new-onset — see §5).
    - non-diabetic: `HBA1C_NONDM_BASE` + mild age term.
  - Glucose baseline becomes continuous in the same axis (replaces the
    `130 if diabetes_controlled else 200` binary):
    `base_glu = GLU_DM_BEST + (1 - state.glycemic_control) * GLU_DM_SPAN` for diabetics;
    non-diabetic unchanged (95). Acute `glucose_status`, stress, diurnal, postprandial
    terms stack on top exactly as today.
  - The existing `diabetes_controlled` parameter is removed/ignored (it was always
    defaulted True; superseded by the axis). Callers need no new kwargs — the axis travels
    on `state`.

Keeping HbA1c and Glucose on the same axis prevents "high HbA1c + normal glucose"
incoherence (loosely tracks the ADAG eAG↔A1c relationship; exact match not required since
glucose carries acute/diurnal terms).

### 5. Scenario linkage — disease protocol YAML

Add an **optional** disease-protocol field:

```yaml
chronic_glycemic_control: 0.1   # 0=very poor .. 1=excellent; implies poor chronic control
```

When present (DKA, HHS), the simulator sets `state.glycemic_control` to this value for the
encounter (overriding the patient's sampled axis), and treats the patient as diabetic for
HbA1c even without an E11 condition (new-onset DKA). Same data-driven pattern as
`causes_myocardial_injury` / `acid_base_type`. Prevents a DKA patient from randomly showing
HbA1c 6.5 (good control), which is clinically incoherent.

Applied where the disease scenario is known (inpatient disease path; ED emergency via the
encounter/disease protocol). No new RNG draws.

### 6. Baseline removal + DET-6 unification

- Remove `"HbA1c"` from the `baseline_values` dicts in `outpatient.py` and `emergency.py`
  (physiology now derives it). Inpatient now results HbA1c via `true_labs`.
- Extract the remaining **non-divergent** baseline normals (the keys that agree across
  venues and are genuinely physiology-unmodeled: Ca, TSH, LDL, HDL, TG, TC, ESR) into a
  single `_BASELINE_LAB_NORMALS: dict[str, float]` in `observation/engine.py`, imported by
  both venues. This is DET-6's actual dedup goal. (Dead-but-divergent keys like
  WBC/CRP — modeled by physiology — are simply dropped from the per-venue dicts.)

### 7. Observation support — `clinosim/modules/observation/engine.py`

Add HbA1c to:
- `BIOLOGICAL_CV` / `ANALYTICAL_CV`: small (~1–2%) — HbA1c is a low-variability assay.
- `PHYSIOLOGIC_LIMITS`: clamp to a physiological band (≈3.0–18.0 %).
- `determine_flag`: flag against the locale reference range (US 4.0–5.6, JP 4.9–6.0);
  diabetic values (>range) → `H`, consistent with referenceRange (FHIR R5 Note 5).

### Determinism summary (AD-16)

- No new draws; the E11 stage draw is reinterpreted in place; `controlled`/`severity_score`
  draws untouched. → main stream unperturbed → all non-HbA1c, non-Glucose output is
  byte-identical.
- `glycemic_control` is patient-stable (sampled once at activation, stored on the
  condition, read read-only by physiology each encounter).

## Calibration (generation audit — like BNP PR #28)

Coefficients (`HBA1C_BEST`, `HBA1C_SPAN`, `HBA1C_NONDM_BASE`, `GLU_DM_BEST`, `GLU_DM_SPAN`,
the `_glycemic_control_from_draw` mapping, DKA `chronic_glycemic_control`) are fixed by
generating US + JP ~20k and auditing HbA1c distributions against targets:

| Cohort | Target HbA1c (%) |
|---|---|
| Non-diabetic | 5.0 – 5.6 |
| Diabetic, well-controlled | 6.5 – 7.5 |
| Diabetic, poorly-controlled (tail) | 8.5 – 11 |
| DKA / HHS (forced poor) | 9 – 13 |

Glucose baseline for diabetics should co-move (well-controlled ~120–140 fasting,
poor ~180–220) and stay consistent with the patient's HbA1c.

## Intended golden changes

- HbA1c becomes diabetes-aware continuous in **all** venues (outpatient/emergency lose flat
  6.5/5.6; inpatient newly results HbA1c).
- `ChronicCondition.stage` (E11/E10) HbA1c string now derived from `glycemic_control`
  → FHIR `Condition.stage.summary.text` changes accordingly (now coherent with labs).
- Glucose baseline for diabetics varies with control (was flat 130).
- e2e `test_alpha_golden.py` golden patient is an inpatient pneumonia case that orders no
  HbA1c, so its `lab_result_count` is unchanged; the documented golden constants are not
  asserted and stay as-is.
- **ED ESR now resolved (DET-6 side effect):** the old per-venue *emergency* baseline did
  not contain ESR, so an ED ESR order (only `low_back_pain.yaml`, prob 0.1) was silently
  dropped (placed, never resulted). The shared `BASELINE_LAB_NORMALS` includes ESR, so the
  order now resolves to a normal value — a clinically-correct fix (an order should produce a
  result), consistent with how the outpatient venue already handled ESR. This shifts the RNG
  stream only within ED low-back-pain encounters that roll the ESR order; the inpatient e2e
  golden is unaffected. No ED encounter orders lipids, so the lipid keys are inert in ED.
- Otherwise byte-identical except HbA1c / diabetic Glucose (main stream preserved).

## Testing

- **Unit (bug-catching / characterization):**
  - `hba1c_from_glycemic_control` monotonic + boundary values.
  - `derive_lab_values` emits HbA1c; diabetic gc=high → ~6.5–7.5, gc=low → high; non-DM
    → ~5.x. Glucose co-moves with gc.
  - `_generate_stage`/activator: E11 stage HbA1c matches `hba1c_from_glycemic_control` of
    the stored `glycemic_control` (coherence guard: stage == lab central value).
  - DKA `chronic_glycemic_control` override → high HbA1c even if patient axis is good.
  - Determinism: a pinned seed produces identical `glycemic_control` across runs, and a
    non-diabetic-only population's full output is unchanged vs master (stream-preserved).
- **Integration:** venue lab generation still green; inpatient now yields an HbA1c result.
- **e2e:** update `lab_result_count`; confirm no other golden drift; US 100% English / JP
  localization intact; referenceRange+interpretation present for HbA1c.
- **Generation audit:** US+JP ~20k, verify the Calibration table.

## Module impact (audited, read-only)

- `types/patient.py`: +`glycemic_control` field. FHIR Condition reads `.stage`/`.severity`
  (now coherent) — no adapter change.
- `physiology/engine.py`: +helper, +HbA1c, glucose axis, state field, remove
  `diabetes_controlled`.
- `patient/activator.py`: E11 stage→glycemic_control (draw-preserving).
- `observation/engine.py`: +`_BASELINE_LAB_NORMALS`, HbA1c CV/limits/flag.
- `simulator/{outpatient,emergency}.py`: drop HbA1c baseline, import `_BASELINE_LAB_NORMALS`.
- `simulator/inpatient.py`: no change needed (HbA1c flows via `true_labs`); scenario override
  wired where disease state is built.
- disease YAML (DKA/HHS): +`chronic_glycemic_control`.
- README/module docs: update ChronicCondition fields + physiology axis count.
- No change: csv_adapter, narrative_generator, document_generator (no HbA1c today),
  diagnosis differentials, population screening, validator.
