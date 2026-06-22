# AKI Creatinine / DKA HCO3 surgical calibration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Calibrate AKI admit Creatinine and DKA admit HCO3 into KDIGO / ADA clinical bands by adjusting only the lab-derivation formulas in `derive_lab_values()`, without modifying `state.renal_function` or `state.ph_status` — preserving `clinical_course` RNG draws and avoiding the patient-cohort cascade that a prior YAML-based WIP attempt produced.

**Architecture:** BNP-pattern surgical fix (same shape as #28 BNP and #62 sepsis SBP). Change two single coefficients in `clinosim/modules/physiology/engine.py::derive_lab_values` (Cr low-renal slope 15→6.5, HCO3 metabolic-axis gain 24→31). Disease YAMLs and physiology state machine stay at `master`. Verified by a byte-diff invariant: every NDJSON except `Observation.ndjson` must be byte-identical to master at the same seed.

**Tech Stack:** Python 3.11+, pytest, numpy. Touches one file (`clinosim/modules/physiology/engine.py`) plus its unit-test file (`tests/unit/test_physiology.py`).

## Global Constraints

- **State invariant:** No modification to `state.renal_function` or `state.ph_status` derivation — including no edits to AKI / DKA disease YAMLs, no changes to `apply_disease_onset`, no changes to `_variable_range`, no changes to `apply_coupling_rules`. Only formulas inside `derive_lab_values()` may change.
- **Byte-diff gold criterion:** At fixed seed (US `-p 2000 -s 42` and JP `-p 2000 -s 42 --jp-insurance`), every NDJSON file except `Observation.ndjson` MUST be byte-identical to a same-seed `master` baseline. Patient count MUST match exactly.
- **Determinism (AD-16):** No new RNG draws, no random state, no `random.random()`. Lab formulas remain pure functions of `state`.
- **Authority (clinical bands):** AKI Cr targets follow KDIGO; DKA HCO3 targets follow ADA. No fabricated reference values — coefficients are derived analytically from the spec's mapping tables.
- **Branch hygiene:** Branch off current `master` (`a708a0b4`). Never reuse the stale `fix/aki-cr-dka-acidosis-calibration` branch (its WIP commit cascades).
- **Commit trailer:** Every commit ends with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` and `Claude-Session: <session-url>` lines.

---

### Task 1: Reset WIP and create the new branch

**Files:**
- Delete (branch): `fix/aki-cr-dka-acidosis-calibration` (local only — never pushed)
- Create (branch): `fix/aki-dka-surgical-calibration` from current `origin/master`

**Interfaces:**
- Consumes: nothing
- Produces: a clean working tree on a new branch off `master`, with the untracked spec from this PR (`docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md`) and plan (`docs/superpowers/plans/2026-06-22-aki-dka-surgical-calibration.md`) staged for the first commit.

- [ ] **Step 1: Confirm current state**

```bash
git status -s
git log --oneline -3
```

Expected:
```
?? docs/superpowers/plans/2026-06-20-bnp-hf-specificity.md
?? docs/superpowers/specs/2026-06-20-bnp-hf-specificity-design.md
?? docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md
?? docs/superpowers/plans/2026-06-22-aki-dka-surgical-calibration.md
?? output/
```

Current branch: `fix/aki-cr-dka-acidosis-calibration` with HEAD `eda694c2` (WIP).

- [ ] **Step 2: Move new spec/plan files aside so the reset does not lose them**

```bash
mkdir -p /tmp/aki-dka-pr-keep
cp docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md /tmp/aki-dka-pr-keep/
cp docs/superpowers/plans/2026-06-22-aki-dka-surgical-calibration.md /tmp/aki-dka-pr-keep/
ls /tmp/aki-dka-pr-keep/
```

Expected: both files listed.

- [ ] **Step 3: Switch to master and update**

```bash
git fetch
git checkout master
git pull --ff-only
git log --oneline -1
```

Expected: HEAD is `a708a0b4 Merge pull request #68 from TomoOkuyama/fix/snomed-verified-codes` (or newer if upstream advanced).

- [ ] **Step 4: Delete the stale WIP branch (local only)**

```bash
git branch -D fix/aki-cr-dka-acidosis-calibration
git branch | grep aki
```

Expected: no output (no AKI branch left).

- [ ] **Step 5: Create the new branch off master and restore spec/plan**

```bash
git checkout -b fix/aki-dka-surgical-calibration
cp /tmp/aki-dka-pr-keep/2026-06-22-aki-dka-surgical-calibration-design.md docs/superpowers/specs/
cp /tmp/aki-dka-pr-keep/2026-06-22-aki-dka-surgical-calibration.md       docs/superpowers/plans/
git status -s
```

Expected: both files appear as `??` (untracked) on the new branch.

- [ ] **Step 6: Stage and commit the spec + plan**

```bash
git add docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md \
        docs/superpowers/plans/2026-06-22-aki-dka-surgical-calibration.md
git commit -m "$(cat <<'EOF'
docs(physiology): spec + plan for AKI Cr / DKA HCO3 surgical calibration

The prior WIP (eda694c2 on fix/aki-cr-dka-acidosis-calibration) modified
AKI/DKA YAML initial_state_impact to land admit Cr / HCO3 in clinical bands,
but a byte-diff vs master (US p=2000, same seed) showed a large-scale
clinical_course cascade: 1509 non-AKI/DKA patients had differing Observations
and the patient cohort itself shifted (1299 vs 1274 patients). This spec/plan
adopts the BNP-pattern (#28) / sepsis SBP (#62) approach: keep state at master,
adjust only the Cr and HCO3 formulas inside derive_lab_values.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit succeeds, hook output OK.

- [ ] **Step 7: Verify clean starting state**

```bash
git log --oneline master..HEAD
git status -s
```

Expected:
- one new commit on the branch (the spec/plan docs)
- working tree shows only untracked `output/` and the unrelated `docs/superpowers/{specs,plans}/2026-06-20-bnp-hf-specificity*` files (these belong to a different PR and stay untracked).

---

### Task 2: Write the failing Creatinine-curve regression test (TDD)

**Files:**
- Modify: `tests/unit/test_physiology.py` (append new test; do not yet touch existing AKI test).

**Interfaces:**
- Consumes: existing helpers `initialize_state`, `derive_lab_values`, `PatientPhysiologicalProfile` from `clinosim.modules.physiology.engine`.
- Produces: pinning test `test_creatinine_curve_matches_clinical_bands` consumed by Task 3 as the gate.

The curve table comes from the spec's "Mapping check (base_cr = 0.9, male)" section. With the new coefficient `6.5`, `Cr = base_cr / 0.5 + (0.5 - renal) * 6.5 = 1.8 + (0.5 - renal) * 6.5`.

- [ ] **Step 1: Append the curve-pinning test**

Add to the end of `tests/unit/test_physiology.py` (after the existing tests, keep blank line between):

```python
@pytest.mark.unit
def test_creatinine_curve_matches_clinical_bands():
    """Pin the (state.renal_function -> Creatinine) curve to clinically realistic bands.

    Guard against an accidental re-steepening of the low-renal slope. The 0.5
    boundary value MUST stay continuous between the >0.5 (base_cr / renal) and
    <=0.5 (linear) branches.
    """
    from clinosim.modules.physiology.engine import (
        derive_lab_values,
        PhysiologicalState,
    )

    # Male baseline (base_cr = 0.9). State is fabricated directly so we exercise
    # the formula independent of disease onset / coupling.
    expected = {
        # state.renal_function -> Cr (mg/dL), tolerance 0.05
        0.0: 5.05,   # severe AKI (anuric state) - KDIGO 3 mid-high
        0.1: 4.40,   # KDIGO 3
        0.2: 3.75,   # KDIGO 2
        0.3: 3.10,   # CKD3 typical
        0.4: 2.45,   # early CKD
        0.5: 1.80,   # baseline (boundary, continuous with renal>0.5 branch)
    }
    for renal, target in expected.items():
        st = PhysiologicalState(patient_id="pt")
        st.renal_function = renal
        labs = derive_lab_values(st, sex="M", age=70)
        assert abs(labs["Creatinine"] - target) < 0.05, (
            f"renal={renal:.2f} Cr={labs['Creatinine']:.2f} expected≈{target}"
        )

    # Continuity at the 0.5 boundary: top branch (base_cr / renal) and bottom
    # branch (linear) must agree to within 0.01.
    st = PhysiologicalState(patient_id="pt")
    st.renal_function = 0.5
    cr_at_05 = derive_lab_values(st, sex="M", age=70)["Creatinine"]
    st.renal_function = 0.500001
    cr_just_above = derive_lab_values(st, sex="M", age=70)["Creatinine"]
    assert abs(cr_at_05 - cr_just_above) < 0.01
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
pytest tests/unit/test_physiology.py::test_creatinine_curve_matches_clinical_bands -v
```

Expected: FAIL. The current coefficient is `15`, which produces e.g. `renal=0.0 -> Cr=9.30` vs. target `5.05`, so the first assertion fires.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
test(physiology): pin Creatinine curve to KDIGO clinical bands (failing)

Adds a regression guard for the (state.renal_function -> Cr) mapping. With
the current low-renal slope coefficient of 15, severe AKI (state.renal=0)
maps to Cr ~9.3 mg/dL (ESRD), which is clinically too extreme. The next
commit drops the slope to 6.5 to land severe AKI at Cr ~5 (KDIGO 3) and
CKD3 (renal~0.3) at Cr ~3 (typical), matching published bands.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit OK.

---

### Task 3: Land the Creatinine coefficient change (15 → 6.5)

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (single-line numeric change inside `derive_lab_values`, around line 252-254).

**Interfaces:**
- Consumes: the failing test from Task 2.
- Produces: a green `test_creatinine_curve_matches_clinical_bands` and an updated (Cr-only) lab derivation. Does NOT touch the AKI YAML / state / floor.

- [ ] **Step 1: Locate the Cr formula**

Read `clinosim/modules/physiology/engine.py:248-258`. The current low-renal branch reads:

```python
    # --- Renal ---
    base_cr = 0.9 if sex == "M" else 0.7
    if renal > 0.5:
        labs["Creatinine"] = base_cr / renal
    else:
        labs["Creatinine"] = base_cr / 0.5 + (0.5 - renal) * 15
    labs["BUN"] = 15.0 / max(renal, 0.1)
```

- [ ] **Step 2: Apply the surgical edit**

Edit `clinosim/modules/physiology/engine.py:248-258`. Replace the renal block above with:

```python
    # --- Renal ---
    base_cr = 0.9 if sex == "M" else 0.7
    if renal > 0.5:
        labs["Creatinine"] = base_cr / renal
    else:
        # Low-renal slope, BNP-pattern surgical calibration (2026-06-22). The
        # earlier coefficient of 15 mapped state.renal_function=0 to Cr ~9
        # (ESRD/dialysis), inconsistent with KDIGO 3 admit Cr (~5-6) and CKD3
        # (renal~0.3) admit Cr (~2.5-3). 6.5 lands severe AKI at Cr ~5 and
        # CKD3 at Cr ~3, leaving state and clinical_course untouched (avoids
        # the master-RNG cascade documented in spec 2026-06-22-aki-dka-...).
        labs["Creatinine"] = base_cr / 0.5 + (0.5 - renal) * 6.5
    labs["BUN"] = 15.0 / max(renal, 0.1)
```

- [ ] **Step 3: Run the pinning test alone**

```bash
pytest tests/unit/test_physiology.py::test_creatinine_curve_matches_clinical_bands -v
```

Expected: PASS.

- [ ] **Step 4: Run the full physiology unit file**

```bash
pytest tests/unit/test_physiology.py -v
```

Expected: every test passes EXCEPT possibly `test_aki_creatinine_not_anuric_on_elderly_baseline` (its ceilings are still the WIP-era values which were tighter than the new BNP-pattern curve will produce for some severities). Note any failure here for Task 4.

- [ ] **Step 5: Commit the formula change**

```bash
git add clinosim/modules/physiology/engine.py
git commit -m "$(cat <<'EOF'
fix(physiology): Cr low-renal slope 15->6.5 (BNP-pattern, state unchanged)

Surgical lab-derivation change inside derive_lab_values. state.renal_function
is unchanged, so clinical_course branching consumes the same RNG draws as
master and the patient cohort is preserved (byte-diff invariant). Only the
Cr value rendered in Observations shifts toward the KDIGO clinical band:

    renal=0.0 (severe AKI):  9.3 -> 5.05  (KDIGO 3 mid-high)
    renal=0.2 (KDIGO 2):     6.3 -> 3.75
    renal=0.3 (CKD3):        4.8 -> 3.10  (typical CKD3)
    renal=0.5 (baseline):    1.80 unchanged (continuous boundary)

Spec: docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit OK.

---

### Task 4: Update the elderly-AKI guard test to the new curve

**Files:**
- Modify: `tests/unit/test_physiology.py` (the existing `test_aki_creatinine_not_anuric_on_elderly_baseline` test, near the end of the file — added by the WIP commit on the deleted branch IF the unit file currently contains it; if Task 1's reset took the file back to its pre-WIP form, this test does not exist and Step 1 below adds it instead).

**Interfaces:**
- Consumes: Task 3's new Cr formula.
- Produces: a hardened acceptance test for AKI admit Cr that aligns with the spec's predicted bands.

`master`'s `test_physiology.py` does NOT contain this test — it was added by the WIP. After the reset in Task 1, the file is back to master. We add the test fresh here, using the new curve's predicted values: with `renal_reserve=0.60` (elderly, no CKD) and master AKI impacts (`-0.25 / -0.45 / -0.65`), end state = `0.35 / 0.15 / 0.0` → Cr = `2.78 / 4.08 / 5.05`. Ceilings: `(3.0, 4.5, 5.5)`.

- [ ] **Step 1: Verify the test does not already exist**

```bash
grep -n "test_aki_creatinine_not_anuric_on_elderly_baseline\|test_renal_function_clamp_floor_via_onset\|test_dka_moderate_acidosis_in_clinical_range" tests/unit/test_physiology.py
```

Expected: no output (Task 1 reset removed the WIP additions).

- [ ] **Step 2: Append the new AKI guard test**

Append to `tests/unit/test_physiology.py`:

```python
@pytest.mark.unit
def test_aki_creatinine_not_anuric_on_elderly_baseline():
    """AKI on a typical elderly baseline (no CKD) should land Cr in the KDIGO 1-3
    envelope, not pin Creatinine at dialysis/ESRD level. Ceilings track the
    BNP-pattern surgical curve (Task 3 changed the slope to 6.5). state is at
    master, so this is a pure lab-formula assertion."""
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.physiology.engine import (
        apply_disease_onset,
        derive_lab_values,
        initialize_state,
        PatientPhysiologicalProfile,
    )

    proto = load_disease_protocol("acute_kidney_injury")
    for severity, ceiling in (("mild", 3.0), ("moderate", 4.5), ("severe", 5.5)):
        prof = PatientPhysiologicalProfile(renal_reserve=0.60)  # elderly, no CKD
        state = initialize_state(prof, [], "pt")
        state = apply_disease_onset(state, severity, proto.initial_state_impact)
        labs = derive_lab_values(state, sex="M", age=78)
        assert labs["Creatinine"] < ceiling, (
            f"{severity}: state.renal={state.renal_function:.2f} "
            f"Cr={labs['Creatinine']:.2f} >= ceiling {ceiling}"
        )
```

- [ ] **Step 3: Run the test**

```bash
pytest tests/unit/test_physiology.py::test_aki_creatinine_not_anuric_on_elderly_baseline -v
```

Expected: PASS for all three severities.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
test(physiology): AKI admit Cr stays inside KDIGO envelope (no ESRD pinning)

Acceptance test for the AKI calibration goal: elderly (renal_reserve=0.60)
patients with mild / moderate / severe AKI (master YAML impacts) admit at
Cr < 3.0 / 4.5 / 5.5 respectively. State is at master; only Task 3's slope
change moves the Cr.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit OK.

---

### Task 5: Write the failing HCO3 metabolic-axis pinning test (TDD)

**Files:**
- Modify: `tests/unit/test_physiology.py` (append).

**Interfaces:**
- Consumes: existing `derive_lab_values`, `PhysiologicalState`.
- Produces: failing pin test `test_hco3_metabolic_axis_matches_ada_bands` consumed by Task 6.

Pure-metabolic axis (`respiratory_fraction=0`, `mf=1`). Henderson-Hasselbalch + Winter's compensation also runs, so we test the HCO3 output (not pH) for tight tolerance. Targets from the spec mapping table.

- [ ] **Step 1: Append the test**

Append to `tests/unit/test_physiology.py`:

```python
@pytest.mark.unit
def test_hco3_metabolic_axis_matches_ada_bands():
    """Pin the (state.ph_status -> HCO3) curve on the pure metabolic axis
    (respiratory_fraction=0). Guards the DKA / sepsis / CKD HCO3 calibration."""
    from clinosim.modules.physiology.engine import (
        derive_lab_values,
        PhysiologicalState,
    )

    # state.ph_status -> HCO3 (mEq/L), tolerance 0.10
    expected = {
        0.00: 24.00,    # no disturbance
        -0.10: 20.90,   # CKD chronic mild metabolic
        -0.15: 19.35,   # severe sepsis
        -0.35: 13.15,   # DKA moderate (ADA moderate band: 10-15)
        -0.60: 5.40,    # DKA severe (ADA severe band: <10; clamped at 5.0 floor below -0.61)
    }
    for ph, target in expected.items():
        st = PhysiologicalState(patient_id="pt")
        st.respiratory_fraction = 0.0   # pure metabolic axis
        st.ph_status = ph
        labs = derive_lab_values(st, sex="M", age=55)
        assert abs(labs["HCO3"] - target) < 0.10, (
            f"ph_status={ph:.2f} HCO3={labs['HCO3']:.2f} expected≈{target}"
        )
```

- [ ] **Step 2: Run the test (expected to fail)**

```bash
pytest tests/unit/test_physiology.py::test_hco3_metabolic_axis_matches_ada_bands -v
```

Expected: FAIL. Current metabolic-axis gain is `24`, e.g. `ph=-0.35 -> HCO3=15.6` vs. target `13.15`.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
test(physiology): pin HCO3 metabolic axis to ADA DKA bands (failing)

Adds a regression guard for the (state.ph_status -> HCO3) mapping on the
pure metabolic axis. Current gain (24) leaves DKA moderate HCO3 at 15.6
(just outside ADA moderate band 10-15); next commit raises the gain to 31
to land moderate DKA at ~13.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit OK.

---

### Task 6: Land the HCO3 coefficient change (24 → 31)

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (single numeric change inside `derive_lab_values`, around line 320).

**Interfaces:**
- Consumes: failing test from Task 5.
- Produces: green `test_hco3_metabolic_axis_matches_ada_bands`. pH follows automatically via Henderson-Hasselbalch + Winter's already-present code below.

- [ ] **Step 1: Locate the HCO3 formula**

Read `clinosim/modules/physiology/engine.py:317-321`. The current metabolic-axis line is:

```python
    rf = clamp(state.respiratory_fraction, 0.0, 1.0)
    mf = 1.0 - rf
    hco3 = 24.0 + ph * mf * 24.0   # metabolic load drives bicarbonate
    pco2 = 40.0 - ph * rf * 40.0   # respiratory load drives CO2 (acidosis → retention)
```

- [ ] **Step 2: Apply the surgical edit**

Edit `clinosim/modules/physiology/engine.py:317-321`. Replace the HCO3 line:

```python
    rf = clamp(state.respiratory_fraction, 0.0, 1.0)
    mf = 1.0 - rf
    # Metabolic-axis gain, BNP-pattern surgical calibration (2026-06-22). 24 left
    # DKA moderate (ph_status=-0.35) at HCO3 ~15.6, outside the ADA moderate band
    # (10-15). 31 lands moderate DKA at HCO3 ~13 (mid-band) and severe DKA at <10,
    # while CKD chronic (ph_status~-0.10) drops only from 21.6 to 20.9. state is
    # unchanged. Spec: docs/superpowers/specs/2026-06-22-aki-dka-surgical-...
    hco3 = 24.0 + ph * mf * 31.0   # metabolic load drives bicarbonate
    pco2 = 40.0 - ph * rf * 40.0   # respiratory load drives CO2 (acidosis → retention)
```

- [ ] **Step 3: Run the HCO3 pinning test alone**

```bash
pytest tests/unit/test_physiology.py::test_hco3_metabolic_axis_matches_ada_bands -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/physiology/engine.py
git commit -m "$(cat <<'EOF'
fix(physiology): HCO3 metabolic-axis gain 24->31 (BNP-pattern, state unchanged)

Surgical lab-derivation change. state.ph_status is unchanged, so
clinical_course branching and the patient cohort are preserved. Only the
HCO3 / pH numbers in Observations shift toward the ADA DKA clinical bands:

    ph=-0.10 (CKD chronic):     21.6 -> 20.9  (minor)
    ph=-0.15 (severe sepsis):   20.4 -> 19.35 (slight deepening)
    ph=-0.35 (DKA moderate):    15.6 -> 13.15 (ADA moderate 10-15)
    ph=-0.60 (DKA severe):       9.6 ->  5.40 (ADA severe <10)

pH follows via Henderson-Hasselbalch + Winter's compensation already in
derive_lab_values; no separate pH tweak needed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit OK.

---

### Task 7: Add the DKA moderate-acidosis acceptance test

**Files:**
- Modify: `tests/unit/test_physiology.py` (append).

**Interfaces:**
- Consumes: Task 6's HCO3 formula.
- Produces: end-to-end acceptance test that DKA moderate scenarios land in the ADA moderate band, with HCO3 reading the disease protocol from YAML.

- [ ] **Step 1: Append the test**

Append to `tests/unit/test_physiology.py`:

```python
@pytest.mark.unit
def test_dka_moderate_acidosis_in_clinical_range():
    """Moderate DKA admit should produce HCO3 ~10-15 (ADA moderate) and pH
    ~7.0-7.27 with master's initial_state_impact. state unchanged; Task 6's
    HCO3 gain (24->31) is what lands the band."""
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.physiology.engine import (
        apply_disease_onset,
        derive_lab_values,
        initialize_state,
        PatientPhysiologicalProfile,
    )

    proto = load_disease_protocol("diabetic_ketoacidosis")
    state = initialize_state(PatientPhysiologicalProfile(), [], "pt")
    # acid_base_type='metabolic' is the DKA default in apply_disease_onset.
    state = apply_disease_onset(state, "moderate", proto.initial_state_impact)
    labs = derive_lab_values(state, sex="M", age=55)
    assert 10.0 <= labs["HCO3"] <= 15.5, f"HCO3={labs['HCO3']:.2f}"
    assert labs["pH"] <= 7.27, f"pH={labs['pH']:.2f}"
```

- [ ] **Step 2: Run the test**

```bash
pytest tests/unit/test_physiology.py::test_dka_moderate_acidosis_in_clinical_range -v
```

Expected: PASS. (Reference: spec maps `ph_status=-0.35 * mf=1` → HCO3 ≈ 13.15; pH ≈ 7.26.)

- [ ] **Step 3: Run the full physiology unit file**

```bash
pytest tests/unit/test_physiology.py -v
```

Expected: every test passes.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
test(physiology): DKA moderate admit HCO3 lands in ADA moderate band

Acceptance test reading the master DKA YAML (ph_status=-0.35 at moderate
severity) and asserting derive_lab_values produces HCO3 in [10, 15.5] and
pH <= 7.27. Closes the test surface around the Task 6 HCO3 gain change.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit OK.

---

### Task 8: Run the full test suite

**Files:** none modified.

**Interfaces:**
- Consumes: the branch HEAD with Tasks 1-7 applied.
- Produces: confidence that no integration / e2e test depended on the old Cr / HCO3 magnitudes outside the new bands.

- [ ] **Step 1: Unit + integration**

```bash
pytest -m "unit or integration" --tb=short -q
```

Expected: ALL pass (the master baseline reported 483 passed). The new tests bring the count up; goal is zero failures.

- [ ] **Step 2: e2e**

```bash
pytest tests/e2e/ --tb=short -q
```

Expected: 39/39 pass.

- [ ] **Step 3: If any failure**

For each failure: read the assertion, decide whether it depended on a now-stale Cr / HCO3 magnitude or whether it indicates a genuine regression. Spec scope explicitly does NOT allow changing assertions outside the new bands without explicit justification — STOP and surface the failure to the human before patching.

If everything passes, continue to Task 9.

---

### Task 9: Byte-diff verification — the gold criterion

**Files:** none modified.

**Interfaces:**
- Consumes: the branch HEAD with Tasks 1-7 applied.
- Produces: a recorded byte-diff between master and branch confirming the invariant in the spec ("only `Observation.ndjson` differs").

Note: this task lives in `/tmp` and does not commit anything to the branch. Results inform Task 10's audit doc.

- [ ] **Step 1: Generate master baseline (US + JP, p=2000, seed 42)**

```bash
rm -rf /tmp/byte_master_us /tmp/byte_master_jp /tmp/byte_branch_us /tmp/byte_branch_jp
git stash -u -m "byte-diff baseline keep" || true
git checkout master
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US -o /tmp/byte_master_us --format cif fhir 2>&1 | tail -3
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP -o /tmp/byte_master_jp --format cif fhir --jp-insurance 2>&1 | tail -3
```

Expected: two output directories, each with `cif/` and `fhir_r4/` subdirs.

- [ ] **Step 2: Generate branch output (same seeds, same flags)**

```bash
git checkout fix/aki-dka-surgical-calibration
git stash pop || true
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US -o /tmp/byte_branch_us --format cif fhir 2>&1 | tail -3
python -m clinosim.simulator.cli generate -p 2000 -s 42 --country JP -o /tmp/byte_branch_jp --format cif fhir --jp-insurance 2>&1 | tail -3
```

Expected: matching output structure.

- [ ] **Step 3: Compare every NDJSON via md5**

Write to `/tmp/bytecheck.py`:

```python
import hashlib
import os
import sys

def md5(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()

def check(label, master_dir, branch_dir):
    print(f"=== {label} ===")
    files = sorted(os.listdir(f"{master_dir}/fhir_r4"))
    fail = 0
    for f in files:
        if not f.endswith(".ndjson"):
            continue
        m = md5(f"{master_dir}/fhir_r4/{f}")
        b = md5(f"{branch_dir}/fhir_r4/{f}")
        status = "same"
        if m != b:
            # only Observation.ndjson is allowed to differ
            if f == "Observation.ndjson":
                status = "DIFFERS (expected for Observation)"
            else:
                status = "*** UNEXPECTED DIFFERENCE ***"
                fail += 1
        print(f"  {f:40s} {status}")
    return fail

fail = check("US", "/tmp/byte_master_us", "/tmp/byte_branch_us")
fail += check("JP", "/tmp/byte_master_jp", "/tmp/byte_branch_jp")
sys.exit(0 if fail == 0 else 1)
```

Run:

```bash
python3 /tmp/bytecheck.py
echo "exit=$?"
```

Expected: only `Observation.ndjson` differs; every other NDJSON identical; exit code 0.

If any other file differs, STOP. The fix is leaking state somehow — re-read the diff in derive_lab_values and confirm only the Cr and HCO3 lines were touched.

- [ ] **Step 4: Confirm patient count is identical (gold criterion)**

```bash
for d in /tmp/byte_master_us /tmp/byte_branch_us /tmp/byte_master_jp /tmp/byte_branch_jp; do
    n=$(wc -l < "$d/fhir_r4/Patient.ndjson")
    echo "$d: $n patients"
done
```

Expected: master and branch produce identical patient counts in both US and JP.

- [ ] **Step 5: Sample Observation diff (sanity check the intended change)**

Confirm that the Observation differences are Cr / HCO3 / pH only — not, e.g., resource id changes:

```bash
python3 - <<'PYEOF'
import json
from collections import Counter

def affected_loinc(master_path, branch_path):
    """For each LOINC code, count how many Observations differ in value."""
    counts = Counter()
    seen = Counter()
    with open(master_path) as fm, open(branch_path) as fb:
        for lm, lb in zip(fm, fb):
            if lm == lb:
                continue
            m = json.loads(lm); b = json.loads(lb)
            code = (m.get("code", {}).get("coding") or [{}])[0].get("code", "?")
            seen[code] += 1
            if m.get("valueQuantity", {}).get("value") != b.get("valueQuantity", {}).get("value"):
                counts[code] += 1
    return counts, seen

for label, base_m, base_b in (
    ("US", "/tmp/byte_master_us/fhir_r4/Observation.ndjson", "/tmp/byte_branch_us/fhir_r4/Observation.ndjson"),
    ("JP", "/tmp/byte_master_jp/fhir_r4/Observation.ndjson", "/tmp/byte_branch_jp/fhir_r4/Observation.ndjson"),
):
    c, s = affected_loinc(base_m, base_b)
    print(f"=== {label} ===")
    print("top 10 LOINC codes by value change:")
    for code, n in c.most_common(10):
        print(f"  {code}  {n} value changes")
PYEOF
```

Expected: top codes are Cr (LOINC 2160-0 or similar), HCO3 (1959-6), pH (2744-1). No structural ids — only numerical-value drifts.

- [ ] **Step 6: Save the byte-diff result to a temp file for the audit doc**

```bash
{
  echo "byte-diff snapshot $(git log --oneline -1)";
  echo "";
  python3 /tmp/bytecheck.py;
  echo "";
  for d in /tmp/byte_master_us /tmp/byte_branch_us /tmp/byte_master_jp /tmp/byte_branch_jp; do
      echo "$d: $(wc -l < $d/fhir_r4/Patient.ndjson) patients";
  done
} > /tmp/bytediff_report.txt
cat /tmp/bytediff_report.txt
```

Expected: a text file with the byte-diff status that Task 10's audit doc will quote.

---

### Task 10: Calibration audit at production scale

**Files:**
- Create: `docs/reviews/2026-06-22-aki-dka-surgical-calibration-audit.md`

**Interfaces:**
- Consumes: branch HEAD; byte-diff report from Task 9.
- Produces: an audit doc documenting admit-day Cr / HCO3 medians and percentiles in the new branch vs master, and confirming the invariant byte-diff (committed to the branch as the docs PR companion).

- [ ] **Step 1: Generate a larger sample for percentile statistics**

```bash
rm -rf /tmp/audit_master_us /tmp/audit_branch_us /tmp/audit_master_jp /tmp/audit_branch_jp
git stash -u -m "audit checkpoint" || true
git checkout master
python -m clinosim.simulator.cli generate -p 8000 -s 42 --country US -o /tmp/audit_master_us --format cif 2>&1 | tail -3
python -m clinosim.simulator.cli generate -p 4000 -s 42 --country JP -o /tmp/audit_master_jp --format cif --jp-insurance 2>&1 | tail -3

git checkout fix/aki-dka-surgical-calibration
git stash pop || true
python -m clinosim.simulator.cli generate -p 8000 -s 42 --country US -o /tmp/audit_branch_us --format cif 2>&1 | tail -3
python -m clinosim.simulator.cli generate -p 4000 -s 42 --country JP -o /tmp/audit_branch_jp --format cif --jp-insurance 2>&1 | tail -3
```

Expected: four CIF outputs.

- [ ] **Step 2: Extract admit-day Cr / HCO3 percentiles by diagnosis cohort**

Write `/tmp/audit_calibration.py`:

```python
import json
import os
import statistics as st
import sys
from pathlib import Path

def load_cif(cif_dir):
    """Yield patient records from a CIF directory."""
    p = Path(cif_dir) / "cif"
    if not p.exists():
        return
    for jf in sorted(p.glob("*.json")):
        with open(jf) as f:
            data = json.load(f)
            patients = data if isinstance(data, list) else [data]
            for rec in patients:
                yield rec

def percentiles(values):
    if not values:
        return {}
    s = sorted(values)
    return {
        "n": len(s),
        "p25": s[len(s)//4],
        "p50": s[len(s)//2],
        "p75": s[(3*len(s))//4],
    }

def admit_labs(rec):
    """Return (admit_cr, admit_hco3) or (None, None) if no admit-day lab observed."""
    cr = hco3 = None
    for enc in rec.get("encounters", []):
        # First-day labs (admit-day) — find earliest lab with date == admit date
        admit = enc.get("admission_datetime", "")[:10]
        for lab in rec.get("lab_results", []):
            if not lab.get("collected_at", "").startswith(admit):
                continue
            code = lab.get("internal_name") or lab.get("name") or ""
            if code in ("Creatinine", "Cr"):
                cr = lab.get("value")
            elif code in ("HCO3", "Bicarbonate"):
                hco3 = lab.get("value")
        if cr is not None or hco3 is not None:
            break
    return cr, hco3

def diagnose_cohort(rec):
    """Return primary admit diagnosis 3-char prefix (e.g. 'N17')."""
    cd = rec.get("clinical_diagnosis", {})
    code = cd.get("admission_diagnosis_code", "") or ""
    return code[:3] if code else "?"

def audit(label, cif_dir):
    print(f"\n=== {label} ===")
    cohort_cr = {}
    cohort_hco3 = {}
    for rec in load_cif(cif_dir):
        cr, hco3 = admit_labs(rec)
        pref = diagnose_cohort(rec)
        if cr is not None:
            cohort_cr.setdefault(pref, []).append(cr)
        if hco3 is not None:
            cohort_hco3.setdefault(pref, []).append(hco3)
    print("Cr by admit dx prefix (top 6 by n):")
    for p, vals in sorted(cohort_cr.items(), key=lambda x: -len(x[1]))[:6]:
        s = percentiles(vals)
        print(f"  {p:5s}  {s}")
    print("HCO3 by admit dx prefix (top 6):")
    for p, vals in sorted(cohort_hco3.items(), key=lambda x: -len(x[1]))[:6]:
        s = percentiles(vals)
        print(f"  {p:5s}  {s}")

audit("US master", "/tmp/audit_master_us")
audit("US branch", "/tmp/audit_branch_us")
audit("JP master", "/tmp/audit_master_jp")
audit("JP branch", "/tmp/audit_branch_jp")
```

Run:

```bash
python3 /tmp/audit_calibration.py 2>&1 | tee /tmp/audit_calibration.txt
```

Expected: prints p25/p50/p75 of admit Cr and HCO3 by ICD prefix per cohort. The relevant lines are AKI (`N17`) for Cr and DKA (`E10/E11`) for HCO3.

If the calibration target is missed (e.g., AKI p50 still > 6, or DKA p50 still > 15), STOP and tune the coefficient: re-edit `derive_lab_values` (the line touched by Task 3 or Task 6 only) and rerun the audit. Document the chosen coefficient.

If the calibration is on target, continue to Step 3.

- [ ] **Step 3: Write the audit document**

Create `docs/reviews/2026-06-22-aki-dka-surgical-calibration-audit.md` containing:

```markdown
# AKI Cr / DKA HCO3 surgical calibration — audit (2026-06-22)

## Summary

PR `fix/aki-dka-surgical-calibration` reduces the AKI admit Creatinine and DKA admit
HCO3 lab values into the published KDIGO / ADA clinical bands by adjusting two
single coefficients inside `derive_lab_values()`, leaving state and disease YAMLs
at master. The byte-diff invariant ("only `Observation.ndjson` differs") holds at
US p=2000 and JP p=2000 seeds; the patient cohort is preserved exactly.

## Byte-diff invariant (gold criterion)

[paste the contents of /tmp/bytediff_report.txt verbatim here]

## Admit-day percentile audit

[paste the contents of /tmp/audit_calibration.txt verbatim here]

### Interpretation

- **N17 (AKI)** — Cr p50 [fill from audit] (target: 2-6 KDIGO 1-3). Master was p50 ~8.
- **E11 / E10 (DKA)** — HCO3 p50 [fill from audit] (target: 10-15 ADA moderate). Master was p50 ~17.
- **N18 (CKD)** — Cr p50 [fill from audit] (target: 1.5-3 published CKD3). Side benefit; master overestimated.
- **All other prefixes** — unchanged within rounding (state-independent labs).

## Why no cascade

Spec ref: `docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md`.
state.renal_function and state.ph_status are unchanged from master, so
`clinical_course/engine.py::evaluate_complications` reads identical state and
consumes identical RNG draws. Population generation, encounter order, medication
streams, immunization, family history, etc. are byte-identical to master.

## Follow-ups

- Track BUN / K / eGFR distributions at next audit; state-driven labs not retuned here.
- DKA pH lower bound: spec noted risk of pH being driven below the Henderson-Hasselbalch
  clamp at severe ph_status; record the p1 from audit and confirm it stays above 6.80.
```

- [ ] **Step 4: Commit the audit doc**

```bash
git add docs/reviews/2026-06-22-aki-dka-surgical-calibration-audit.md
git commit -m "$(cat <<'EOF'
docs(review): audit for AKI Cr / DKA HCO3 surgical calibration

Captures the byte-diff invariant (only Observation.ndjson differs) and the
admit-day percentile audit (US p=8000, JP p=4000) confirming AKI Cr and DKA
HCO3 land in the KDIGO / ADA bands. State and patient cohort preserved.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: commit OK.

---

### Task 11: Push and open the PR

**Files:** none modified.

**Interfaces:**
- Consumes: the branch with Tasks 1-10 committed.
- Produces: an open PR ready for human review and merge.

- [ ] **Step 1: Push the branch**

```bash
git push -u origin fix/aki-dka-surgical-calibration
```

Expected: push succeeds, branch tracked.

- [ ] **Step 2: Create the PR**

```bash
gh pr create --title "fix(physiology): AKI Cr / DKA HCO3 surgical calibration (state unchanged)" --body "$(cat <<'EOF'
## Summary

- Adjust two coefficients inside `derive_lab_values()` to land AKI admit
  Creatinine in the KDIGO 1-3 envelope and DKA admit HCO3 in the ADA moderate
  band, without modifying any state variable or disease YAML.
- BNP-pattern surgical fix (#28 / #62): no `clinical_course` cascade, patient
  cohort preserved byte-for-byte across all non-`Observation` resources at fixed
  seed (US p=2000 + JP p=2000).
- Replaces the prior WIP on `fix/aki-cr-dka-acidosis-calibration` (eda694c2),
  which mutated AKI/DKA YAML `initial_state_impact` and was found to cascade
  through master-RNG-shared clinical course (1509 non-AKI/DKA patient
  Observations shifted, patient count drifted 1274 → 1299).

Spec: `docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md`
Audit: `docs/reviews/2026-06-22-aki-dka-surgical-calibration-audit.md`

## Changes

- `clinosim/modules/physiology/engine.py`
  - Cr low-renal slope coefficient: 15 → 6.5
  - HCO3 metabolic-axis gain coefficient: 24 → 31
- `tests/unit/test_physiology.py` adds four guards:
  - `test_creatinine_curve_matches_clinical_bands` (renal → Cr table)
  - `test_aki_creatinine_not_anuric_on_elderly_baseline` (KDIGO ceilings)
  - `test_hco3_metabolic_axis_matches_ada_bands` (ph_status → HCO3 table)
  - `test_dka_moderate_acidosis_in_clinical_range` (ADA moderate band)
- Two doc files (spec, audit).

## Test plan

- [x] `pytest -m "unit or integration"` — all green (483+ tests)
- [x] `pytest tests/e2e/` — 39/39 green
- [x] Byte-diff invariant: only `Observation.ndjson` differs at US p=2000 / JP p=2000 seed 42; all other NDJSON byte-identical to master
- [x] Patient count identical to master (US and JP)
- [x] Audit (US p=8000 / JP p=4000): AKI N17 admit Cr p50 in [2, 6], DKA E10/E11 admit HCO3 p50 in [10, 15]

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01RrLyGbo9G1dqiPUpSqDYtm
EOF
)"
```

Expected: PR URL returned. Report URL to the human.

- [ ] **Step 3: Surface follow-up reminders**

After the PR is open, mention to the human (not as a commit):

- The `docs/superpowers/{plans,specs}/2026-06-20-bnp-hf-specificity*` untracked files belong to a different (unrelated) PR — they remain untracked on this branch and are out of scope.
- After merge, `output/` left over in working tree from earlier byte-diff runs can be deleted (`rm -rf output/`).

---

## Self-Review Notes

- Spec coverage: every numbered requirement in the spec is addressed in a task. The "What is NOT changed" section maps to the global state-invariant constraint and is implicitly enforced by the byte-diff invariant in Task 9.
- Coefficient values (Cr 6.5, HCO3 31) appear verbatim everywhere they are referenced.
- Task 4 explicitly handles the "master may not have this test" reality (the WIP added it, the reset removed it).
- The single risk noted in the spec ("hidden state dependency") is operationalized in Task 9 Step 3 (any non-`Observation` byte difference triggers a STOP).
- Task 10 has an explicit "if calibration miss, retune coefficient and rerun" loop, matching the spec's "audit IS the source of truth" guidance.
