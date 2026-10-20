# Longitudinal Phase 2 — Markov Stage Absorption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the existing `_disease_progression` aging pass + `stage_transition.yaml` monolith into the Phase 1 longitudinal engine as a `markov` pattern per-family yaml set. Retire `PersonRecord.disease_stages` and `stage_transition.yaml`; consumers read stage via `state_at(person, when).chronic_stages[icd_base]`.

**Architecture:** Add a `MarkovSpec` + `step` / `initial` pair to `clinosim.modules.longitudinal.patterns`, register it in `PATTERN_REGISTRY` and the engine's `_apply_pattern` dispatch, split `stage_transition.yaml` into 11 per-family yamls under `clinosim/locale/shared/longitudinal/stage/`, and retire the five hand-written code paths that read / write `person.disease_stages`. External `_comorbidity_multiplier` is kept as a pre-step multiplier passed into `markov.step(..., multiplier=...)` — inlining per-attribute `modifiers:` blocks is deferred to Phase 3 to keep the migration scope bounded.

**Tech Stack:** Python 3.12, pydantic (schema validation), numpy (RNG), pyyaml.

**Spec:** `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` — §3.3 pattern composition, §4.2.2 Markov yaml body, §5.2 pattern-level API, §7 migration plan.

## Global Constraints

- `pattern: markov` yamls live under `clinosim/locale/shared/longitudinal/stage/` (one directory per pattern family); loader globs the whole `longitudinal/` tree recursively.
- Markov step signature mirrors AR(1): `step(prev: str, rng: np.random.Generator, spec: MarkovSpec, *, multiplier: float = 1.0) -> str`. Multiplier scales the per-year transition probability from the current state; clamped to `[0.0, 1.0]`.
- Terminal states (annual_advance_probability 0.0 or missing from `transitions:`) are absorbing — `step` returns `prev` unchanged.
- Initial state draw uses `initial_distribution:` block (categorical over `states`).
- Each per-family yaml carries `clinical_scope.requires_chronic_codes: [<icd_base>]` so the engine runs the attribute only for patients who carry that chronic.
- Deterministic RNG salt: `aging_sub_seed(person_id, year, f"longitudinal:{attribute_id}")` (same salt convention as Phase 1).
- Byte-identity across the migration is NOT required (spec §2.3 non-goal). CIF JSON output on patients with any of {N18, J44, I50, I25, F00, K70, K74, G20, I48, G35, I69.x} changes substantively; patients without any of these see cursor-shift-only changes.
- `reproduce.sh` same-seed-twice contract stays as CI gate.

## Review Focus

The five input classes most likely to bite a person using this software that the task tests do not naturally exercise — each line gets its test pinned in the task that owns the code:

1. **Patient activates mid-sim with existing chronic + stage** (e.g. activator writes `ChronicCondition.stage = "CKD G3a"` at year Y+2 after N18 is added by onset): the engine must pick up the existing stage, not reseed from `initial_distribution:`. Pinned in Task 7 (initial_snapshot wiring).
2. **Sub-code precedence I69.3 vs I69**: a person with chronic_conditions `["I69.3"]` must advance under the I69.3 yaml, not fall back to the I69 base-code yaml. Pinned in Task 5 (I69 family split).
3. **Terminal-state absorption**: a person at `"CDR 3"` or `"CKD G5"` must have `step()` return the same string for every subsequent year — never raise, never advance. Pinned in Task 1 (step math).
4. **Multiplier clamp**: a `_comorbidity_multiplier` value of 3.0 against a base rate of 0.4 (CDR 1 → 2) would compound to 1.2 (invalid probability). Multiplier must clamp the final probability at 1.0, not pre-clamp the multiplier. Pinned in Task 1.
5. **I69 base-code reader lookup**: a patient carrying `"I69"` (base-code fallback entry) must successfully advance when the engine iterates attributes — i.e. the loader must register both the sub-code yamls AND a base-code fallback yaml, and the engine picks the longest-prefix match per person. Pinned in Task 5.

---

## File Structure

**Create:**
- `clinosim/modules/longitudinal/patterns/markov.py` — pattern math (step + initial + MarkovSpec).
- `clinosim/locale/shared/longitudinal/stage/ckd_n18.yaml` — N18 CKD G1-G5.
- `clinosim/locale/shared/longitudinal/stage/copd_j44.yaml` — J44 COPD GOLD 1-4.
- `clinosim/locale/shared/longitudinal/stage/heart_failure_i50.yaml` — I50 NYHA I-IV.
- `clinosim/locale/shared/longitudinal/stage/ischemic_heart_i25.yaml` — I25 CCS I-III.
- `clinosim/locale/shared/longitudinal/stage/dementia_f00.yaml` — F00 CDR 0.5-3.
- `clinosim/locale/shared/longitudinal/stage/alcoholic_liver_k70.yaml` — K70 Child-Pugh A-C.
- `clinosim/locale/shared/longitudinal/stage/fibrosis_liver_k74.yaml` — K74 Child-Pugh A-C.
- `clinosim/locale/shared/longitudinal/stage/parkinson_g20.yaml` — G20 H&Y 1-5.
- `clinosim/locale/shared/longitudinal/stage/atrial_fib_i48.yaml` — I48 Paroxysmal → Permanent.
- `clinosim/locale/shared/longitudinal/stage/multiple_sclerosis_g35.yaml` — G35 EDSS 0-7.5+.
- `clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69_3.yaml` — I69.3 mRS 0-5 (ischemic).
- `clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69_1.yaml` — I69.1 mRS 0-5 (hemorrhagic).
- `clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69.yaml` — I69 mRS 0-5 (base-code fallback).
- `tests/modules/longitudinal/test_markov_step.py` — pattern math.
- `tests/modules/longitudinal/test_markov_initial.py` — initial distribution.
- `tests/modules/longitudinal/test_stage_absorption_integration.py` — p=50 cohort CKD stage advance.
- `tests/integration/test_stage_trajectory_in_cif.py` — CKD cohort stage distribution across 5y.

**Modify:**
- `clinosim/modules/longitudinal/patterns/__init__.py` — register `markov` in `PATTERN_REGISTRY`.
- `clinosim/modules/longitudinal/loader.py` — add `markov` to `_IMPLEMENTED_PATTERNS`; dispatch to `MarkovSpec` for pattern body validation.
- `clinosim/modules/longitudinal/engine.py` — extend `_apply_pattern` to dispatch `markov` to `snapshot.chronic_stages`; thread `multiplier` kwarg from `_comorbidity_multiplier`.
- `clinosim/modules/population/aging.py` — retire `_disease_progression`, `_load_stage_transitions`, `_initialise_disease_stages`. Keep `_comorbidity_multiplier` + its yaml (used as pre-step multiplier).
- `clinosim/modules/patient/activator.py` — migrate stage-string generation at lines 365-469 to read from `state_at(person, as_of_year_date).chronic_stages`.
- `clinosim/simulator/helpers.py:142` — `person.disease_stages["I69"] = stage` becomes a write into the latest `YearSnapshot.chronic_stages`.
- `clinosim/types/population.py` — remove `disease_stages: dict[str, str]` field.
- `clinosim/locale/loader.py` — delete `load_stage_transition()` function + registry entry.
- `clinosim/locale/shared/stage_transition.yaml` — DELETE (file removed).
- `tests/unit/modules/population/test_aging_disease_progression.py` — DELETE (coverage replaced by Task 1 + Task 12).
- `tests/unit/modules/patient/test_disease_stages_snapshot_1572.py` — DELETE (field removed).
- `tests/unit/modules/patient/test_stage_at_year_1581.py` — DELETE or rewrite under new engine state_at semantics.
- `tests/unit/simulator/test_stroke_sequela_discharge_time.py` — rewrite I69 stage write assertion against `longitudinal_history`.
- `tests/unit/modules/population/test_aging_hook_1564.py` — scrub remaining `disease_stages` references.
- `CHANGELOG.md` — Unreleased Added + Changed + Removed entries.

---

## Task 1: Markov pattern math (step + initial + MarkovSpec)

**Files:**
- Create: `clinosim/modules/longitudinal/patterns/markov.py`
- Test: `tests/modules/longitudinal/test_markov_step.py`, `tests/modules/longitudinal/test_markov_initial.py`

**Interfaces:**
- Produces: `MarkovSpec` pydantic model (`states: list[str]`, `initial_distribution: dict[str, float]`, `transitions: dict[str, dict[str, float]]`, `state_name: str`, `icd_base: str`); `step(prev: str, rng: np.random.Generator, spec: MarkovSpec, *, multiplier: float = 1.0) -> str`; `initial(rng: np.random.Generator, spec: MarkovSpec) -> str`.

- [ ] **Step 1: Write failing test for `step` basic transition**

```python
# tests/modules/longitudinal/test_markov_step.py
import numpy as np
from clinosim.modules.longitudinal.patterns.markov import MarkovSpec, step

def test_step_advances_on_hit():
    spec = MarkovSpec(
        state_name="ckd_stage", icd_base="N18",
        states=["G1", "G2", "G3"],
        initial_distribution={"G1": 1.0},
        transitions={"G1": {"G2": 1.0}, "G2": {"G3": 1.0}, "G3": {}},
    )
    rng = np.random.default_rng(0)
    assert step("G1", rng, spec) == "G2"
    assert step("G2", rng, spec) == "G3"

def test_step_terminal_absorbs():
    spec = MarkovSpec(
        state_name="ckd_stage", icd_base="N18",
        states=["G1", "G5"],
        initial_distribution={"G1": 1.0},
        transitions={"G1": {"G5": 0.0}, "G5": {}},
    )
    rng = np.random.default_rng(0)
    assert step("G5", rng, spec) == "G5"
    assert step("G1", rng, spec) == "G1"  # 0.0 prob → stays

def test_step_multiplier_scales_rate():
    spec = MarkovSpec(
        state_name="x", icd_base="X",
        states=["A", "B"],
        initial_distribution={"A": 1.0},
        transitions={"A": {"B": 0.1}, "B": {}},
    )
    # 10000 draws at multiplier=5.0 → ~50 % advance (0.5 clamp)
    rng = np.random.default_rng(42)
    hits = sum(1 for _ in range(10000) if step("A", rng, spec, multiplier=5.0) == "B")
    assert 4500 < hits < 5500, f"multiplier=5.0 on p=0.1 expected ~0.5, got {hits/10000:.3f}"

def test_step_multiplier_clamps_final_probability():
    """Review Focus #4: multiplier that would compound past 1.0 must clamp at the probability level, not pre-clamp the multiplier itself."""
    spec = MarkovSpec(
        state_name="x", icd_base="X",
        states=["A", "B"],
        initial_distribution={"A": 1.0},
        transitions={"A": {"B": 0.4}, "B": {}},
    )
    rng = np.random.default_rng(0)
    # 0.4 * 3.0 = 1.2 → clamped to 1.0 → always advance
    for _ in range(100):
        assert step("A", rng, spec, multiplier=3.0) == "B"

def test_step_unknown_state_raises():
    spec = MarkovSpec(
        state_name="x", icd_base="X",
        states=["A", "B"],
        initial_distribution={"A": 1.0},
        transitions={"A": {"B": 0.1}, "B": {}},
    )
    rng = np.random.default_rng(0)
    import pytest
    with pytest.raises(ValueError, match="unknown"):
        step("Z", rng, spec)
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_markov_step.py -v`
Expected: FAIL with "No module named 'clinosim.modules.longitudinal.patterns.markov'"

- [ ] **Step 3: Implement `markov.py`**

Define `MarkovSpec` as a pydantic `BaseModel` with fields above. `step()` resolves the row at `transitions[prev]`; builds a (next_state, prob) list; for each candidate, multiplies prob by `multiplier`, clamps to `[0.0, 1.0]`; draws one uniform `rng.random()` and compares cumulatively; if no destination is hit, returns `prev` (stay). Terminal state = empty row. Unknown prev raises `ValueError`. `initial()` draws from the categorical `initial_distribution` by cumulative uniform.

- [ ] **Step 4: Verify step tests pass**

Run: `pytest tests/modules/longitudinal/test_markov_step.py -v`
Expected: 5/5 pass

- [ ] **Step 5: Write failing test for `initial` distribution shape**

```python
# tests/modules/longitudinal/test_markov_initial.py
import numpy as np
from clinosim.modules.longitudinal.patterns.markov import MarkovSpec, initial

def test_initial_matches_distribution():
    spec = MarkovSpec(
        state_name="ckd_stage", icd_base="N18",
        states=["G1", "G2", "G3", "G4", "G5"],
        initial_distribution={"G1": 0.20, "G2": 0.45, "G3": 0.20, "G4": 0.10, "G5": 0.05},
        transitions={},
    )
    rng = np.random.default_rng(42)
    draws = [initial(rng, spec) for _ in range(10000)]
    counts = {s: draws.count(s) / 10000 for s in spec.states}
    assert abs(counts["G2"] - 0.45) < 0.02, counts
    assert abs(counts["G5"] - 0.05) < 0.02, counts
```

- [ ] **Step 6: Verify initial test passes**

Run: `pytest tests/modules/longitudinal/test_markov_initial.py -v`
Expected: 1/1 pass

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/markov.py tests/modules/longitudinal/test_markov_step.py tests/modules/longitudinal/test_markov_initial.py
git commit -s -m "feat(longitudinal): add Markov pattern math (step + initial + MarkovSpec)"
```

---

## Task 2: Register `markov` in PATTERN_REGISTRY, loader, and engine dispatch

**Files:**
- Modify: `clinosim/modules/longitudinal/patterns/__init__.py`
- Modify: `clinosim/modules/longitudinal/loader.py` (`_IMPLEMENTED_PATTERNS` + pattern-body dispatch)
- Modify: `clinosim/modules/longitudinal/engine.py` (`_apply_pattern`)
- Test: `tests/modules/longitudinal/test_engine_markov_dispatch.py` (new)

**Interfaces:**
- Consumes: `MarkovSpec` + `step` + `initial` from Task 1.
- Produces: `_apply_pattern` writes `snapshot.chronic_stages[icd_base] = <next_stage>` for `pattern: markov` attributes; multiplier parameter wired through from the engine's caller (left as `multiplier=1.0` default in this task; Task 8 threads the real multiplier from `_comorbidity_multiplier`).

- [ ] **Step 1: Write failing test asserting engine dispatches to markov**

```python
# tests/modules/longitudinal/test_engine_markov_dispatch.py
# Verifies that advance_one_year on a person with a chronic condition
# whose attribute uses pattern: markov writes into
# YearSnapshot.chronic_stages, not .continuous.
```

Mock a tiny per-family yaml via `monkeypatch` of `_LONGITUDINAL_DIR`, with one `ckd_test.yaml` whose icd_base is `TEST`, states `["A", "B"]`, deterministic transition `A → B` at p=1.0. Create a `PersonRecord` with `chronic_conditions=["TEST"]`. Call `initial_snapshot` then `advance_one_year`. Assert the two snapshots carry `chronic_stages={"TEST": "A"}` and `chronic_stages={"TEST": "B"}` respectively.

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_engine_markov_dispatch.py -v`
Expected: FAIL with `NotImplementedError: pattern 'markov' not implemented in Phase 1`

- [ ] **Step 3: Register markov in `patterns/__init__.py`**

Add `"markov": {"spec": markov.MarkovSpec, "step": markov.step, "initial": markov.initial}` to `PATTERN_REGISTRY`. Import `markov` module.

- [ ] **Step 4: Add markov to `_IMPLEMENTED_PATTERNS` in loader + wire schema dispatch**

Change `_IMPLEMENTED_PATTERNS = frozenset({"ar1", "markov"})`. In the `_load_one` branch that validates pattern body, add `elif raw["pattern"] == "markov": body = MarkovSpec.model_validate(...)` alongside the existing AR1 branch.

- [ ] **Step 5: Extend `_apply_pattern` in engine.py**

Add a `markov` branch after the existing `ar1` branch:

```python
elif spec.pattern == "markov":
    icd = spec.body.icd_base
    if prev_snapshot is None:
        value = handler["initial"](rng, spec.body)
    else:
        prev_value = prev_snapshot.chronic_stages.get(icd)
        if prev_value is None:
            value = handler["initial"](rng, spec.body)
        else:
            value = handler["step"](prev_value, rng, spec.body)
    snapshot.chronic_stages[icd] = value
```

- [ ] **Step 6: Verify test passes**

Run: `pytest tests/modules/longitudinal/test_engine_markov_dispatch.py -v`
Expected: 1/1 pass

- [ ] **Step 7: Verify Phase 1 tests still green**

Run: `pytest tests/modules/longitudinal/ -v`
Expected: all green (Phase 1 61 tests + Task 1's 6 + Task 2's 1 = 68/68)

- [ ] **Step 8: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/__init__.py clinosim/modules/longitudinal/loader.py clinosim/modules/longitudinal/engine.py tests/modules/longitudinal/test_engine_markov_dispatch.py
git commit -s -m "feat(longitudinal): register markov pattern in registry + loader + engine dispatch"
```

---

## Task 3: Split primary chronic conditions — CKD / COPD / HF / IHD / Dementia yamls

**Files:**
- Create: `clinosim/locale/shared/longitudinal/stage/ckd_n18.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/copd_j44.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/heart_failure_i50.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/ischemic_heart_i25.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/dementia_f00.yaml`
- Modify: `clinosim/modules/longitudinal/loader.py` (recursive glob of `longitudinal/**/*.yaml`)
- Test: `tests/modules/longitudinal/test_stage_yamls_load.py` (new)

**Interfaces:**
- Consumes: `MarkovSpec` + loader dispatch from Task 2.
- Produces: five `AttributeSpec` registered at import time under keys `ckd_stage_n18`, `copd_stage_j44`, `heart_failure_stage_i50`, `ischemic_heart_stage_i25`, `dementia_stage_f00`.

- [ ] **Step 1: Write failing test asserting the 5 yamls load with correct ICD base + states**

```python
# tests/modules/longitudinal/test_stage_yamls_load.py
from clinosim.modules.longitudinal.loader import load_attribute_specs

EXPECTED = {
    "ckd_stage_n18": ("N18", ["CKD G1", "CKD G2", "CKD G3a", "CKD G3b", "CKD G4", "CKD G5"]),
    "copd_stage_j44": ("J44", ["GOLD 1", "GOLD 2", "GOLD 3", "GOLD 4"]),
    "heart_failure_stage_i50": ("I50", ["NYHA I", "NYHA II", "NYHA III", "NYHA IV"]),
    "ischemic_heart_stage_i25": ("I25", ["CCS I", "CCS II", "CCS III"]),
    "dementia_stage_f00": ("F00", ["CDR 0.5", "CDR 1", "CDR 2", "CDR 3"]),
}

def test_primary_chronic_stage_yamls_load():
    specs = load_attribute_specs()
    for attr_id, (icd, states) in EXPECTED.items():
        assert attr_id in specs, f"missing {attr_id}"
        body = specs[attr_id].body
        assert body.icd_base == icd
        assert body.states == states
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_stage_yamls_load.py -v`
Expected: FAIL with 5 missing attribute keys.

- [ ] **Step 3: Update loader to glob recursively**

Change `_LONGITUDINAL_DIR.glob("*.yaml")` to `_LONGITUDINAL_DIR.rglob("*.yaml")` so files under `stage/` are discovered.

- [ ] **Step 4: Author the 5 yamls**

Each yaml follows the schema in spec §4.2.2. Translate the existing N18 / J44 / I50 / I25 / F00 entries from `clinosim/locale/shared/stage_transition.yaml` verbatim into per-family files. Preserve all clinical commentary (Thompson 2013 / GOLD 2023 / Ponikowski 2016 / etc.) in each yaml's leading comment block. Transition probabilities translate: existing `annual_advance_probability[X] = p` → `transitions[X] = {<next_state>: p}` where `<next_state>` is the next element in `states`. Terminal rows become `transitions[<terminal>] = {}`.

Example skeleton (CKD):

```yaml
# locale/shared/longitudinal/stage/ckd_n18.yaml
# N18 Chronic Kidney Disease — Markov stage transitions (KDIGO G1-G5).
# ... clinical commentary preserved from stage_transition.yaml ...

attribute_id: ckd_stage_n18
pattern: markov
depends_on: []
clinical_scope:
  requires_chronic_codes: ["N18"]
  requires_age_band: [0, 120]

state_name: ckd_stage
icd_base: N18
states: ["CKD G1", "CKD G2", "CKD G3a", "CKD G3b", "CKD G4", "CKD G5"]
initial_distribution:
  "CKD G1": 0.40
  "CKD G2": 0.35
  "CKD G3a": 0.15
  "CKD G3b": 0.07
  "CKD G4": 0.025
  "CKD G5": 0.005
transitions:
  "CKD G1": {"CKD G2": 0.015}
  "CKD G2": {"CKD G3a": 0.025}
  "CKD G3a": {"CKD G3b": 0.050}
  "CKD G3b": {"CKD G4": 0.080}
  "CKD G4": {"CKD G5": 0.120}
  "CKD G5": {}
narrative_label:
  en: "CKD stage"
  ja: "CKD ステージ"
```

Initial-distribution values: Phase 2 default is the existing activator distribution (if any) OR a mild-skewed default consistent with incident-cohort epidemiology. For CKD, mirror the KDIGO population-prevalence profile. For N18 / J44 / I50 / I25 / F00 these are the author's call unless the current activator already seeds a specific distribution — in that case, lift it verbatim; record the choice as a `Ruling:` line in the executor's ledger if divergent.

**Ruling (plan author)**: For every family where the existing activator already seeds a specific stage distribution (`_initialise_disease_stages` in aging.py line 412-oriented path), the implementer MUST lift it verbatim. Divergence is a semantic change that goes in the Phase 2 PR body audit table, not a silent default.

- [ ] **Step 5: Verify test passes**

Run: `pytest tests/modules/longitudinal/test_stage_yamls_load.py -v`
Expected: 1/1 pass

- [ ] **Step 6: Commit**

```bash
git add clinosim/locale/shared/longitudinal/stage/ckd_n18.yaml clinosim/locale/shared/longitudinal/stage/copd_j44.yaml clinosim/locale/shared/longitudinal/stage/heart_failure_i50.yaml clinosim/locale/shared/longitudinal/stage/ischemic_heart_i25.yaml clinosim/locale/shared/longitudinal/stage/dementia_f00.yaml clinosim/modules/longitudinal/loader.py tests/modules/longitudinal/test_stage_yamls_load.py
git commit -s -m "feat(longitudinal): add Markov yamls for CKD, COPD, HF, IHD, dementia"
```

---

## Task 4: Secondary chronic conditions — AlcLiver / FibLiver / Parkinson / AF yamls

**Files:**
- Create: `clinosim/locale/shared/longitudinal/stage/alcoholic_liver_k70.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/fibrosis_liver_k74.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/parkinson_g20.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/atrial_fib_i48.yaml`
- Test: extend `tests/modules/longitudinal/test_stage_yamls_load.py` (add 4 entries to EXPECTED)

**Interfaces:**
- Consumes: loader + MarkovSpec from Task 2.
- Produces: `alcoholic_liver_stage_k70`, `fibrosis_liver_stage_k74`, `parkinson_stage_g20`, `atrial_fib_stage_i48` AttributeSpecs.

- [ ] **Step 1: Extend EXPECTED dict in test_stage_yamls_load.py**

Add the 4 new entries with their expected (icd_base, states) tuples:
- K70: `["Child-Pugh A", "Child-Pugh B", "Child-Pugh C"]`
- K74: same Child-Pugh set
- G20: `["H&Y 1", "H&Y 2", "H&Y 3", "H&Y 4", "H&Y 5"]`
- I48: `["Paroxysmal", "Persistent", "Long-standing persistent", "Permanent"]`

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_stage_yamls_load.py -v`
Expected: FAIL with 4 missing keys.

- [ ] **Step 3: Author the 4 yamls**

Translate from `stage_transition.yaml` K70 / K74 / G20 / I48 rows verbatim, following the Task 3 schema. Preserve clinical commentary (D'Amico 2006 / Hoehn-Yahr / de Vos 2010 / etc.) in the leading comment block.

- [ ] **Step 4: Verify test passes**

Run: `pytest tests/modules/longitudinal/test_stage_yamls_load.py -v`
Expected: 1/1 pass (9/9 expected keys).

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/stage/alcoholic_liver_k70.yaml clinosim/locale/shared/longitudinal/stage/fibrosis_liver_k74.yaml clinosim/locale/shared/longitudinal/stage/parkinson_g20.yaml clinosim/locale/shared/longitudinal/stage/atrial_fib_i48.yaml tests/modules/longitudinal/test_stage_yamls_load.py
git commit -s -m "feat(longitudinal): add Markov yamls for alcoholic liver, fibrotic liver, Parkinson's, AF"
```

---

## Task 5: Stroke-sequela family — I69.3 / I69.1 / I69 base + sub-code precedence

**Files:**
- Create: `clinosim/locale/shared/longitudinal/stage/multiple_sclerosis_g35.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69_3.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69_1.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69.yaml`
- Modify: `clinosim/modules/longitudinal/engine.py` — longest-prefix selection when multiple attributes share an icd_base-prefix match for the same person.
- Test: `tests/modules/longitudinal/test_stage_yamls_load.py` extended; `tests/modules/longitudinal/test_i69_subcode_precedence.py` (new)

**Interfaces:**
- Consumes: engine `_attribute_in_scope`.
- Produces: deterministic ordering — when a person carries `"I69.3"`, the engine selects the I69.3 attribute (longest prefix match on `requires_chronic_codes` vs `chronic_conditions`); when they carry only `"I69"` or `"I69.0"` / `"I69.2"`, the base-code I69 attribute runs.

- [ ] **Step 1: Write test asserting sub-code precedence I69.3 > I69**

```python
# tests/modules/longitudinal/test_i69_subcode_precedence.py
# Review Focus #2 + #5.
# A person with chronic_conditions=["I69.3"] must advance under the
# stroke_sequela_stage_i69_3 attribute, not the base stroke_sequela_stage_i69.
# A person with chronic_conditions=["I69"] advances under the base.
```

Fixture: two PersonRecords, one with `["I69.3"]`, one with `["I69"]`. For both, call `initial_snapshot` then `advance_one_year` with a seed that drives the I69.3 yaml's `"mRS 0" → "mRS 1"` transition to fire deterministically (rig the yamls with a conspicuous rate difference, e.g. I69.3 → mRS 1 at 1.0, I69 base → mRS 1 at 0.0). Assert the first person reaches `"mRS 1"`, the second stays at `"mRS 0"`.

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_i69_subcode_precedence.py -v`
Expected: FAIL — multiple attributes match the I69.3-carrying person and the engine runs both or picks the wrong one.

- [ ] **Step 3: Author the 4 yamls**

Translate G35 / I69.3 / I69.1 / I69 rows from stage_transition.yaml. Note: states for mRS and EDSS carry the stage-string prefix exactly as the existing yaml (`"mRS 0"`, `"EDSS 0-2"`).

- [ ] **Step 4: Add longest-prefix selection to engine**

In `advance_one_year`, when iterating topologically-sorted attribute_ids, before calling `_apply_pattern` on a `markov` attribute, check whether another attribute with a longer-prefix `requires_chronic_codes` match for this same person already ran this year (via `_executed_this_year: set[str]`). If so, skip. Group by `icd_base` first — multiple attributes targeting the same `icd_base` (I69 vs I69.3) are the trigger; attributes with distinct `icd_base` keys always both run.

- [ ] **Step 5: Verify I69.3 test passes**

Run: `pytest tests/modules/longitudinal/test_i69_subcode_precedence.py -v`
Expected: 1/1 pass.

- [ ] **Step 6: Verify stage yamls still load**

Run: `pytest tests/modules/longitudinal/test_stage_yamls_load.py -v`
Expected: 1/1 pass (14/14 expected keys: 11 chronic + 3 I69 variants).

- [ ] **Step 7: Commit**

```bash
git add clinosim/locale/shared/longitudinal/stage/multiple_sclerosis_g35.yaml clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69_3.yaml clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69_1.yaml clinosim/locale/shared/longitudinal/stage/stroke_sequela_i69.yaml clinosim/modules/longitudinal/engine.py tests/modules/longitudinal/test_i69_subcode_precedence.py tests/modules/longitudinal/test_stage_yamls_load.py
git commit -s -m "feat(longitudinal): add MS + stroke-sequela Markov yamls with sub-code precedence"
```

---

## Task 6: Wire `initial_snapshot` to seed `chronic_stages` from the activator's existing stage strings

**Files:**
- Modify: `clinosim/modules/longitudinal/engine.py` — `_apply_pattern` in the `prev_snapshot is None` branch for markov now first checks the person's existing `ChronicCondition.stage` value for the matching icd_base; if present, uses it instead of drawing from `initial_distribution`.
- Modify: `clinosim/modules/population/engine.py` — `generate_population` currently calls `initial_snapshot` for longitudinal:init; must ensure this runs AFTER activator (if activator has already run) OR activator must seed via engine. Rule: engine wins — activator stops seeding `disease_stages`; initial draw happens in engine.
- Test: `tests/modules/longitudinal/test_initial_snapshot_markov_seed.py` (new).

**Interfaces:**
- Consumes: `PersonRecord.chronic_conditions: list[ChronicCondition]` (with `.stage` strings already activated).
- Produces: `initial_snapshot(person, year, rng).chronic_stages[icd]` equals the already-activated ChronicCondition.stage, when present. When absent, draws from `initial_distribution:` via `markov.initial`.

- [ ] **Step 1: Write failing test for mid-sim activation respecting existing stage**

```python
# Review Focus #1.
# A person who activates with ChronicCondition(code="N18", stage="CKD G3a")
# must have initial_snapshot write chronic_stages["N18"] = "CKD G3a",
# not draw a fresh initial from the distribution.
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_initial_snapshot_markov_seed.py -v`
Expected: FAIL — initial draws from distribution regardless of pre-existing stage.

- [ ] **Step 3: Add stage-preserving branch in `_apply_pattern`**

Before the initial-draw branch, iterate `person.chronic_conditions` looking for `ChronicCondition.code.startswith(spec.body.icd_base)` with a non-empty `.stage` — if found, lift it. Normalise stage strings (strip whitespace).

- [ ] **Step 4: Verify test passes**

Run: `pytest tests/modules/longitudinal/test_initial_snapshot_markov_seed.py -v`
Expected: 1/1 pass.

- [ ] **Step 5: Verify Phase 1 + prior Phase 2 tests green**

Run: `pytest tests/modules/longitudinal/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/longitudinal/engine.py tests/modules/longitudinal/test_initial_snapshot_markov_seed.py
git commit -s -m "feat(longitudinal): seed Markov chronic_stages from activator's existing ChronicCondition.stage"
```

---

## Task 7: Thread `_comorbidity_multiplier` into Markov step through engine kwarg

**Files:**
- Modify: `clinosim/modules/longitudinal/engine.py` — accept an optional `multiplier_fn: Callable[[PersonRecord, str, int], float] | None = None` on `advance_one_year`; call it for each markov attribute and pass as `multiplier=` into `step`.
- Modify: `clinosim/modules/population/aging.py` — `advance_population` passes `multiplier_fn=_comorbidity_multiplier` into `advance_one_year`. Keep `_comorbidity_multiplier` + its yaml unchanged.
- Test: `tests/modules/longitudinal/test_markov_multiplier_wiring.py` (new).

**Interfaces:**
- Consumes: `_comorbidity_multiplier(person: PersonRecord, target_icd: str, year: int) -> float` from aging.py (unchanged).
- Produces: `advance_one_year(person, year, rng, *, multiplier_fn=None)` — when provided, resolves per-icd-base multiplier before each markov step.

- [ ] **Step 1: Write failing test**

Build a mock `multiplier_fn` that returns 3.0 for N18 and 1.0 otherwise. Rig a tiny CKD yaml under temp dir with transition `"CKD G1" → "CKD G2"` at base p=0.1. Over 10k seeds confirm advance rate ≈ 0.3 (3.0 × 0.1 = 0.3, well under 1.0 clamp).

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_markov_multiplier_wiring.py -v`
Expected: FAIL — observed rate ≈ 0.1 (multiplier not applied).

- [ ] **Step 3: Thread multiplier through engine**

Change `advance_one_year` signature to accept `multiplier_fn`. In `_apply_pattern`, for markov, resolve `multiplier = multiplier_fn(person, spec.body.icd_base, year) if multiplier_fn else 1.0`, pass to `step`.

- [ ] **Step 4: Wire in aging driver**

In `clinosim/modules/population/aging.py::advance_population`, inject `multiplier_fn=_comorbidity_multiplier` into the `advance_one_year` call.

- [ ] **Step 5: Verify test passes**

Run: `pytest tests/modules/longitudinal/test_markov_multiplier_wiring.py -v`
Expected: 1/1 pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/longitudinal/engine.py clinosim/modules/population/aging.py tests/modules/longitudinal/test_markov_multiplier_wiring.py
git commit -s -m "feat(longitudinal): thread _comorbidity_multiplier into Markov step via multiplier_fn"
```

---

## Task 8: Migrate activator stage-string generation to `state_at` reads

**Files:**
- Modify: `clinosim/modules/patient/activator.py:365-469` — `stage_at_year` + `_populate_chronic_stage` now read from `state_at(person, as_of_year_date).chronic_stages[code_base]` instead of `person.disease_stages[code_base]`.
- Test: `tests/unit/modules/patient/test_activator_stage_from_state_at.py` (new).

**Interfaces:**
- Consumes: `state_at(person, when)` from Phase 1.
- Produces: `ChronicCondition.stage` populated at activation reads from the year-matched YearSnapshot, not from the retired `person.disease_stages`.

- [ ] **Step 1: Write failing test**

Set up a PersonRecord whose `longitudinal_history` is `[YearSnapshot(year=2024, chronic_stages={"N18": "CKD G3b"})]`. Call the activator path that populates `ChronicCondition.stage` at year 2024. Assert the resulting stage is `"CKD G3b"`.

- [ ] **Step 2: Verify failing**

Run: `pytest tests/unit/modules/patient/test_activator_stage_from_state_at.py -v`
Expected: FAIL — activator still reads from `person.disease_stages[code_base]` which is empty.

- [ ] **Step 3: Migrate activator reader**

Replace the read sites at `activator.py:365-469` with:

```python
from clinosim.modules.longitudinal.engine import state_at
snapshot = state_at(person, date(as_of_year, 1, 1))
stage = snapshot.chronic_stages.get(code_base, "")
```

For code paths that previously wrote back to `person.disease_stages`, delete the write (engine owns the state now).

- [ ] **Step 4: Verify test passes**

Run: `pytest tests/unit/modules/patient/test_activator_stage_from_state_at.py -v`
Expected: 1/1 pass.

- [ ] **Step 5: Verify activator unit suite green**

Run: `pytest tests/unit/modules/patient/ -v`
Expected: all green (except retired tests covered in Task 10).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/patient/activator.py tests/unit/modules/patient/test_activator_stage_from_state_at.py
git commit -s -m "feat(longitudinal): migrate activator stage-string reads to state_at(.).chronic_stages"
```

---

## Task 9: Migrate helpers.py stroke-sequela setter + residual readers

**Files:**
- Modify: `clinosim/simulator/helpers.py:142` — `person.disease_stages["I69"] = stage` becomes a write to the latest `YearSnapshot.chronic_stages["I69"]`.
- Modify: `tests/unit/simulator/test_stroke_sequela_discharge_time.py` — assert against `longitudinal_history`.
- Modify: `clinosim/modules/population/aging.py::_comorbidity_multiplier` — `stages = person.disease_stages or {}` becomes `stages = state_at(person, date(year, 1, 1)).chronic_stages`.

**Interfaces:**
- Consumes: `state_at(person, when).chronic_stages` from Phase 1 engine.
- Produces: no residual `person.disease_stages` reads remain outside the retired aging passes.

- [ ] **Step 1: Grep for residual reads**

```bash
grep -rn 'person\.disease_stages\|\.disease_stages\s*\[' clinosim/ tests/
```

Record every hit. Each one gets migrated or deleted.

- [ ] **Step 2: Write failing test for helpers.py setter migration**

Build a person with an initial YearSnapshot at year=2024. Call `helpers._set_stroke_sequela_stage(person, "mRS 2", when=date(2024, 6, 1))`. Assert `person.longitudinal_history[-1].chronic_stages["I69"] == "mRS 2"`.

- [ ] **Step 3: Verify failing**

Run: `pytest tests/unit/simulator/test_stroke_sequela_discharge_time.py -v`
Expected: FAIL — helper still writes to `person.disease_stages`.

- [ ] **Step 4: Migrate helpers.py:142 + comorbidity multiplier reader**

In `helpers.py`, replace the `disease_stages` write with a `state_at(person, when).chronic_stages[...]` write (mutate the matched snapshot in place). In `aging.py::_comorbidity_multiplier`, replace `stages = person.disease_stages or {}` with a `state_at` lookup gated by `person.longitudinal_history` being non-empty (return default multiplier of 1.0 when no history yet, matching current pre-aging-pass fallback).

- [ ] **Step 5: Verify tests pass**

Run: `pytest tests/unit/simulator/test_stroke_sequela_discharge_time.py -v`
Expected: pass.

Run: grep again — zero hits:

```bash
grep -rn 'person\.disease_stages\|\.disease_stages\s*\[' clinosim/
```

Expected: 0 results.

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/helpers.py clinosim/modules/population/aging.py tests/unit/simulator/test_stroke_sequela_discharge_time.py
git commit -s -m "refactor(longitudinal): migrate helpers.py + _comorbidity_multiplier readers to state_at"
```

---

## Task 10: Retire `_disease_progression` + `stage_transition.yaml` + obsolete loader + obsolete tests

**Files:**
- Modify: `clinosim/modules/population/aging.py` — delete `_disease_progression`, `_load_stage_transitions`, `_initialise_disease_stages`; remove from the aging-pass list.
- Delete: `clinosim/locale/shared/stage_transition.yaml`.
- Modify: `clinosim/locale/loader.py` — delete `load_stage_transition()` + any registry entry.
- Delete: `tests/unit/modules/population/test_aging_disease_progression.py`.
- Delete: `tests/unit/modules/patient/test_disease_stages_snapshot_1572.py`.
- Delete: `tests/unit/modules/patient/test_stage_at_year_1581.py` (or rewrite under new engine `state_at`; smaller-change rule: delete and lean on Task 12 integration).
- Modify: `tests/unit/modules/population/test_aging_hook_1564.py` — scrub remaining disease_stages references (replace with longitudinal_history setup).

**Interfaces:**
- Consumes: no new deps.
- Produces: dead-code sweep is complete — the engine is the single source of truth.

- [ ] **Step 1: Verify Task 9 complete (no residual readers)**

```bash
grep -rn 'disease_stages\|_disease_progression\|_load_stage_transitions\|_initialise_disease_stages\|load_stage_transition\|stage_transition\.yaml' clinosim/ --include="*.py" --include="*.yaml"
```

Expected: hits only inside `aging.py` (for the functions to be deleted), the yaml itself, and the locale loader.

- [ ] **Step 2: Delete the three retired functions in aging.py**

Remove `_disease_progression`, `_load_stage_transitions`, `_initialise_disease_stages`. Remove them from the aging-pass registration tuple at `aging.py:1030`. Keep `_comorbidity_multiplier` (now called from engine via Task 7).

- [ ] **Step 3: Delete the yaml + loader entry + obsolete tests**

```bash
git rm clinosim/locale/shared/stage_transition.yaml tests/unit/modules/population/test_aging_disease_progression.py tests/unit/modules/patient/test_disease_stages_snapshot_1572.py tests/unit/modules/patient/test_stage_at_year_1581.py
```

Edit `clinosim/locale/loader.py` to delete the `load_stage_transition` function. Grep for callers; migrate / delete each.

Edit `tests/unit/modules/population/test_aging_hook_1564.py`: replace fixture setup that writes `person.disease_stages = {...}` with equivalent `person.longitudinal_history = [YearSnapshot(year=Y, chronic_stages={...})]` setup.

- [ ] **Step 4: Verify full test suite green**

Run: `pytest -x`
Expected: all green.

- [ ] **Step 5: Verify dead-code sweep**

```bash
grep -rn 'disease_stages\|_disease_progression\|_load_stage_transitions\|_initialise_disease_stages\|load_stage_transition\|stage_transition' clinosim/ tests/ --include="*.py" --include="*.yaml"
```

Expected: zero hits (except possibly in CHANGELOG or docs commentary — grep-check only `clinosim/` and `tests/`).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -s -m "chore(longitudinal): retire _disease_progression + stage_transition.yaml + obsolete tests"
```

---

## Task 11: Retire `PersonRecord.disease_stages` field + locale loader sweep

**Files:**
- Modify: `clinosim/types/population.py` — delete `disease_stages: dict[str, str] = field(default_factory=dict)` + its surrounding block comment.
- Modify: `clinosim/modules/patient/activator.py` — ensure no `.disease_stages` assignments remain post-Task 8.
- Modify: `.vulture-whitelist.py` — remove any disease_stages whitelist entries (and add any needed new ones for YearSnapshot.chronic_stages consumers if vulture flags them, though Phase 1 already whitelisted the field).

**Interfaces:**
- Consumes: no new deps.
- Produces: `PersonRecord` field surface shrinks by one.

- [ ] **Step 1: Delete the field + comment block**

Open `clinosim/types/population.py`; delete `disease_stages` field and the inline doc comment immediately preceding it.

- [ ] **Step 2: Run static checks**

```bash
ruff check clinosim/ tests/
ruff format --check clinosim/ tests/
vulture clinosim/ --min-confidence 80
```

Expected: no new errors introduced by the removal.

- [ ] **Step 3: Run full suite**

```bash
pytest -x
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -s -m "chore(longitudinal): retire PersonRecord.disease_stages field"
```

---

## Task 12: Integration + cohort audit — CKD stage distribution across 5y

**Files:**
- Create: `tests/integration/test_stage_trajectory_in_cif.py`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: full longitudinal engine + Phase 2 attributes.
- Produces: a cohort-level sanity check pinning the Phase 2 behavior envelope in CI.

- [ ] **Step 1: Write failing cohort test**

```python
# tests/integration/test_stage_trajectory_in_cif.py
# p=100 US seed=42 5y, filter for N18 patients.
# Across the cohort:
# - After 5 years, the distribution shifts right (mean stage index up by ≥ 0.3)
# - No patient advances by more than 3 stages in 5 years (physiologic bound)
# - No patient regresses (Markov is monotonic absorbing)
```

Build the test using the existing cohort-generator entry points (`generate_population` + `advance_population` 5y). Extract `person.longitudinal_history` for each N18-carrying patient. Compute per-year distribution of the stage index (0..5). Assert the mean year-5 index exceeds mean year-0 index by at least 0.3.

- [ ] **Step 2: Verify failing on pre-fix repo**

On master (pre-Phase 2 code): the test should fail because `person.longitudinal_history[y].chronic_stages["N18"]` is empty under Phase 1.

(Note: in subagent-driven execution, this step is academic since Task 1-11 commits are already in place by this task; execute Step 2 by observing a GREEN result and recording that the test now reflects migrated behavior.)

- [ ] **Step 3: Verify test passes**

Run: `pytest tests/integration/test_stage_trajectory_in_cif.py -v`
Expected: 1/1 pass.

- [ ] **Step 4: Update CHANGELOG.md**

Under `## [Unreleased]`:
- **Added**: Markov pattern + 11 per-family stage yamls under `clinosim/locale/shared/longitudinal/stage/`; cohort stage distribution now progresses year-over-year under Phase 2 engine.
- **Changed**: `_comorbidity_multiplier` now wraps Markov step probability via engine `multiplier_fn` kwarg instead of being called inline from `_disease_progression`.
- **Removed**: `PersonRecord.disease_stages`, `_disease_progression`, `_load_stage_transitions`, `_initialise_disease_stages`, `clinosim/locale/shared/stage_transition.yaml`, `load_stage_transition()` locale loader.

- [ ] **Step 5: Verify full suite + reproduce.sh**

```bash
pytest -x
scripts/reproduce.sh
```

Expected: all green; same-seed-twice byte-identical.

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_stage_trajectory_in_cif.py CHANGELOG.md
git commit -s -m "test(longitudinal): CKD cohort 5y stage distribution integration + CHANGELOG"
```
