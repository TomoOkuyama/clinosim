# BMP Cl/Ca Physiology Implementation Plan (Phase 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Cl and Ca to `derive_lab_values` so the BMP canonical 8 (Na/K/Cl/CO2/BUN/Cr/Glucose/Ca) is fully emit-able, introduce an `anion_gap_status` axis on `PhysiologicalState` for AG-aware Cl coupling, set AG values on disease/encounter YAMLs where AG is recorded as varying in real-world BMPs, raise BMP `min_components` 5→7, and verify with byte-diff invariant + clinical coherence audit.

**Architecture:** Pure-function extension of `derive_lab_values` (BNP-pattern surgical, no state mutation). The new `anion_gap_status` axis is orthogonal to the AD-57 acid-base two-axis model (does NOT affect pH/HCO3/pCO2). RNG consumption stays zero in physiology, so AD-16 is auto-satisfied; per-parent `panel_specimen_seed` (PR #74) handles BMP-as-one-specimen at order time. Disease/encounter YAML files set AG axis in `initial_state_impact` (existing pattern from DKA/sepsis/gastroenteritis). `lab_panel_groups.yaml` BMP threshold rises 5→7 (canonical N − 1 rule from PR #75).

**Tech Stack:** Python 3.11+, Pydantic for YAML loaders, `@dataclass` for runtime types, pytest, numpy, ruff, mypy strict.

## Global Constraints

- Code: Python 3.11+, ruff format, mypy strict, line length 100
- Types: `@dataclass` for runtime types (PhysiologicalState), Pydantic for YAML loaders
- AD-16: deterministic with seed, no `random.random()`, no shared mutable state. The `anion_gap_status` axis MUST NOT mutate other state variables via `apply_coupling_rules`
- AD-30: CIF stores codes only, display resolved at output time
- AD-57: acid-base two-axis model (metabolic HCO3 / respiratory pCO2). The new `anion_gap_status` is a 3rd orthogonal axis driving only Cl (not pH/HCO3/pCO2)
- BNP-pattern surgical: formula-only changes in `derive_lab_values`, state variables unchanged, byte-diff invariant on master vs branch (Observation.ndjson only differs; all other NDJSON/CSV/manifest IDENTICAL)
- Comments: English-only in code (per CLAUDE.md)
- All edits preserve `sort_keys=False` and existing YAML formatting
- Authoritative codes (LOINC 2075-0 Cl / 17861-6 Ca, JLAC10 3H020 Cl / 3H030 Ca) already registered in `codes/data/{loinc,jlac10}.yaml` and `locale/{us,jp}/code_mapping_lab.yaml`; reference ranges already in `locale/{us,jp}/reference_range_lab.yaml`. **Do NOT modify these files.**

---

## File Structure

**Modify:**
- `clinosim/types/clinical.py` — add `anion_gap_status: float = 0.0` to `PhysiologicalState`
- `clinosim/modules/physiology/engine.py` — add Cl/Ca block to `derive_lab_values` after the pH/blood-gas block
- 20 disease YAMLs in `clinosim/modules/disease/reference_data/` — add `anion_gap_status` to `initial_state_impact` severity dicts
- 2 encounter YAMLs in `clinosim/modules/encounter/reference_data/` — same
- `clinosim/modules/output/reference_data/lab_panel_groups.yaml` — BMP `min_components` 5→7, update comment
- `tests/unit/test_physiology.py` — new test cases for Cl/Ca + AG axis non-mutation
- `tests/unit/test_diagnostic_report_panels.py` — BMP min-component threshold update
- `scratchpad/cbc_bmp_panel_audit.py` — add Cl/Ca to `LOINC_TO_COMPONENT` and `BMP_COMPONENTS`, set `canonical["BMP"]=8`, `plan["BMP"]=7`
- `docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md` — fix encounter list 3→2 (chemical_exposure has no `initial_state_impact`, scope-out)

**Create:**
- `scratchpad/bmp_cl_ca_byte_diff.py` — master vs branch byte-diff invariant gate
- `scratchpad/bmp_cl_ca_clinical_audit.py` — per-disease Cl/Ca/AG percentile audit
- `docs/reviews/2026-06-23-bmp-cl-ca-audit.md` — audit results doc with numerical evidence

**Do NOT modify:**
- `clinosim/codes/data/loinc.yaml`, `jlac10.yaml` (codes already registered)
- `clinosim/locale/{us,jp}/reference_range_lab.yaml` (ranges already registered)
- `clinosim/locale/{us,jp}/code_mapping_lab.yaml` (mappings already registered)
- `clinosim/modules/observation/reference_data/lab_panels.yaml` (BMP canonical 8 already declared)

---

## Task 1: Add `anion_gap_status` field to `PhysiologicalState`

**Files:**
- Modify: `clinosim/types/clinical.py` (lines 9-39, after `respiratory_fraction`)
- Test: `tests/unit/test_physiology.py` (add test for default + settable)

**Interfaces:**
- Produces: `PhysiologicalState.anion_gap_status: float = 0.0` (-1.0 to +1.0 conventional range, not enforced by type; consumed by Task 2's Cl formula)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_physiology.py`:

```python
def test_anion_gap_status_field_default_is_zero():
    from clinosim.types.clinical import PhysiologicalState
    state = PhysiologicalState()
    assert hasattr(state, "anion_gap_status"), \
        "PhysiologicalState should have anion_gap_status field"
    assert state.anion_gap_status == 0.0, \
        "default anion_gap_status should be 0.0 (normal AG)"


def test_anion_gap_status_field_is_settable():
    from clinosim.types.clinical import PhysiologicalState
    state = PhysiologicalState(anion_gap_status=1.0)
    assert state.anion_gap_status == 1.0
    state.anion_gap_status = -0.5
    assert state.anion_gap_status == -0.5
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_physiology.py::test_anion_gap_status_field_default_is_zero tests/unit/test_physiology.py::test_anion_gap_status_field_is_settable -v`

Expected: FAIL with `AttributeError: 'PhysiologicalState' object has no attribute 'anion_gap_status'`

- [ ] **Step 3: Add the field to `PhysiologicalState`**

Modify `clinosim/types/clinical.py` — insert after `respiratory_fraction` (line 29), before `glucose_status`:

```python
    # Anion gap axis. Distinct from ph_status (acid-base magnitude) and
    # respiratory_fraction (metabolic vs respiratory routing). Drives the Cl axis
    # only — does NOT mutate pH/HCO3/pCO2 or feed apply_coupling_rules.
    #  0.0  = normal AG (8-12 mEq/L), Cl follows HCO3 1:1 when HCO3 drops (default
    #         healthy and most non-acid-base diseases)
    # +1.0  = high-AG metabolic acidosis (DKA/sepsis/uremia/lactic). Unmeasured
    #         anion (ketone/lactate/SO4/PO4) absorbs the HCO3 deficit, so Cl
    #         stays near normal even with low HCO3.
    # -1.0  = non-AG hyperchloremic acidosis (diarrhea, RTA, saline-induced).
    #         Cl rises 1:1 with HCO3 deficit to maintain electroneutrality.
    anion_gap_status: float = 0.0  # -1.0 to +1.0
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_physiology.py::test_anion_gap_status_field_default_is_zero tests/unit/test_physiology.py::test_anion_gap_status_field_is_settable -v`

Expected: PASS

- [ ] **Step 5: Run full unit + integration suite to confirm no regression**

Run: `pytest -m "unit or integration" -q`

Expected: ALL PASS (no field reads it yet, so addition is pure-additive)

- [ ] **Step 6: Commit**

```bash
git add clinosim/types/clinical.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
feat(types): add anion_gap_status axis to PhysiologicalState

Phase 1 of BMP Cl/Ca physiology. Axis is orthogonal to AD-57 acid-base
two-axis (metabolic/respiratory) and routes only the Cl formula. Default
0.0 (normal AG) means existing scenarios are unaffected until disease
YAMLs set the axis in initial_state_impact (next task).

No code consumes this yet — the Cl formula in derive_lab_values arrives
in Task 2.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 2: Add Cl and Ca to `derive_lab_values` + unit tests

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` — `derive_lab_values` (insert after the pH/blood-gas block ending at the `labs["pO2"] = ...` line, before the `# --- Glucose ...` block)
- Test: `tests/unit/test_physiology.py` (add 9 test cases)

**Interfaces:**
- Consumes: `PhysiologicalState.anion_gap_status` (from Task 1), existing state fields (inflammation_level, renal_function, hepatic_function, sodium_status, volume_status), and already-computed `labs["HCO3"]`
- Produces: `labs["Cl"]`, `labs["Ca"]` (consumed by BMP panel emission via inpatient.py/outpatient.py at the lab-result-stage downstream)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_physiology.py` (mirror existing fixture style — most tests in this file build a `PhysiologicalState` directly):

```python
def _healthy_state():
    from clinosim.types.clinical import PhysiologicalState
    return PhysiologicalState()


def _dka_state():
    """DKA: severe metabolic acidosis with high AG (ketone bodies)."""
    return _healthy_state().__class__(
        ph_status=-0.5, respiratory_fraction=0.0,
        anion_gap_status=1.0, glucose_status=0.6,
        volume_status=-0.4, renal_function=0.85,
    )


def _sepsis_state():
    """Sepsis: high inflammation + lactic acidosis (high-AG mixed)."""
    return _healthy_state().__class__(
        inflammation_level=0.85, ph_status=-0.30,
        respiratory_fraction=0.0, anion_gap_status=0.7,
        perfusion_status=0.5,
    )


def _diarrhea_state():
    """Non-AG hyperchloremic acidosis from GI HCO3 loss."""
    return _healthy_state().__class__(
        inflammation_level=0.08, ph_status=-0.25,
        respiratory_fraction=0.0, anion_gap_status=-0.5,
        volume_status=-0.22,
    )


def _ckd_state():
    """CKD: low renal function with uremic mild AG."""
    return _healthy_state().__class__(
        renal_function=0.3, anion_gap_status=0.4,
        ph_status=-0.1, respiratory_fraction=0.0,
    )


def _dehydration_state():
    """Mild dehydration (hyper-Na, no acid-base disturbance)."""
    return _healthy_state().__class__(sodium_status=0.3, volume_status=-0.2)


def test_cl_normal_healthy_state():
    from clinosim.modules.physiology.engine import derive_lab_values
    labs = derive_lab_values(_healthy_state(), sex="M", age=45)
    assert 100 <= labs["Cl"] <= 106, f"healthy Cl out of range: {labs['Cl']}"


def test_cl_high_ag_dka_keeps_normal():
    """High AG: unmeasured anion absorbs HCO3 deficit, Cl stays near normal."""
    from clinosim.modules.physiology.engine import derive_lab_values
    labs = derive_lab_values(_dka_state(), sex="M", age=45)
    assert labs["Cl"] <= 108, f"DKA should keep Cl near normal (got {labs['Cl']})"
    # AG = Na - Cl - HCO3 should be > 20
    ag = labs["Na"] - labs["Cl"] - labs["HCO3"]
    assert ag >= 20, f"DKA AG should be >= 20 (got {ag})"


def test_cl_non_ag_diarrhea_hyperchloremic():
    """Non-AG: Cl absorbs the HCO3 deficit 1:1, hyperchloremic."""
    from clinosim.modules.physiology.engine import derive_lab_values
    labs = derive_lab_values(_diarrhea_state(), sex="M", age=45)
    assert labs["Cl"] >= 108, \
        f"diarrhea non-AG should give Cl >= 108 (got {labs['Cl']})"
    # AG = Na - Cl - HCO3 should be in normal range (8-14)
    ag = labs["Na"] - labs["Cl"] - labs["HCO3"]
    assert 5 <= ag <= 14, f"diarrhea AG should be normal (got {ag})"


def test_ca_normal_healthy_state():
    from clinosim.modules.physiology.engine import derive_lab_values
    labs = derive_lab_values(_healthy_state(), sex="M", age=45)
    assert 9.0 <= labs["Ca"] <= 10.0, f"healthy Ca out of range: {labs['Ca']}"


def test_ca_sepsis_low_calcium():
    from clinosim.modules.physiology.engine import derive_lab_values
    labs = derive_lab_values(_sepsis_state(), sex="M", age=45)
    assert labs["Ca"] < 9.0, f"sepsis should give Ca < 9.0 (got {labs['Ca']})"


def test_ca_ckd_low_calcium():
    from clinosim.modules.physiology.engine import derive_lab_values
    labs = derive_lab_values(_ckd_state(), sex="M", age=45)
    assert labs["Ca"] < 9.2, f"CKD should give Ca < 9.2 (got {labs['Ca']})"


def test_ca_dehydration_normal_upper_range():
    from clinosim.modules.physiology.engine import derive_lab_values
    labs = derive_lab_values(_dehydration_state(), sex="M", age=45)
    assert 9.3 <= labs["Ca"] <= 10.0, \
        f"dehydration Ca should land in upper-normal (got {labs['Ca']})"


def test_anion_gap_status_does_not_mutate_other_state():
    """AG axis must NOT cascade through apply_coupling_rules. Compare
    derive output for AG=0 vs AG=1 with all other state held equal —
    only Cl should change; HCO3, pCO2, pH, K, Na, Cr, BUN, Ca all equal."""
    from clinosim.modules.physiology.engine import derive_lab_values
    base = _healthy_state()
    high_ag = _healthy_state().__class__(anion_gap_status=1.0)
    labs_base = derive_lab_values(base, sex="M", age=45)
    labs_ag = derive_lab_values(high_ag, sex="M", age=45)
    for key in ("HCO3", "pCO2", "pH", "K", "Na", "Creatinine", "BUN", "Ca",
                "WBC", "CRP", "BNP", "Lactate", "Glucose", "HbA1c"):
        assert abs(labs_base[key] - labs_ag[key]) < 1e-9, \
            f"AG axis should not affect {key} (base={labs_base[key]}, ag={labs_ag[key]})"
    # Only Cl is allowed to change — and in healthy state HCO3=24 so the
    # AG term collapses to 0 anyway, so Cl is also equal here.
    assert labs_base["Cl"] == labs_ag["Cl"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_physiology.py -k "_cl_ or _ca_ or anion_gap" -v`

Expected: FAIL with `KeyError: 'Cl'` (or `'Ca'`)

- [ ] **Step 3: Add Cl/Ca block to `derive_lab_values`**

Modify `clinosim/modules/physiology/engine.py` — find the `# --- pH / Blood gas ...` block ending with `labs["pO2"] = clamp(95.0 - infl * 45.0, 45.0, 105.0)` and insert immediately after:

```python
    # --- Electrolytes: Cl and Ca complete BMP canonical 8 ---
    # Cl reflects (a) Na linkage (electroneutrality) and (b) HCO3 reciprocity:
    # in non-AG metabolic acidosis (diarrhea, RTA) Cl absorbs the HCO3 deficit
    # 1:1 (hyperchloremic), while in high-AG acidosis (DKA, sepsis, uremia) the
    # unmeasured anion (ketone/lactate/SO4/PO4) absorbs it and Cl stays near
    # normal. The anion_gap_status axis routes between the two regimes. The
    # axis does NOT mutate ph/HCO3/pCO2 or feed back into any state variable.
    base_cl = 103.0 + state.sodium_status * 9.0
    hco3_deficit = max(0.0, 24.0 - labs["HCO3"])
    non_ag_fraction = clamp(1.0 - state.anion_gap_status, 0.0, 1.5)
    labs["Cl"] = clamp(base_cl + hco3_deficit * non_ag_fraction, 80.0, 125.0)
    # Total Ca — the lab-standard report (JCCLS 3H030 / LOINC 17861-6).
    # Corrected Ca and ionized Ca (iCa) are physician-side computations from a
    # second sample and out of scope here (Phase 2). Multi-axis linear coupling:
    # sepsis (inflammation), CKD (renal), liver failure (hepatic) drop Ca;
    # mild dehydration (high Na) lifts it slightly.
    ca = (
        9.5
        - state.inflammation_level * 0.8
        - (1.0 - state.renal_function) * 0.7
        - (1.0 - state.hepatic_function) * 0.4
        + state.sodium_status * 0.3
    )
    labs["Ca"] = clamp(ca, 5.5, 13.0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/unit/test_physiology.py -k "_cl_ or _ca_ or anion_gap" -v`

Expected: PASS (all 10 new tests)

- [ ] **Step 5: Run full unit + integration suite to confirm no regression**

Run: `pytest -m "unit or integration" -q`

Expected: ALL PASS. (The existing per-state fixtures in test_physiology.py call `derive_lab_values` and would have crashed if the formula raised — Cl/Ca silently appearing as new dict keys is additive.)

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
feat(physiology): add Cl and Ca to derive_lab_values

Completes BMP canonical 8 emission. Cl uses AG-aware coupling — non-AG
acidosis (diarrhea) gives hyperchloremic Cl, high-AG (DKA/sepsis) keeps
Cl near normal. Ca is the total (lab-standard) value; corrected Ca and
iCa are Phase 2. Formulas are pure (no RNG, no state mutation), so AD-16
is preserved and existing byte-diff stability holds for everything except
the new Cl/Ca Observations.

Disease/encounter YAML files setting anion_gap_status follow in Task 3-4.
Until they're updated, anion_gap_status defaults to 0.0 and Cl behaves
as a normal-AG patient with HCO3 reciprocity (which is the right default
for the vast majority of diseases that don't disturb AG).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 3: Set `anion_gap_status` on 20 disease YAMLs

**Files:**
- Modify the 20 disease YAMLs listed below (under `clinosim/modules/disease/reference_data/`)

**Strategy:**
All target disease YAMLs use a severity-keyed `initial_state_impact` dict (e.g. `mild:`, `moderate:`, `severe:`). Add `anion_gap_status: V` to each severity entry. For diseases with `mild: {}` (`acute_appendicitis`, `acute_cholecystitis`), set only on the non-empty severities. For `pulmonary_embolism`, `ileus`, `acute_pancreatitis` (which use `mild:` then `moderate:` block separators), populate the existing severities only. **Do not invent new severity keys.**

**AG value table (verbatim from spec §6.1):**

| File | mild | moderate | severe / shock |
|------|------|----------|----------------|
| `diabetic_ketoacidosis.yaml` | 0.7 | 1.0 | 1.0 |
| `sepsis.yaml` | 0.3 | 0.6 | 0.8 (severe) / 1.0 (septic_shock if present) |
| `acute_kidney_injury.yaml` | 0.2 | 0.4 | 0.6 |
| `acute_mi.yaml` | 0.0 | 0.1 | 0.3 (severe) / 0.6 (cardiogenic_shock if present) |
| `acute_pancreatitis.yaml` | 0.1 | 0.3 | 0.5 |
| `industrial_burn_severe.yaml` | (skip if absent) | 0.4 | 0.5 |
| `electrical_injury.yaml` | (skip) | 0.3 | 0.4 |
| `crush_injury_hand.yaml` | (skip) | 0.3 | 0.4 |
| `traffic_accident_severe.yaml` | (skip) | 0.3 | 0.4 |
| `fall_from_height.yaml` | (skip) | 0.2 | 0.3 |
| `aspiration_pneumonia.yaml` | 0.0 | 0.2 | 0.5 |
| `bacterial_pneumonia.yaml` | 0.0 | 0.2 | 0.4 |
| `gi_bleeding.yaml` | 0.0 | 0.1 | 0.3 |
| `liver_cirrhosis_decompensated.yaml` | 0.2 | 0.3 | 0.4 |
| `hemorrhagic_stroke.yaml` | (skip) | 0.2 | 0.3 |
| `cerebral_infarction.yaml` | (skip) | 0.1 | 0.2 |
| `pulmonary_embolism.yaml` | 0.0 | 0.2 | 0.3 |
| `ileus.yaml` | 0.0 | 0.2 | 0.3 |
| `acute_appendicitis.yaml` | (mild={}: skip) | 0.1 | 0.2 |
| `acute_cholecystitis.yaml` | (mild={}: skip) | 0.2 | 0.3 |

For severities a disease YAML doesn't define (e.g., DKA only has `moderate` and `severe`), simply skip — don't fabricate.

**Interfaces:**
- Consumes: Task 1's `PhysiologicalState.anion_gap_status` field, Task 2's Cl formula
- Produces: realistic AG-driven Cl values in each disease cohort, validated by Task 8's clinical audit

- [ ] **Step 1: Set `anion_gap_status` on DKA**

Open `clinosim/modules/disease/reference_data/diabetic_ketoacidosis.yaml`. For each severity key under `initial_state_impact`, add an `anion_gap_status` line. Example for `moderate`:

```yaml
  moderate:
    ph_status: -0.35
    volume_status: -0.40
    glucose_status: 0.60
    renal_function: -0.15
    perfusion_status: -0.10
    anion_gap_status: 1.0   # NEW — typical DKA AG 20-30
```

Use 0.7 for `mild` and 1.0 for `severe` (mirror the line above).

- [ ] **Step 2: Repeat for the remaining 19 disease YAMLs**

For each row in the value table above:
1. Open the file
2. For every severity key present (`mild`, `moderate`, `severe`, and any extra `septic_shock` / `cardiogenic_shock` / etc. — apply the severest column to those), add an `anion_gap_status` line with a short comment giving the AG band.
3. If the severity dict is empty (`mild: {}`), skip that severity.

Suggested comment template: `# AG axis: <typical AG band> (lactate / ketone / uremia / etc.)`.

- [ ] **Step 3: Run unit + integration suite**

Run: `pytest -m "unit or integration" -q`

Expected: ALL PASS. YAML edits are pure-additive (new key in a Pydantic-validated dict, but the loader is `dict`-typed and tolerates new keys; verify by spot-running one disease integration test below).

- [ ] **Step 4: Spot-check one disease scenario test**

Run: `pytest tests/unit/test_physiology.py -v 2>&1 | tail -20`

If there is an existing scenario-level integration test (e.g. `tests/integration/test_disease_*.py`), run it with `-v`. The new `anion_gap_status` line should be loaded silently.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/disease/reference_data/*.yaml
git commit -m "$(cat <<'EOF'
feat(disease): set anion_gap_status on 20 AG-disturbing diseases

DKA / sepsis / AKI / MI cardiogenic shock / pancreatitis / pneumonia /
GI bleeding / hepatic decompensation / stroke / PE / ileus / appendicitis
/ cholecystitis / multi-trauma / burns / electrical / crush — all the
diseases that, in real-world BMPs, show a measurable anion-gap shift.
Severity-graded where the YAML already has severity tiers.

Diseases that do NOT disturb AG in real-world BMPs (COPD pure
respiratory, asthma, UTI uncomplicated, AF, fractures, neuro encounters,
DVT, cellulitis, HF compensated) stay at default 0.0 — that's the
clinically correct null.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 4: Set `anion_gap_status` on 2 encounter YAMLs

**Files:**
- Modify: `clinosim/modules/encounter/reference_data/viral_gastroenteritis.yaml`
- Modify: `clinosim/modules/encounter/reference_data/food_poisoning.yaml`

**Scope note:** `chemical_exposure.yaml` was in the spec's §6.2 but has no `initial_state_impact` block. Adding one for the average chemical-exposure cohort would be a structural change well outside this PR's scope; AG behavior of chemical exposure is also highly substance-dependent (methanol/ethylene glycol high-AG vs alkali low-AG vs most others neutral). Leaving it at default 0.0 is the clinically correct null. Spec will be updated in Task 9.

**AG values:**
- `viral_gastroenteritis`: mild=-0.3, moderate=-0.5, severe=-0.6 (diarrhea-driven non-AG hyperchloremic)
- `food_poisoning`: mild=-0.2, moderate=-0.4, severe=-0.5 (mixed diarrhea/vomiting, slightly less negative on average)

**Interfaces:**
- Consumes: same as Task 3
- Produces: hyperchloremic Cl values in GE/food-poisoning cohorts, validated by Task 8

- [ ] **Step 1: Edit `viral_gastroenteritis.yaml`**

Open `clinosim/modules/encounter/reference_data/viral_gastroenteritis.yaml`. The current `initial_state_impact` is an inline-dict-style:

```yaml
initial_state_impact:
  mild:     {inflammation_level: 0.05, volume_status: -0.10}
  moderate: {inflammation_level: 0.08, volume_status: -0.22}
  severe:   {inflammation_level: 0.10, volume_status: -0.38, ph_status: -0.05}
```

Change to:

```yaml
initial_state_impact:
  # AG axis: HCO3 stool loss → non-AG hyperchloremic acidosis (textbook
  # presentation). Severity scales with stool volume.
  mild:     {inflammation_level: 0.05, volume_status: -0.10, anion_gap_status: -0.3}
  moderate: {inflammation_level: 0.08, volume_status: -0.22, anion_gap_status: -0.5}
  severe:   {inflammation_level: 0.10, volume_status: -0.38, ph_status: -0.05, anion_gap_status: -0.6}
```

- [ ] **Step 2: Edit `food_poisoning.yaml`**

Open `clinosim/modules/encounter/reference_data/food_poisoning.yaml` and apply the same shape with values -0.2 / -0.4 / -0.5.

- [ ] **Step 3: Run unit + integration suite**

Run: `pytest -m "unit or integration" -q`

Expected: ALL PASS.

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/encounter/reference_data/viral_gastroenteritis.yaml \
        clinosim/modules/encounter/reference_data/food_poisoning.yaml
git commit -m "$(cat <<'EOF'
feat(encounter): set anion_gap_status on GE / food poisoning

Diarrhea-driven HCO3 stool loss → non-AG hyperchloremic acidosis is the
textbook presentation. Severity scales with stool volume. chemical_exposure
deliberately left at default 0.0 — substance-dependent AG behavior, no
initial_state_impact block to extend (out of scope for Phase 1).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 5: Raise BMP `min_components` 5 → 7 in `lab_panel_groups.yaml`

**Files:**
- Modify: `clinosim/modules/output/reference_data/lab_panel_groups.yaml` (BMP block, lines 28-38)
- Modify: `tests/unit/test_diagnostic_report_panels.py` (BMP threshold check)

**Interfaces:**
- Consumes: Task 2's Cl/Ca emission
- Produces: BMP DR `result[]` of length ≥ 7 per panel-order day, validated by integration test

- [ ] **Step 1: Find the BMP min_components test**

Run: `grep -n "BMP\|51990-0\|min_components" tests/unit/test_diagnostic_report_panels.py | head -10`

If a test asserts the BMP threshold value (5) or the minimum-component count, it lives there. Read the test to understand its shape.

- [ ] **Step 2: Update the test to expect 7**

Modify whichever test in `tests/unit/test_diagnostic_report_panels.py` checks BMP min_components or result-length so it asserts the new value 7 (and 8 emit-able components). If the test checks that BMP groups when 5+ components are present, change to 7+. Example pattern (adapt to actual test):

```python
# Before
assert len(bmp_dr.result) >= 5
# After
assert len(bmp_dr.result) >= 7
```

If no such test exists, add one in the existing style:

```python
def test_bmp_diagnostic_report_emits_with_seven_or_more_components():
    """After Cl/Ca were added to derive_lab_values, BMP DR groups when
    canonical N - 1 = 7 components are observed in the same encounter/day."""
    # ... build encounter with BMP order, derive labs (must include Cl/Ca),
    #     run _build_diagnostic_reports, find BMP DR, assert len(result) >= 7
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `pytest tests/unit/test_diagnostic_report_panels.py -v`

Expected: FAIL on the BMP test (threshold not yet raised).

- [ ] **Step 4: Update `lab_panel_groups.yaml` BMP block**

Modify `clinosim/modules/output/reference_data/lab_panel_groups.yaml` — replace the BMP block (lines 28-38) with:

```yaml
  BMP:
    loinc: "51990-0"
    display: "Basic metabolic 2000 panel - Serum or Plasma"
    components: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
    # canonical N − 1 rule (PR #75): BMP has 8 listed components and as of
    # PR #N (this PR, 2026-06-23), derive_lab_values produces all 8 (Cl/Ca
    # added). The 5th-percentile bucket of "panel-order-placed" days now
    # holds ≥ 7 components, validated by scratchpad/cbc_bmp_panel_audit.py
    # on the post-PR head.
    min_components: 7
```

- [ ] **Step 5: Run the integration test to verify pass**

Run: `pytest tests/unit/test_diagnostic_report_panels.py -v`

Expected: PASS.

- [ ] **Step 6: Run full unit + integration suite**

Run: `pytest -m "unit or integration" -q`

Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/output/reference_data/lab_panel_groups.yaml \
        tests/unit/test_diagnostic_report_panels.py
git commit -m "$(cat <<'EOF'
feat(output): raise BMP min_components 5→7 (canonical N − 1)

Cl/Ca now emit from derive_lab_values, so BMP's emit-able N rises from
6 to 8 and the canonical-N-1 floor rises from 5 to 7. Audit by
scratchpad/cbc_bmp_panel_audit.py validates the 5th-percentile bucket
of panel-order days is ≥ 7.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 6: Update `cbc_bmp_panel_audit.py` for Cl/Ca + run audit

**Files:**
- Modify: `scratchpad/cbc_bmp_panel_audit.py`

**Interfaces:**
- Consumes: Task 5's raised BMP threshold (the audit's `plan["BMP"] = 7`)
- Produces: numerical verdict that the 5th-percentile floor for BMP-order-placed days is ≥ 7 (gate for PR)

- [ ] **Step 1: Edit `LOINC_TO_COMPONENT`, `BMP_COMPONENTS`, `canonical`, `plan` in the audit script**

Modify `scratchpad/cbc_bmp_panel_audit.py`:

- In `LOINC_TO_COMPONENT` (lines ~34-39), add:

```python
    "2075-0": "Cl",
    "17861-6": "Ca",
```

- Remove the obsolete comment line `# Cl (2075-0) and Ca (17861-6) don't emit until derive_lab_values adds them.`

- In `BMP_COMPONENTS` (line ~42), change to:

```python
BMP_COMPONENTS = {"Na", "K", "Cl", "HCO3", "BUN", "Creatinine", "Glucose", "Ca"}  # 8 emit-able
```

- In `report()` (line ~139-140), change:

```python
    plan = {"CBC": 3, "BMP": 7}
    canonical = {"CBC": 4, "BMP": 8}
```

- [ ] **Step 2: Run the audit script**

Run: `python scratchpad/cbc_bmp_panel_audit.py 2>&1 | tee /tmp/bmp-audit.txt | tail -60`

Expected: `=== SUMMARY ===  US failures: 0` and the BMP `5th-percentile floor (with panel order) = 7` (or higher). If `failures: 1` and BMP floor < 7, the formula coverage isn't complete enough for the threshold rise — investigate which component is missing (check `derive_lab_values` reaches the same path for all BMP-ordering venues — inpatient, ED, outpatient).

- [ ] **Step 3: Commit the audit script update**

```bash
git add scratchpad/cbc_bmp_panel_audit.py
git commit -m "$(cat <<'EOF'
chore(audit): extend cbc_bmp_panel_audit to Cl/Ca

Cl (2075-0) and Ca (17861-6) now emit. BMP canonical = 8, plan = 7
(canonical N − 1 from PR #75 rule). Validates the lab_panel_groups
threshold raised in Task 5.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 7: Create `bmp_cl_ca_byte_diff.py` + run byte-diff invariant gate

**Files:**
- Create: `scratchpad/bmp_cl_ca_byte_diff.py`

**Interfaces:**
- Consumes: master branch state (pre-this-PR baseline) and current feature branch
- Produces: SHA-256 comparison of all NDJSON / CSV / manifest. Gate: EVERY non-Observation file must be byte-identical between master and branch at the same seed; Observation.ndjson may differ only by Cl/Ca additions and AG-axis-driven Cl shifts.

- [ ] **Step 1: Write the byte-diff script**

Create `scratchpad/bmp_cl_ca_byte_diff.py`:

```python
"""Byte-diff invariant gate for the BMP Cl/Ca physiology PR.

Generates US p=2000 + JP p=2000 bundles at seed=42 from (a) master HEAD
and (b) the current feature branch, then hashlib-compares every output
file. Gate:
  - Every non-Observation NDJSON, every CSV, every manifest: byte-IDENTICAL
  - Observation.ndjson: differs only by (i) new Cl/Ca lines and (ii) any
    shifted Cl value on diseases where anion_gap_status was set
  - Patient count: exact match (no cohort drift)

This guards against the master-RNG cascade documented in
docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md
(state mutation → clinical_course RNG → cohort shift).
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int = 42) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate", "--country", country, "-p", str(n), "-s", str(seed),
        "-o", str(out_dir), "--format", "fhir", "csv",
    ], check=True, cwd=cwd)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def all_relative_files(root: Path) -> list[Path]:
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def observation_count_by_loinc(ndjson: Path) -> dict[str, int]:
    """Count Observation lines by LOINC code (for delta inspection)."""
    counts: dict[str, int] = {}
    with open(ndjson) as f:
        for line in f:
            o = json.loads(line)
            if not o.get("id", "").startswith("lab-"):
                continue
            loinc = (o.get("code", {}).get("coding") or [{}])[0].get("code", "")
            counts[loinc] = counts.get(loinc, 0) + 1
    return counts


def compare(master: Path, branch: Path, label: str) -> int:
    failures = 0
    master_files = set(all_relative_files(master))
    branch_files = set(all_relative_files(branch))
    if master_files != branch_files:
        only_master = master_files - branch_files
        only_branch = branch_files - master_files
        print(f"  [{label}] file-set mismatch:")
        if only_master:
            print(f"    only in master: {sorted(only_master)[:5]}")
        if only_branch:
            print(f"    only in branch: {sorted(only_branch)[:5]}")
        failures += 1

    for rel in sorted(master_files & branch_files):
        m_hash = sha256(master / rel)
        b_hash = sha256(branch / rel)
        if m_hash == b_hash:
            continue
        # Differences allowed only on Observation.ndjson (and only by new Cl/Ca
        # plus AG-shifted Cl on AG-axis diseases)
        if rel.name == "Observation.ndjson":
            m_counts = observation_count_by_loinc(master / rel)
            b_counts = observation_count_by_loinc(branch / rel)
            # New analytes — should appear only on the branch side
            new_us = {"2075-0", "17861-6"}
            new_jp = {"3H020", "3H030"}
            for code in (new_us | new_jp):
                m_n = m_counts.get(code, 0)
                b_n = b_counts.get(code, 0)
                if m_n == 0 and b_n > 0:
                    print(f"  [{label}] {rel}: new Cl/Ca emission "
                          f"LOINC/JLAC {code} = {b_n}")
            # Existing analyte counts must match (Cl-shift is value, not count)
            existing_drift = {
                k: (m_counts.get(k, 0), b_counts.get(k, 0))
                for k in (set(m_counts) | set(b_counts))
                if k not in new_us and k not in new_jp
                and m_counts.get(k, 0) != b_counts.get(k, 0)
            }
            if existing_drift:
                print(f"  [{label}] {rel}: ❌ existing analyte count drift:")
                for k, (mc, bc) in sorted(existing_drift.items())[:10]:
                    print(f"      LOINC {k}: master={mc} branch={bc}")
                failures += 1
            else:
                print(f"  [{label}] {rel}: ✓ only new Cl/Ca added; existing counts identical")
        else:
            print(f"  [{label}] {rel}: ❌ byte mismatch (NOT Observation.ndjson)")
            failures += 1
    return failures


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="bmp-cl-ca-byte-diff-"))
    master_dir = work / "master"
    branch_dir = work / "branch"

    # Snapshot the current branch's worktree, then build a master worktree.
    master_repo = work / "master-repo"
    subprocess.run(["git", "worktree", "add", str(master_repo), "master"],
                   check=True, cwd=REPO)
    try:
        for country, n in [("US", 2000), ("JP", 2000)]:
            print(f"\n=== Generating master {country} p={n} (seed=42) ===")
            run_simulator(master_repo, master_dir / country, country, n)
            print(f"=== Generating branch {country} p={n} (seed=42) ===")
            run_simulator(REPO, branch_dir / country, country, n)

        total_failures = 0
        for country in ("US", "JP"):
            print(f"\n### {country} ###")
            total_failures += compare(master_dir / country, branch_dir / country, country)

        print(f"\n=== SUMMARY ===  failures: {total_failures}")
        print(f"Workspaces kept at {work} for inspection.")
        if total_failures:
            sys.exit(1)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(master_repo)],
                       check=False, cwd=REPO)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the byte-diff script**

Run: `python scratchpad/bmp_cl_ca_byte_diff.py 2>&1 | tee /tmp/bmp-byte-diff.txt | tail -40`

Expected:
- For each country: `Observation.ndjson: ✓ only new Cl/Ca added; existing counts identical`
- For all other files: silence (byte-identical, no print)
- Final line: `failures: 0`

If `failures: > 0`:
- If a non-Observation file differs → check whether `anion_gap_status` is feeding into `apply_coupling_rules` somewhere (it must not — spec §8). Re-verify Task 1's field comment and Task 2's no-coupling intent.
- If existing analyte counts drift in Observation → check whether physiology state mutation slipped in. Re-verify the `derive_lab_values` block from Task 2 is pure-additive (only `labs["Cl"]` / `labs["Ca"]` assignments, no other writes).

- [ ] **Step 3: Commit the byte-diff script**

```bash
git add scratchpad/bmp_cl_ca_byte_diff.py
git commit -m "$(cat <<'EOF'
chore(audit): add byte-diff invariant gate for BMP Cl/Ca PR

Compares master vs branch at seed=42, US/JP p=2000. Gate: every
non-Observation NDJSON / CSV / manifest is byte-identical; Observation
differs only by new Cl/Ca emission. Verified locally before merge.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 8: Create `bmp_cl_ca_clinical_audit.py` + clinical coherence audit + audit doc

**Files:**
- Create: `scratchpad/bmp_cl_ca_clinical_audit.py`
- Create: `docs/reviews/2026-06-23-bmp-cl-ca-audit.md`

**Interfaces:**
- Consumes: branch state with Task 2-5 applied
- Produces: per-disease median + percentile table for Cl/Ca/AG, written to a review doc as PR evidence

- [ ] **Step 1: Write the clinical audit script**

Create `scratchpad/bmp_cl_ca_clinical_audit.py`:

```python
"""Clinical coherence audit for BMP Cl/Ca physiology PR.

Generates US p=4000 + JP p=2000 at seed=42 and walks Observation.ndjson +
Condition.ndjson + Encounter.ndjson, grouping Cl/Ca/AG values per
ground-truth disease cohort. Output: median + p10/p90 per disease for
Cl, Ca, and AG = Na − Cl − HCO3.

Expected ranges (from spec §9.4):
  DKA:      Cl 100-105, Ca 9.0-9.4, AG 20-30
  Sepsis:   Cl 100-104, Ca 8.5-9.0, AG 15-20
  Diarrhea: Cl 108-115, Ca 9.0-9.5, AG 6-10
  CKD/AKI:  Cl 100-105, Ca 8.8-9.2, AG 12-18
  Healthy:  Cl 99-106,  Ca 9.0-10.0, AG 8-14
"""
import collections
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# LOINC + JLAC10 codes for the three analytes we care about per locale.
US_CODES = {"Na": "2951-2", "K": "2823-3", "Cl": "2075-0",
            "HCO3": "1963-8", "Ca": "17861-6"}
JP_CODES = {"Na": "3H010", "K": "3H015", "Cl": "3H020",
            "HCO3": "3F015"  # NOTE: verify HCO3 JLAC10 if mismatched
            , "Ca": "3H030"}

# ICD-10 → disease label for the cohorts we report. Use prefix matching.
COHORTS = {
    "DKA":            ["E10.1", "E11.1", "E13.1"],   # CM granular
    "Sepsis":         ["A41"],
    "AKI":            ["N17"],
    "CKD":            ["N18"],
    "GE/diarrhea":    ["A09", "K52.9"],
    "Pneumonia":      ["J15", "J18"],
    "GI_bleed":       ["K92.2", "K92.0", "K92.1"],
    "MI":             ["I21"],
    "Healthy":        ["Z00"],
}


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int = 42) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate", "--country", country, "-p", str(n), "-s", str(seed),
        "-o", str(out_dir), "--format", "fhir",
    ], check=True, cwd=cwd)


def patient_diagnoses(fhir_dir: Path) -> dict[str, set[str]]:
    """{patient_id: {icd_code, ...}} from Condition.ndjson."""
    out: dict[str, set[str]] = collections.defaultdict(set)
    with open(fhir_dir / "Condition.ndjson") as f:
        for line in f:
            c = json.loads(line)
            pid = (c.get("subject") or {}).get("reference", "").split("/")[-1]
            for coding in (c.get("code", {}).get("coding") or []):
                if coding.get("code"):
                    out[pid].add(coding["code"])
    return out


def encounter_to_patient(fhir_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(fhir_dir / "Encounter.ndjson") as f:
        for line in f:
            e = json.loads(line)
            eid = e.get("id")
            pid = (e.get("subject") or {}).get("reference", "").split("/")[-1]
            if eid and pid:
                out[eid] = pid
    return out


def lab_values(fhir_dir: Path, codes: dict[str, str]) -> list[tuple[str, str, str, float]]:
    """[(patient_id, encounter_id, analyte_name, value_quantity), ...]"""
    code_to_analyte = {v: k for k, v in codes.items()}
    enc_pat = encounter_to_patient(fhir_dir)
    out: list[tuple[str, str, str, float]] = []
    with open(fhir_dir / "Observation.ndjson") as f:
        for line in f:
            o = json.loads(line)
            if not o.get("id", "").startswith("lab-"):
                continue
            loinc = ((o.get("code", {}).get("coding") or [{}])[0]).get("code", "")
            analyte = code_to_analyte.get(loinc)
            if not analyte:
                continue
            v = (o.get("valueQuantity") or {}).get("value")
            if v is None:
                continue
            enc = (o.get("encounter") or {}).get("reference", "").split("/")[-1]
            pid = enc_pat.get(enc, "")
            if pid:
                out.append((pid, enc, analyte, float(v)))
    return out


def report(fhir_dir: Path, codes: dict[str, str], label: str) -> None:
    diags = patient_diagnoses(fhir_dir)
    labs = lab_values(fhir_dir, codes)

    # Group by patient + cohort. For AG we need same-encounter Na/Cl/HCO3.
    enc_values: dict[str, dict[str, float]] = collections.defaultdict(dict)
    pat_enc: dict[str, str] = {}
    for pid, enc, analyte, v in labs:
        enc_values[enc][analyte] = v
        pat_enc[enc] = pid

    cohort_vals: dict[str, dict[str, list[float]]] = collections.defaultdict(
        lambda: {"Cl": [], "Ca": [], "AG": []}
    )
    for enc, vals in enc_values.items():
        pid = pat_enc.get(enc, "")
        if not pid:
            continue
        # Determine cohort by patient's ICD codes (prefix match)
        pat_codes = diags.get(pid, set())
        for cohort, prefixes in COHORTS.items():
            if any(any(c.startswith(p) for c in pat_codes) for p in prefixes):
                if "Cl" in vals:
                    cohort_vals[cohort]["Cl"].append(vals["Cl"])
                if "Ca" in vals:
                    cohort_vals[cohort]["Ca"].append(vals["Ca"])
                if all(k in vals for k in ("Na", "Cl", "HCO3")):
                    ag = vals["Na"] - vals["Cl"] - vals["HCO3"]
                    cohort_vals[cohort]["AG"].append(ag)

    def quantile(xs: list[float], p: float) -> float:
        if not xs:
            return 0.0
        xs_sorted = sorted(xs)
        k = max(0, min(len(xs_sorted) - 1, int(len(xs_sorted) * p)))
        return xs_sorted[k]

    print(f"\n##### {label} #####")
    print(f"{'cohort':<14} {'n':>5}   "
          f"{'Cl (p10/p50/p90)':<26}{'Ca (p10/p50/p90)':<26}"
          f"{'AG (p10/p50/p90)':<22}")
    for cohort in COHORTS:
        cl = cohort_vals[cohort]["Cl"]
        ca = cohort_vals[cohort]["Ca"]
        ag = cohort_vals[cohort]["AG"]
        n = len(cl)
        if n == 0:
            print(f"{cohort:<14} {n:>5}   (no patients)")
            continue
        print(
            f"{cohort:<14} {n:>5}   "
            f"{quantile(cl,0.10):>5.1f}/{statistics.median(cl):>5.1f}/{quantile(cl,0.90):>5.1f}  "
            f"     "
            f"{quantile(ca,0.10):>5.2f}/{statistics.median(ca):>5.2f}/{quantile(ca,0.90):>5.2f}  "
            f"     "
            f"{quantile(ag,0.10):>5.1f}/{statistics.median(ag):>5.1f}/{quantile(ag,0.90):>5.1f}"
            if ag else
            f"{cohort:<14} {n:>5}   "
            f"{quantile(cl,0.10):>5.1f}/{statistics.median(cl):>5.1f}/{quantile(cl,0.90):>5.1f}  "
            f"     "
            f"{quantile(ca,0.10):>5.2f}/{statistics.median(ca):>5.2f}/{quantile(ca,0.90):>5.2f}  "
            "     (no AG triple)"
        )


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="bmp-cl-ca-audit-"))
    print("Generating US p=4000 + JP p=2000 (seed=42)...")
    us = work / "us"; jp = work / "jp"
    run_simulator(REPO, us, "US", 4000)
    run_simulator(REPO, jp, "JP", 2000)
    report(us / "fhir_r4", US_CODES, "US")
    report(jp / "fhir_r4", JP_CODES, "JP")
    print(f"\nOutputs kept at {work} for inspection.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the audit**

Run: `python scratchpad/bmp_cl_ca_clinical_audit.py 2>&1 | tee /tmp/bmp-clinical-audit.txt | tail -60`

Expected ballpark (per spec §9.4):
- DKA: Cl median 100-105, AG median 20-30
- Sepsis: Cl median 100-104, AG median 15-20
- GE/diarrhea: Cl median 108-115, AG median 6-10
- CKD/AKI: Cl median 100-105, AG median 12-18
- Healthy (Z00): Cl median 99-106, AG median 8-14

Mismatch policy: if a cohort lands ±2 mEq/L off the band, **investigate the disease YAML's AG value** before touching the formula — most likely the AG axis is set too low/high. If the formula itself is at fault (e.g. Ca always lands < 8.5 in healthy), tune coefficients in `derive_lab_values` and re-run Task 2's unit tests, then this audit.

If the audit needs the JP HCO3 JLAC10 code corrected (see code-table TODO comment in script), verify the actual code from `clinosim/locale/jp/code_mapping_lab.yaml` and update `JP_CODES["HCO3"]`.

- [ ] **Step 3: Write the audit doc with results**

Create `docs/reviews/2026-06-23-bmp-cl-ca-audit.md` with the actual numbers from Step 2's run:

```markdown
# BMP Cl/Ca Physiology — Audit Results (PR #N)

**Date:** 2026-06-23
**Spec:** docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md
**Plan:** docs/superpowers/plans/2026-06-23-bmp-cl-ca-physiology-plan.md

## Methodology

- US p=4000 + JP p=2000, seed=42
- Walks Observation.ndjson + Condition.ndjson + Encounter.ndjson
- AG = Na - Cl - HCO3 (per-encounter triple)
- Compares against textbook ranges from Harrison's 21e Ch. 51, Tietz 4e

## Per-cohort percentiles (p10 / p50 / p90)

<paste the script's table output here, US then JP>

## Verdict

- DKA: <PASS/FAIL — note specifically>
- Sepsis: <...>
- GE/diarrhea: <...>
- CKD/AKI: <...>
- Healthy: <...>

## Byte-diff invariant

(from scratchpad/bmp_cl_ca_byte_diff.py)

- Non-Observation NDJSON: byte-identical ✓
- Existing analyte counts in Observation.ndjson: identical ✓
- New Cl/Ca emissions: US Cl=<N> Ca=<N>, JP Cl=<N> Ca=<N>
- Patient count: master <N> = branch <N> ✓

## Panel threshold

(from scratchpad/cbc_bmp_panel_audit.py)

- BMP 5th-percentile floor (with panel order placed): <N>
- canonical N − 1 = 7 ≥ chosen = 7 ✓
```

- [ ] **Step 4: Commit the audit script + doc**

```bash
git add scratchpad/bmp_cl_ca_clinical_audit.py docs/reviews/2026-06-23-bmp-cl-ca-audit.md
git commit -m "$(cat <<'EOF'
chore(audit): clinical coherence audit for BMP Cl/Ca PR

US p=4000 + JP p=2000 audit walks Observation.ndjson + Condition.ndjson
grouping Cl/Ca/AG per ground-truth disease cohort. Verdict by cohort
documented in docs/reviews/2026-06-23-bmp-cl-ca-audit.md against
textbook ranges (Harrison's 21e, Tietz 4e).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

---

## Task 9: Fix spec, run full test suite, push, open PR

**Files:**
- Modify: `docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md` (§6.2 encounter count 3→2, remove `chemical_exposure` row)

**Interfaces:**
- Consumes: all prior tasks
- Produces: PR on GitHub with audit doc linked, byte-diff invariant + clinical audit passing

- [ ] **Step 1: Fix spec §6.2 — encounter count 3→2**

Edit `docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md`:

- In §6 header line "20 disease + 3 encounter YAML files" → "20 disease + 2 encounter YAML files"
- In §6.2, remove the `chemical_exposure.yaml` row and replace the section header with "### 6.2 Encounter (2 files)" with a footnote:

```markdown
### 6.2 Encounter (2 files)

| File | Value | Rationale |
|------|-------|-----------|
| `viral_gastroenteritis.yaml` | mild=-0.3, moderate=-0.5, severe=-0.6 | Diarrhea-dominant — HCO3 stool loss → non-AG hyperchloremic acidosis (textbook) |
| `food_poisoning.yaml` | mild=-0.2, moderate=-0.4, severe=-0.5 | Mixed diarrhea/vomiting — slightly less negative on average |

> **Scope note:** `chemical_exposure.yaml` was in the original spec draft but has no `initial_state_impact` block to extend, and AG behavior is highly substance-dependent. Left at default 0.0; revisited if a chemical-specific encounter is added.
```

- [ ] **Step 2: Run the full test suite (unit + integration + e2e)**

Run: `pytest -x -q 2>&1 | tail -20`

Expected: ALL PASS. (e2e may take ~8 min.)

If a golden e2e test fails because of new Cl/Ca emission, regenerate goldens with the documented procedure (likely `pytest --snapshot-update` or equivalent — check `tests/e2e/` for the existing pattern). Commit golden updates with message `test(e2e): refresh goldens for BMP Cl/Ca emission`.

- [ ] **Step 3: Commit spec fix and any golden updates**

```bash
git add docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md
# add any e2e golden files if they were regenerated
git commit -m "$(cat <<'EOF'
docs(spec): trim encounter list 3→2 (chemical_exposure scope-out)

chemical_exposure has no initial_state_impact block — adding one is a
structural change outside Phase 1. AG behavior is also substance-
dependent (methanol high-AG vs alkali low-AG). Default 0.0 is the
clinically correct null until a substance-specific encounter exists.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin feat/bmp-cl-ca-physiology
gh pr create --title "feat: complete BMP canonical 8 (Cl/Ca + anion_gap_status axis, raise min_components 5→7)" --body "$(cat <<'EOF'
## Summary

PR #74 (panel registry + sub-rng) and PR #75 (canonical N − 1 rule)
follow-up — Phase 1 of BMP completion.

- Adds Cl and Ca to `derive_lab_values` so BMP canonical 8 is fully
  emit-able for the first time.
- New `anion_gap_status` axis on `PhysiologicalState` for AG-aware Cl
  coupling (orthogonal to AD-57 acid-base 2-axis; does NOT affect
  pH/HCO3/pCO2 or feed back into any state via apply_coupling_rules).
- 20 disease YAMLs + 2 encounter YAMLs set the AG axis where AG is
  recorded as varying in real-world BMPs (DKA / sepsis severity-graded /
  AKI / diarrhea / etc.). The rest stay at default 0.0 — matching how
  real BMPs read for non-AG-disturbing diseases (COPD pure respiratory,
  UTI uncomplicated, AF, fractures).
- BMP `min_components` 5 → 7 (canonical N − 1 = 8 − 1).
- Audit doc: `docs/reviews/2026-06-23-bmp-cl-ca-audit.md`

## Spec & plan

- `docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md`
- `docs/superpowers/plans/2026-06-23-bmp-cl-ca-physiology-plan.md`

## Verification

- Unit + integration: <N pass>
- e2e: <N pass>
- Byte-diff invariant (US/JP p=2000 seed=42, master vs branch):
  - Patient count: master = branch (no cohort drift)
  - All non-Observation NDJSON / CSV / manifest: byte-identical
  - Observation.ndjson: only new Cl/Ca additions; existing analyte counts identical
- Clinical coherence (US p=4000 + JP p=2000):
  - DKA Cl p50 = <N> / AG p50 = <N> (target Cl 100-105, AG 20-30)
  - Sepsis Cl p50 = <N> / AG p50 = <N> (target Cl 100-104, AG 15-20)
  - GE/diarrhea Cl p50 = <N> / AG p50 = <N> (target Cl 108-115, AG 6-10)
  - CKD Cl p50 = <N> / AG p50 = <N> (target Cl 100-105, AG 12-18)
  - Healthy Cl p50 = <N> / AG p50 = <N> (target Cl 99-106, AG 8-14)
- BMP panel floor: 5th-percentile (with panel order placed) = <N> ≥ 7 ✓

## Phase 2 (later PR)

- iCa (LOINC 1994-3) on ABG / separate lab
- Cl hypochloremic alkalosis axis (vomiting-dominant)
- Corrected Ca text annotation

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_012vZKGp32VGW8BVH9u1fTAs
EOF
)"
```

Paste actual audit numbers in place of `<N>` before pressing enter (read from `/tmp/bmp-clinical-audit.txt` and `/tmp/bmp-byte-diff.txt`).

- [ ] **Step 5: Confirm PR opened**

Run: `gh pr view --json url,number 2>&1`

Expected: PR URL and number reported. Share with user.

---

## Self-Review

**Spec coverage check** (skim each spec section, point to plan task):
- §1 Goal → Task 2 (Cl/Ca derive) + Task 5 (min_components raise)
- §2 リアリティ定義 → embedded in Task 3-4 (scoping diseases that record AG variation)
- §3 Phase 分解 → Phase 1 = this PR (all 9 tasks); Phase 2 explicitly out of scope
- §4 物理式 → Task 2 (code blocks match spec verbatim)
- §5 PhysiologicalState 変更 → Task 1
- §6 disease/encounter YAML 設定対象 → Task 3 (20 disease) + Task 4 (2 encounter, spec §6.2 corrected from 3 in Task 9)
- §7 配線変更 → Task 5 (lab_panel_groups) + Task 2 (placement in derive_lab_values after blood-gas block)
- §8 data flow / AD-16 → Task 2 implementation has no RNG, Task 1 axis has no coupling rule
- §9 test 戦略 → Task 2 (unit) + Task 5 (integration) + Task 7 (byte-diff) + Task 8 (clinical audit) + Task 6 (panel audit)
- §10 workflow gates → Task ordering follows §10's 1-11
- §11 後続 phase → out of scope, mentioned in PR body
- §12 Rollback → not a plan task; revert mechanism documented in spec
- §13 リスクと緩和 → Task 7 (byte-diff catches cascade), Task 8 (audit catches Ca/Cl drift), Task 2 (test_anion_gap_status_does_not_mutate_other_state catches coupling slip)

**No placeholders:** scanned — every step has either runnable code or a runnable bash command. The `<N>` placeholders in Task 9's PR body are intentional (filled with real numbers at the time of running).

**Type consistency:** `anion_gap_status: float` consistent in Task 1 (definition), Task 2 (consumer), Task 3-4 (YAML setter). `min_components: 7` consistent in Task 5 (yaml) + Task 6 (audit `plan["BMP"]=7`).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-23-bmp-cl-ca-physiology-plan.md`. Two execution options:

1. **Subagent-Driven** — fresh subagent per task with two-stage review, fast iteration on isolated changes
2. **Inline Execution (recommended for clinosim)** — execute tasks in this session using executing-plans, with checkpoints between tasks. Memory `feedback_clinosim_workflow` notes inline is preferred for "single module densely-coupled tasks" — this PR is single-theme (BMP Cl/Ca physiology) across few files, fits the inline pattern.

Which approach?
