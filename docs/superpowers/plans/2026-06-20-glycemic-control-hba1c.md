# Glycemic Control Axis + HbA1c Physiology Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Model HbA1c from a single continuous `glycemic_control` axis shared by the lab value, `ChronicCondition.stage` display, and Glucose baseline, with DKA scenario linkage — resolving DET-6 and the inpatient/Condition-stage incoherence.

**Architecture:** A patient-stable `glycemic_control ∈ [0,1]` is sampled at activation by *reinterpreting the existing E11 stage RNG draw* (no new draw → main stream unperturbed, AD-16). It is stored on the diabetic `ChronicCondition`, seeded into `PhysiologicalState` by `initialize_state`, and consumed by `derive_lab_values` for both HbA1c and the Glucose baseline via one shared formula `hba1c_from_glycemic_control`. DKA/HHS disease protocols override it. DET-6's leftover non-divergent baseline normals move to a single `_BASELINE_LAB_NORMALS`.

**Tech Stack:** Python 3.11, numpy Generator (seeded), dataclasses, Pydantic (DiseaseProtocol), pytest.

## Global Constraints

- **Determinism (AD-16):** NO new RNG draws on the main stream. The E11 stage draw is *reinterpreted in place* (one `rng.random()` replacing one `rng.uniform`, identical stream advance). `controlled`/`severity_score` draws kept verbatim. Non-HbA1c/non-Glucose output stays byte-identical.
- **Types live in `clinosim/types/`** — never define data types in module code.
- **AD-30:** CIF stores codes/values, not display text resolved elsewhere; `stage` is an existing display exception.
- **No hardcoded coefficients without audit:** HbA1c/Glucose coefficients are placeholders here, fixed by the Task 7 generation audit.
- **Line length 100, ruff, mypy strict.** English comments/docstrings.
- **Run `pytest -m unit` before every commit; full `pytest -x` at the end.**

---

### Task 1: HbA1c formula + HbA1c/Glucose in `derive_lab_values`

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (add `hba1c_from_glycemic_control`, constants; add `labs["HbA1c"]`; make Glucose baseline continuous; signature)
- Modify: `clinosim/types/clinical.py:33` region (add `glycemic_control` to `PhysiologicalState`)
- Test: `tests/unit/test_physiology.py`

**Interfaces:**
- Produces: `hba1c_from_glycemic_control(glycemic_control: float) -> float`; `PhysiologicalState.glycemic_control: float | None`; `derive_lab_values(...)` now returns `"HbA1c"` and Glucose baseline driven by `state.glycemic_control`.
- Consumes: existing `clamp`, `PhysiologicalState`.

- [ ] **Step 1: Add `glycemic_control` field to `PhysiologicalState`**

In `clinosim/types/clinical.py`, after the `glucose_status` field (line ~33), add:

```python
    # Chronic glycemic control for diabetics: 1.0 = excellent (HbA1c ~6%), 0.0 = very poor
    # (HbA1c ~12%). None = non-diabetic. Patient-stable; seeded from the E11 ChronicCondition
    # by initialize_state and NOT moved by acute disease onset (HbA1c is a ~3-month average).
    glycemic_control: float | None = None
```

- [ ] **Step 2: Write failing tests for the formula + HbA1c/Glucose derivation**

In `tests/unit/test_physiology.py` add:

```python
def test_hba1c_from_glycemic_control_monotonic_and_bounds():
    from clinosim.modules.physiology.engine import hba1c_from_glycemic_control
    best = hba1c_from_glycemic_control(1.0)
    worst = hba1c_from_glycemic_control(0.0)
    assert best < worst                      # worse control -> higher HbA1c
    assert 6.0 <= best <= 7.0                # well-controlled diabetic
    assert 10.0 <= worst <= 13.0             # very poor control
    # clamps out-of-range input
    assert hba1c_from_glycemic_control(2.0) == hba1c_from_glycemic_control(1.0)


def test_derive_lab_values_hba1c_diabetic_vs_nondiabetic():
    from clinosim.modules.physiology.engine import derive_lab_values
    from clinosim.types.clinical import PhysiologicalState
    nondm = PhysiologicalState()
    labs_nondm = derive_lab_values(nondm, sex="M", age=55, has_diabetes=False)
    assert 4.5 <= labs_nondm["HbA1c"] <= 5.8

    good = PhysiologicalState(glycemic_control=0.9)
    labs_good = derive_lab_values(good, sex="M", age=55, has_diabetes=True)
    assert 6.0 <= labs_good["HbA1c"] <= 7.6

    poor = PhysiologicalState(glycemic_control=0.1)
    labs_poor = derive_lab_values(poor, sex="M", age=55, has_diabetes=True)
    assert labs_poor["HbA1c"] > labs_good["HbA1c"]
    # Glucose co-moves with control
    assert labs_poor["Glucose"] > labs_good["Glucose"]
```

- [ ] **Step 3: Run tests — expect FAIL**

Run: `pytest tests/unit/test_physiology.py -k "hba1c or glycemic" -v`
Expected: FAIL (`hba1c_from_glycemic_control` not defined / `KeyError: 'HbA1c'`).

- [ ] **Step 4: Implement the formula + constants**

In `clinosim/modules/physiology/engine.py`, near the top (after imports / module constants), add:

```python
# HbA1c model (chronic glycemic control). Coefficients fixed by generation audit (Task 7).
HBA1C_NONDM_BASE = 5.1     # %, non-diabetic baseline (mild age term added below)
HBA1C_BEST = 6.0           # %, diabetic at perfect control (glycemic_control = 1.0)
HBA1C_SPAN = 6.0           # %, added at glycemic_control = 0.0  -> 12.0% worst case
# Diabetic fasting Glucose baseline as a function of glycemic control.
GLU_DM_BEST = 120.0        # mg/dL at glycemic_control = 1.0
GLU_DM_SPAN = 100.0        # mg/dL added at glycemic_control = 0.0 -> 220 worst
GLYCEMIC_CONTROL_DEFAULT = 0.5   # fallback when has_diabetes but axis unset (e.g. new-onset)


def hba1c_from_glycemic_control(glycemic_control: float) -> float:
    """Typical (noise-free) HbA1c % for a diabetic at this chronic control level.

    glycemic_control: 1.0 = excellent, 0.0 = very poor. Coefficients audit-tuned.
    """
    gc = clamp(glycemic_control, 0.0, 1.0)
    return HBA1C_BEST + (1.0 - gc) * HBA1C_SPAN
```

- [ ] **Step 5: Add HbA1c to `derive_lab_values` and make Glucose continuous**

In `derive_lab_values`, in the Glucose block (currently lines ~316-318), replace:

```python
    if has_diabetes:
        base_glu = 130.0 if diabetes_controlled else 200.0
    else:
        base_glu = 95.0
```

with:

```python
    is_diabetic = has_diabetes or state.glycemic_control is not None
    gc = state.glycemic_control if state.glycemic_control is not None else GLYCEMIC_CONTROL_DEFAULT
    if is_diabetic:
        base_glu = GLU_DM_BEST + (1.0 - clamp(gc, 0.0, 1.0)) * GLU_DM_SPAN
    else:
        base_glu = 95.0
```

Then, after the Glucose block ends (after the `labs["Glucose"] = clamp(...)` line ~339), add HbA1c:

```python
    # --- HbA1c (chronic glycemic control; ~3-month average, control-driven) ---
    if is_diabetic:
        labs["HbA1c"] = hba1c_from_glycemic_control(gc)
    else:
        labs["HbA1c"] = HBA1C_NONDM_BASE + max(0, age - 40) * 0.003  # mild age term
```

Remove the now-unused `diabetes_controlled` parameter from the signature (no caller passes it — confirmed by audit). Update the signature line `diabetes_controlled: bool = True,` → delete it.

- [ ] **Step 6: Run tests — expect PASS**

Run: `pytest tests/unit/test_physiology.py -k "hba1c or glycemic or glucose" -v`
Expected: PASS (existing `test_dka_hyperglycemia*` / `test_hypoglycemia*` still pass — they use `glucose_status`, unaffected).

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/physiology/engine.py clinosim/types/clinical.py tests/unit/test_physiology.py
git commit -m "feat(physiology): model HbA1c + Glucose from glycemic_control axis"
```

---

### Task 2: Seed `glycemic_control` into state from the E11 condition

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` `initialize_state` (the chronic-condition loop, ~line 40-70)
- Test: `tests/unit/test_physiology.py`

**Interfaces:**
- Consumes: `ChronicCondition.glycemic_control` (added in Task 3 — but the read is `getattr`-safe so this task is order-independent).
- Produces: `initialize_state` sets `state.glycemic_control` for E11/E10 conditions.

- [ ] **Step 1: Write failing test**

```python
def test_initialize_state_seeds_glycemic_control_from_e11():
    from clinosim.modules.physiology.engine import initialize_state
    from clinosim.types.patient import ChronicCondition, PatientPhysiologicalProfile
    prof = PatientPhysiologicalProfile()
    dm = ChronicCondition(code="E11.9", glycemic_control=0.2)
    st = initialize_state(prof, [dm], "pt-1")
    assert st.glycemic_control == 0.2
    # non-diabetic -> stays None
    st2 = initialize_state(prof, [], "pt-2")
    assert st2.glycemic_control is None
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_physiology.py -k seeds_glycemic -v`
Expected: FAIL (`st.glycemic_control` is None).

- [ ] **Step 3: Add E11/E10 branch to `initialize_state`**

In the chronic-condition `for c in conditions:` loop, add a branch (after the `J45` asthma branch, before the loop end):

```python
        elif code.startswith(("E11", "E10")):  # Diabetes — chronic glycemic control axis
            gc = getattr(c, "glycemic_control", None)
            if gc is not None:
                state.glycemic_control = gc
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_physiology.py -k seeds_glycemic -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "feat(physiology): seed state.glycemic_control from E11 chronic condition"
```

---

### Task 3: `ChronicCondition.glycemic_control` + activator stage unification (draw-preserving)

**Files:**
- Modify: `clinosim/types/patient.py:73-81` (add field)
- Modify: `clinosim/modules/patient/activator.py` (`_generate_stage` remove E11 branch; condition loop computes glycemic_control + stage from one draw)
- Test: `tests/unit/test_patient.py` (or `clinosim/modules/patient/test_patient.py` — match existing location)

**Interfaces:**
- Consumes: `hba1c_from_glycemic_control` (Task 1).
- Produces: `ChronicCondition.glycemic_control: float | None`; E11 conditions carry a control level whose stage string equals `hba1c_from_glycemic_control(glycemic_control)`.

- [ ] **Step 1: Add the field**

In `clinosim/types/patient.py`, in `ChronicCondition`, after `severity_score`:

```python
    glycemic_control: float | None = None  # E11/E10 only; 1.0=excellent .. 0.0=very poor
```

- [ ] **Step 2: Write failing coherence + determinism tests**

In the patient test file add:

```python
def test_e11_stage_matches_glycemic_control():
    import numpy as np
    from clinosim.modules.patient.activator import activate_patient
    # find/construct a diabetic person; if helper exists use it. Otherwise sample until E11.
    from clinosim.modules.physiology.engine import hba1c_from_glycemic_control
    # Use the smallest deterministic path: build a Person with E11.9 and activate.
    # (Adapt to the repo's activate_patient signature / Person factory used in this file.)
    ...
    dm = next(c for c in patient.chronic_conditions if c.code.startswith("E11"))
    assert dm.glycemic_control is not None
    expected = f"HbA1c {hba1c_from_glycemic_control(dm.glycemic_control):.1f}%"
    assert dm.stage == expected


def test_glycemic_control_deterministic_same_seed():
    # Same seed -> identical glycemic_control (and identical non-diabetic output).
    ...
    assert run_a == run_b
```

(Use the activation/Person construction pattern already present in this test file; do not invent a new harness.)

- [ ] **Step 3: Run — expect FAIL**

Run: `pytest <patient test file> -k "e11_stage or glycemic_control_deterministic" -v`
Expected: FAIL (`glycemic_control` is None / stage mismatched).

- [ ] **Step 4: Remove E11 branch from `_generate_stage`**

In `clinosim/modules/patient/activator.py` `_generate_stage`, delete the block:

```python
    if base in ("E11", "E10"):  # Diabetes
        if severity == "mild":
            hba1c = float(rng.uniform(6.5, 7.5))
        else:
            hba1c = float(rng.uniform(7.5, 9.5))
        return f"HbA1c {hba1c:.1f}%"
```

- [ ] **Step 5: Compute glycemic_control + stage in the condition loop (one draw)**

In the `for code in person.chronic_conditions:` loop, replace the `stage = _generate_stage(code, sev, rng)` line and the `ChronicCondition(...)` construction so that E11/E10 derive from a single `rng.random()` (the same single float draw the removed E11 `uniform` consumed — stream-preserving):

```python
        base = code.split(".")[0]
        if base in ("E11", "E10"):
            gc_draw = float(rng.random())          # replaces the removed E11 uniform (1 draw)
            glycemic_control = 1.0 - gc_draw        # low draw -> good control
            stage = f"HbA1c {hba1c_from_glycemic_control(glycemic_control):.1f}%"
        else:
            glycemic_control = None
            stage = _generate_stage(code, sev, rng)
        conditions.append(ChronicCondition(
            code=code,
            system="icd-10-cm",
            onset_date=date(onset_year, onset_month, onset_day),
            severity=sev,
            controlled=rng.random() < 0.7,          # KEEP verbatim (preserves stream; dead field)
            severity_score=float(rng.uniform(0.1, 0.4)),
            stage=stage,
            glycemic_control=glycemic_control,
        ))
```

Add `from clinosim.modules.physiology.engine import hba1c_from_glycemic_control` at the top of the file (verify no import cycle: physiology imports only types — safe).

- [ ] **Step 6: Run — expect PASS**

Run: `pytest <patient test file> -k "e11_stage or glycemic_control_deterministic" -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add clinosim/types/patient.py clinosim/modules/patient/activator.py <patient test file>
git commit -m "feat(patient): unify E11 stage HbA1c with glycemic_control axis (draw-preserving)"
```

---

### Task 4: HbA1c observation support + DET-6 `_BASELINE_LAB_NORMALS`

**Files:**
- Modify: `clinosim/modules/observation/engine.py` (BIOLOGICAL_CV:46, ANALYTICAL_CV:60, PHYSIOLOGIC_LIMITS:127, determine_flag defaults:230-248; add `_BASELINE_LAB_NORMALS`)
- Test: `tests/unit/test_observation.py` (match existing location) + `tests/unit/test_baseline_normals.py` (new)

**Interfaces:**
- Produces: `_BASELINE_LAB_NORMALS: dict[str, float]` (Ca, TSH, LDL, HDL, TG, TC, ESR); HbA1c entries in CV/limits/flag.

- [ ] **Step 1: Failing tests**

```python
def test_hba1c_flag_and_limits():
    from clinosim.modules.observation.engine import determine_flag, PHYSIOLOGIC_LIMITS
    assert "HbA1c" in PHYSIOLOGIC_LIMITS
    assert determine_flag("HbA1c", 8.0) == "H"      # diabetic > normal range
    assert determine_flag("HbA1c", 5.2) is None     # normal

def test_baseline_lab_normals_exported():
    from clinosim.modules.observation.engine import _BASELINE_LAB_NORMALS
    assert _BASELINE_LAB_NORMALS["Ca"] == 9.2
    assert _BASELINE_LAB_NORMALS["TSH"] == 2.5
    assert "HbA1c" not in _BASELINE_LAB_NORMALS    # HbA1c is physiology-modeled now
```

- [ ] **Step 2: Run — expect FAIL**

Run: `pytest tests/unit/test_observation.py -k "hba1c_flag or baseline_lab" -v`
Expected: FAIL.

- [ ] **Step 3: Add HbA1c to CV / limits / flag and define `_BASELINE_LAB_NORMALS`**

In `BIOLOGICAL_CV` add `"HbA1c": 0.015,`; in `ANALYTICAL_CV` add `"HbA1c": 0.01,`; in `PHYSIOLOGIC_LIMITS` add `"HbA1c": (3.0, 18.0),`; in `determine_flag` `defaults` add `"HbA1c": {"all": (4.0, 5.6)},`.

Add near the other module dicts:

```python
# Reference-normal fallback values for analytes physiology does not model, shared by the
# outpatient/emergency venues (DET-6 — single source of truth, replaces per-venue dicts).
_BASELINE_LAB_NORMALS: dict[str, float] = {
    "Ca": 9.2, "TSH": 2.5, "LDL": 110, "HDL": 55, "TG": 130, "TC": 190, "ESR": 12,
}
```

- [ ] **Step 4: Run — expect PASS**

Run: `pytest tests/unit/test_observation.py -k "hba1c_flag or baseline_lab" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/observation/engine.py tests/unit/test_observation.py
git commit -m "feat(observation): HbA1c CV/limits/flag + _BASELINE_LAB_NORMALS (DET-6)"
```

---

### Task 5: Venues use `_BASELINE_LAB_NORMALS`, drop HbA1c baseline

**Files:**
- Modify: `clinosim/simulator/outpatient.py:149-154`
- Modify: `clinosim/simulator/emergency.py:107-109`
- Test: `tests/unit/` or `tests/integration/` venue test (assert HbA1c now derived, lipids still from baseline)

**Interfaces:**
- Consumes: `_BASELINE_LAB_NORMALS` (Task 4); `derive_lab_values` HbA1c (Task 1).

- [ ] **Step 1: Failing test** — assert an outpatient diabetic HbA1c order is resolved from physiology (varies by control), not the flat 6.5:

```python
def test_outpatient_hba1c_from_physiology_not_flat():
    # Build two diabetic patients with different glycemic_control, generate outpatient labs,
    # assert HbA1c differs (was flat 6.5 before). Adapt to outpatient generate signature.
    ...
    assert hba1c_poor > hba1c_good
```

- [ ] **Step 2: Run — expect FAIL** (flat 6.5 for both).

- [ ] **Step 3: Replace the baseline dicts**

In `outpatient.py`, replace the `baseline_values = {...}` literal (lines 149-154) with:

```python
    from clinosim.modules.observation.engine import _BASELINE_LAB_NORMALS
    baseline_values = _BASELINE_LAB_NORMALS
```

In `emergency.py`, replace the `baseline_values = {...}` literal (lines 107-109) likewise. (HbA1c is no longer in baseline; it now comes from `_true_labs`.)

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/outpatient.py clinosim/simulator/emergency.py tests/...
git commit -m "refactor(sim): venues use shared _BASELINE_LAB_NORMALS, HbA1c via physiology (DET-6)"
```

---

### Task 6: DKA/HHS scenario linkage (`chronic_glycemic_control`)

**Files:**
- Modify: `clinosim/types/` DiseaseProtocol model (add optional field) — find with `grep -rn "class DiseaseProtocol" clinosim/`
- Modify: `clinosim/simulator/inpatient.py:128-145` (apply override after `initialize_state`)
- Modify: `clinosim/modules/disease/reference_data/diabetic_ketoacidosis.yaml` (+ HHS file if present)
- Test: `tests/unit/` or `tests/integration/`

**Interfaces:**
- Consumes: `state.glycemic_control` (Task 2).
- Produces: `DiseaseProtocol.chronic_glycemic_control: float | None`; inpatient applies it.

- [ ] **Step 1: Failing test** — a DKA patient (even with no E11 condition) gets a high HbA1c (forced poor control):

```python
def test_dka_forces_poor_glycemic_control():
    # Run the DKA disease path (or unit-test the override application) and assert the
    # resulting state.glycemic_control <= 0.2 and HbA1c >= 9.0. Adapt to inpatient harness.
    ...
```

- [ ] **Step 2: Run — expect FAIL.**

- [ ] **Step 3: Add the protocol field + YAML + apply**

Add `chronic_glycemic_control: float | None = None` to the `DiseaseProtocol` Pydantic model.

In `diabetic_ketoacidosis.yaml` (top-level), add:

```yaml
chronic_glycemic_control: 0.1   # DKA implies poor chronic control -> HbA1c ~11%
```

In `inpatient.py`, after `state = initialize_state(...)` (line 128) and the `apply_disease_onset` calls, add:

```python
    if getattr(protocol, "chronic_glycemic_control", None) is not None:
        state.glycemic_control = protocol.chronic_glycemic_control
```

(Place it so the override also holds for the daily-labs `state` used at line 553. If state is rebuilt per day, set it in the same place the per-day state is initialized.)

- [ ] **Step 4: Run — expect PASS.**

- [ ] **Step 5: Commit**

```bash
git add clinosim/types/... clinosim/simulator/inpatient.py clinosim/modules/disease/reference_data/diabetic_ketoacidosis.yaml tests/...
git commit -m "feat(disease): DKA forces poor glycemic control -> high HbA1c"
```

---

### Task 7: Calibration audit, golden update, docs

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (tune coefficients if audit requires)
- Modify: `tests/e2e/test_alpha_golden.py:18` (`lab_result_count`)
- Modify: module READMEs (physiology axis count, ChronicCondition fields), `TODO.md`
- Audit scripts: write to `/tmp` only; never touch `output/`.

- [ ] **Step 1: Generate US + JP ~20k to `/tmp`, audit HbA1c**

Generate diabetic/non-diabetic/DKA cohorts; compute HbA1c medians per cohort. Compare to the spec Calibration table (non-DM 5.0-5.6; controlled DM 6.5-7.5; poor tail 8.5-11; DKA 9-13). Confirm Glucose co-moves.

- [ ] **Step 2: Tune coefficients** (`HBA1C_BEST/SPAN/NONDM_BASE`, `GLU_DM_*`, the `1.0 - gc_draw` mapping, DKA `chronic_glycemic_control`) until medians hit targets. Re-run audit. Pin the chosen test-state values in unit tests to the audit-measured states (not guesses) — same discipline as BNP PR #28.

- [ ] **Step 3: Update e2e golden** — run `pytest -m e2e -k alpha_golden`; update `lab_result_count` (57 → new) to reflect inpatient now resulting HbA1c. Confirm no OTHER golden constant drifts (state_snapshot_count etc. unchanged → main stream preserved).

- [ ] **Step 4: Full suite**

Run: `pytest -x -q` (unit+integration), then `pytest -m e2e -q`.
Expected: all green; only HbA1c/Glucose/Condition.stage/lab_result_count changed.

- [ ] **Step 5: Docs**

Update `clinosim/modules/physiology/README.md` (axis list +glycemic_control, HbA1c now modeled), `clinosim/modules/patient/README.md` / `clinosim/modules/facility` etc. as relevant (ChronicCondition.glycemic_control), `README.md` physiology axis count, and `TODO.md` (note optional future: narrative HbA1c mention; `controlled` field cleanup).

- [ ] **Step 6: Commit**

```bash
git add -u
git commit -m "chore: calibrate HbA1c/Glucose, update golden + docs"
```

---

## Self-Review

**Spec coverage:** §1 data model→T3; §2 formula→T1; §3 sampling→T3; §4 physiology integration→T1/T2; §5 scenario→T6; §6 baseline removal+DET-6→T4/T5; §7 observation support→T4; determinism→Global Constraints + T3 (draw-preserving) + T7 golden check; calibration→T7. All covered.

**Placeholders:** Test bodies for T3/T5/T6 say "adapt to existing harness" with `...` — these are deliberate because the activate/generate harness signatures must match the repo's existing test patterns (the implementer reads the neighboring tests). All *production* code steps show complete code.

**Type consistency:** `glycemic_control` (float|None) consistent across `ChronicCondition`, `PhysiologicalState`, `derive_lab_values` usage; `hba1c_from_glycemic_control(float)->float` used identically in T1/T3; `_BASELINE_LAB_NORMALS` name consistent T4/T5; `chronic_glycemic_control` consistent T6.
