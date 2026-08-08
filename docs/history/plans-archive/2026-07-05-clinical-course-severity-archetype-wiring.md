# clinical_course Severity/Archetype Wiring Fix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two verified bugs that make disease-authored clinical content silently inert: (1) `select_archetype()` never receives a disease's own `course_archetypes` probabilities, so every disease uses a generic fallback distribution; (2) a `severity_severe` complication risk-factor condition is hardcoded to always return `False`, and the root cause is that `_run_daily_loop` ignores its own accurate `severity` parameter in favor of a fragile, less-accurate re-derivation (`severity_str`).

**Architecture:** Both fixes are small, surgical edits to existing call sites — no new modules, no new types. Fix A is a one-argument addition at a single call site. Fix B removes ~7 lines of duplicate/fragile logic, threads the already-correct `severity` parameter through two existing call sites that currently ignore it, and replaces a `# simplified` stub with a real (but intentionally narrow — matching only the one condition string that exists in the data today) comparison. A companion TODO.md update records the larger, explicitly out-of-scope architecture question (two disconnected severity systems, several orphaned disease-YAML keys) per this project's scope-discipline convention.

**Tech Stack:** Python 3.11+, pytest (`unit`/`integration`/`regression` markers), Pydantic (`DiseaseProtocol`), numpy `Generator` for all RNG.

## Global Constraints

- AD-16 determinism: no `random.random()`; all RNG via `numpy.random.Generator`. (Not touched by this plan — no new RNG draws are introduced.)
- No new types — this plan only edits function signatures/bodies in `clinosim/simulator/inpatient.py` and `clinosim/modules/clinical_course/engine.py`.
- Every new/changed behavior needs a TDD test (RED before, GREEN after) per this project's workflow.
- Both fixes change deterministic generation output (course archetype distribution; complication rates for severe encounters). Per AD-66 Rule 1, any golden/regression fixture drift must be regenerated and committed together with the code change in the same commit. Per AD-66 Rule 2, the diff must be read for clinical plausibility, not just accepted because it's the "expected" category of change.
- Scope discipline: do NOT touch `severity.distribution`/`severity.modifiers`/`archetype_modifiers`/other orphaned disease-YAML keys, do NOT add `model_config = ConfigDict(extra="forbid")` to `DiseaseProtocol`, do NOT author `course_archetypes` for the 9 diseases that lack one. These are explicitly deferred to TODO.md (Task 5).
- Full spec: `docs/superpowers/specs/2026-07-05-clinical-course-severity-archetype-wiring-design.md`.

---

### Task 1: Fix `_evaluate_risk_condition` + `evaluate_complications` to accept and use `severity`

**Files:**
- Modify: `clinosim/modules/clinical_course/engine.py:197-276`
- Test: `tests/unit/test_clinical_course.py`

**Interfaces:**
- Consumes: nothing new from other tasks.
- Produces: `evaluate_complications(day, state, patient, complications, active_complications, rng, severity="moderate")` — the new `severity` keyword param (default `"moderate"` so the 3 existing call sites in `tests/unit/test_clinical_course.py` keep passing unchanged). `_evaluate_risk_condition(condition, state, patient, day, severity)` — `severity` is now a required 5th positional param (its only caller, `evaluate_complications`, is updated in this same task). Task 2 will pass the real `severity` value into `evaluate_complications` from `clinosim/simulator/inpatient.py`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_clinical_course.py`, inside the existing `class TestComplications:` (after `test_complication_respects_onset_window`):

```python
    def test_severity_severe_condition_applies_multiplier_when_severe(self):
        rng = np.random.default_rng(0)

        class MockState:
            pass

        class MockPatient:
            age = 50

        complications = [{
            "name": "severe_only_comp",
            "probability_per_day": 0.5,
            "onset_day_range": [1, 5],
            "risk_factors": [{"condition": "severity_severe", "multiplier": 2.0}],
        }]

        # 0.5 * 2.0 = 1.0 -> rng.random() (always < 1.0) guarantees a fire,
        # independent of the specific draw, when severity="severe".
        triggered = evaluate_complications(
            3, MockState(), MockPatient(), complications, set(), rng, severity="severe",
        )
        assert len(triggered) == 1

    def test_severity_severe_condition_not_applied_when_not_severe(self):
        rng = np.random.default_rng(0)

        class MockState:
            pass

        class MockPatient:
            age = 50

        complications = [{
            "name": "severe_only_comp",
            "probability_per_day": 0.0,
            "onset_day_range": [1, 5],
            "risk_factors": [{"condition": "severity_severe", "multiplier": 2.0}],
        }]

        # Base probability is 0.0; the multiplier must NOT apply when
        # severity != "severe", so prob stays 0.0 and never fires.
        triggered = evaluate_complications(
            3, MockState(), MockPatient(), complications, set(), rng, severity="moderate",
        )
        assert len(triggered) == 0
```

Also add a new test class at the end of the file (after `class TestInterpolation:`), importing the private helper directly (this file already does this for `_interpolate`):

```python
@pytest.mark.unit
class TestEvaluateRiskConditionSeverity:
    def test_severity_severe_matches_severe(self):
        assert _evaluate_risk_condition("severity_severe", None, None, 1, "severe") is True

    def test_severity_severe_does_not_match_moderate_or_mild(self):
        assert _evaluate_risk_condition("severity_severe", None, None, 1, "moderate") is False
        assert _evaluate_risk_condition("severity_severe", None, None, 1, "mild") is False
```

Update the module-level import at the top of `tests/unit/test_clinical_course.py` to also import `_evaluate_risk_condition`:

```python
from clinosim.modules.clinical_course.engine import (
    _FALLBACK_PROBABILITIES,
    _evaluate_risk_condition,
    evaluate_complications,
    get_daily_directive,
    select_archetype,
    _interpolate,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_clinical_course.py -v -k "severity_severe"`
Expected: `test_severity_severe_condition_applies_multiplier_when_severe` FAILs with `TypeError: evaluate_complications() got an unexpected keyword argument 'severity'` (or similar); `test_severity_severe_matches_severe` FAILs with `TypeError: _evaluate_risk_condition() takes 4 positional arguments but 5 were given`.

- [ ] **Step 3: Implement the fix**

In `clinosim/modules/clinical_course/engine.py`, change:

```python
def evaluate_complications(
    day: int,
    state: Any,
    patient: Any,
    complications: list[dict[str, Any]],
    active_complications: set[str],
    rng: np.random.Generator,
) -> list[dict[str, Any]]:
```

to:

```python
def evaluate_complications(
    day: int,
    state: Any,
    patient: Any,
    complications: list[dict[str, Any]],
    active_complications: set[str],
    rng: np.random.Generator,
    severity: str = "moderate",
) -> list[dict[str, Any]]:
```

and change the risk-factor loop body:

```python
        # Apply risk factors
        for rf in comp.get("risk_factors", []):
            condition = rf.get("condition", "")
            mult = rf.get("multiplier", 1.0)
            if _evaluate_risk_condition(condition, state, patient, day):
                prob *= mult
```

to:

```python
        # Apply risk factors
        for rf in comp.get("risk_factors", []):
            condition = rf.get("condition", "")
            mult = rf.get("multiplier", 1.0)
            if _evaluate_risk_condition(condition, state, patient, day, severity):
                prob *= mult
```

Then change `_evaluate_risk_condition`'s signature and stub:

```python
def _evaluate_risk_condition(condition: str, state: Any, patient: Any, day: int) -> bool:
    """Evaluate a risk factor condition string against current state/patient."""
    try:
        if condition.startswith("age_over_"):
            threshold = int(condition.split("_")[-1])
            return patient.age >= threshold if hasattr(patient, "age") else False
        if condition.startswith("severity_"):
            return False  # simplified
```

to:

```python
def _evaluate_risk_condition(
    condition: str, state: Any, patient: Any, day: int, severity: str,
) -> bool:
    """Evaluate a risk factor condition string against current state/patient."""
    try:
        if condition.startswith("age_over_"):
            threshold = int(condition.split("_")[-1])
            return patient.age >= threshold if hasattr(patient, "age") else False
        if condition == "severity_severe":
            return severity == "severe"
```

(Leave the rest of the function — `renal_function`/`volume_status`/`perfusion_status`/`delirium_susceptibility`/`immobility_days` branches and the trailing `except`/`return False` — unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_clinical_course.py -v`
Expected: all tests in the file PASS, including the 4 new ones and the pre-existing `TestComplications`/`TestSelectArchetype`/`TestGetDailyDirective`/`TestInterpolation` tests (unaffected, since `severity` defaults to `"moderate"` and none of their fixture complications use a `severity_`-prefixed condition).

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/clinical_course/engine.py tests/unit/test_clinical_course.py
git commit -m "fix(clinical_course): wire severity into severity_severe risk-factor condition

_evaluate_risk_condition had an explicit '# simplified' stub that made every
severity_severe-gated complication risk factor a permanent no-op, for every
disease. Threads the real severity string through evaluate_complications so
the (only, grep-verified) severity_severe condition can actually match."
```

---

### Task 2: Remove the fragile `severity_str` re-derivation in `_run_daily_loop`, use the real `severity` parameter

**Files:**
- Modify: `clinosim/simulator/inpatient.py:590-596, 625-627, 1012, 1032-1036`
- Test: `tests/unit/test_encounter_archetype_severity.py`

**Interfaces:**
- Consumes: `evaluate_complications(..., severity=...)` from Task 1.
- Produces: `_run_daily_loop`'s `severity: str` parameter (already exists, `inpatient.py:568`) is now the single source of truth for severity within the function — `severity_str` no longer exists. `evaluate_complications` is now called with `severity=severity` at `inpatient.py:1012`.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_encounter_archetype_severity.py` (append at the end of the file):

```python
def test_run_daily_loop_passes_real_severity_to_evaluate_complications(monkeypatch):
    """Before this fix, _run_daily_loop ignored its own accurate `severity`
    parameter and re-derived a separate, less-accurate `severity_str` via
    target_los-mean matching, which is what actually reached
    evaluate_complications. This pins that the real, forced severity is what
    gets passed."""
    from clinosim.simulator import inpatient as inpatient_mod

    captured: dict = {}
    original = inpatient_mod.evaluate_complications

    def spy(*args, **kwargs):
        captured["kwargs"] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(inpatient_mod, "evaluate_complications", spy)

    scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=1, severity="severe")
    config = SimulatorConfig(random_seed=42, country="US")
    run_forced(scenario, config)

    assert captured, "evaluate_complications was never called (check target_los >= 2 and complications are non-empty for bacterial_pneumonia/severe/US)"
    assert captured["kwargs"].get("severity") == "severe"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_encounter_archetype_severity.py -v -k test_run_daily_loop_passes_real_severity`
Expected: FAIL — either `AssertionError: evaluate_complications was never called` is NOT the failure (it should be called, since bacterial_pneumonia/severe/US has complications and target_los >= 5 days), so the actual expected failure is `assert captured["kwargs"].get("severity") == "severe"` failing because `captured["kwargs"]` is `{}` (the current call site passes no keyword arguments at all).

- [ ] **Step 3: Implement the fix**

In `clinosim/simulator/inpatient.py`, delete the `severity_str` re-derivation block:

```python
    # Determine severity string for natural recovery scaling
    severity_str = "moderate"  # default
    for s in ("severe", "moderate", "mild"):
        los_data = (protocol.target_los.get(country_key) or {}).get(s)
        if los_data and abs(target_los - los_data.get("mean", 14)) < 5:
            severity_str = s
            break

    prev_diet = ""  # last diet ordered for this patient; threaded through the day loop
```

to just:

```python
    prev_diet = ""  # last diet ordered for this patient; threaded through the day loop
```

Replace the `natural_recovery_directive` call's use of `severity_str`:

```python
        # Phase 2: Natural recovery (small baseline healing)
        nat_directive = natural_recovery_directive(
            day, disease_id, severity_str, patient.physiological_profile,
        )
```

with:

```python
        # Phase 2: Natural recovery (small baseline healing)
        nat_directive = natural_recovery_directive(
            day, disease_id, severity, patient.physiological_profile,
        )
```

Update the `evaluate_complications` call site to pass `severity`:

```python
            triggered = evaluate_complications(day, state, patient, comp_list, active_complications, rng)
```

to:

```python
            triggered = evaluate_complications(
                day, state, patient, comp_list, active_complications, rng, severity=severity,
            )
```

And replace the remaining use of `severity_str` (in the mortality check) with `severity`:

```python
        if _evaluate_mortality(
            state, patient, severity=severity_str, day=day, rng=rng,
            disease_mortality_rate=benchmark_mortality,
            target_los=target_los,
        ):
```

to:

```python
        if _evaluate_mortality(
            state, patient, severity=severity, day=day, rng=rng,
            disease_mortality_rate=benchmark_mortality,
            target_los=target_los,
        ):
```

(This third call site was not mentioned in the design spec's "one use site" description — grep confirmed during planning that `severity_str` is actually used twice, not once. Both must be updated or `severity_str` cannot be fully removed. This does not change the design's intent: use the real `severity` everywhere the fragile `severity_str` was previously (mis)used.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_encounter_archetype_severity.py -v`
Expected: all tests in the file PASS (the new test plus the 4 pre-existing ones, which are about archetype/severity persistence on `Encounter` and are unaffected by this internal change).

- [ ] **Step 5: Run the full clinical_course + inpatient-adjacent unit tests**

Run: `pytest tests/unit/test_clinical_course.py tests/unit/test_encounter_archetype_severity.py tests/unit/test_diagnosis_feedback.py tests/unit/test_inpatient_avpu.py -v`
Expected: all PASS. (`test_diagnosis_feedback.py` calls `natural_recovery_directive` directly with literal severity strings and is unaffected; `test_inpatient_avpu.py` tests an unrelated helper in the same file.)

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/inpatient.py tests/unit/test_encounter_archetype_severity.py
git commit -m "fix(clinical_course): stop re-deriving severity_str, use the real severity param

_run_daily_loop already received an accurate severity parameter from its
caller, but ignored it in favor of re-deriving a separate, less-accurate
severity_str via fragile target_los-mean matching (adjacent severity tiers'
target_los ranges can overlap). Deletes the re-derivation and threads the
real severity through natural_recovery_directive, evaluate_complications,
and _evaluate_mortality."
```

---

### Task 3: Wire `course_archetypes` into the `select_archetype` call in `_simulate_patient`

**Files:**
- Modify: `clinosim/simulator/inpatient.py:129`
- Test: `tests/unit/test_encounter_archetype_severity.py`

**Interfaces:**
- Consumes: nothing from Tasks 1-2 (fully independent fix).
- Produces: `_simulate_patient`'s natural (non-forced) archetype selection now consults `protocol.course_archetypes`, matching the existing pattern already used later in the same function at `get_daily_directive` (`inpatient.py:601-604`).

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_encounter_archetype_severity.py`:

```python
def test_select_archetype_receives_disease_course_archetypes(monkeypatch):
    """Before this fix, _simulate_patient's natural (non-forced) archetype
    draw called select_archetype() without protocol_archetypes, so every
    disease used the generic _FALLBACK_PROBABILITIES table regardless of its
    own YAML-authored course_archetypes. A sibling call site 470 lines later
    (get_daily_directive) already passed this correctly."""
    from clinosim.simulator import inpatient as inpatient_mod
    from clinosim.modules.disease.protocol import load_disease_protocol

    captured: dict = {}
    original = inpatient_mod.select_archetype

    def spy(*args, **kwargs):
        captured["kwargs"] = kwargs
        return original(*args, **kwargs)

    monkeypatch.setattr(inpatient_mod, "select_archetype", spy)

    scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=1, severity="moderate")
    config = SimulatorConfig(random_seed=42, country="US")
    run_forced(scenario, config)

    protocol = load_disease_protocol("bacterial_pneumonia")
    assert captured.get("kwargs", {}).get("protocol_archetypes") == protocol.course_archetypes
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_encounter_archetype_severity.py -v -k test_select_archetype_receives_disease_course_archetypes`
Expected: FAIL with `assert None == {...}` (or similar) — `captured["kwargs"]` is `{}` today because the call is fully positional.

- [ ] **Step 3: Implement the fix**

In `clinosim/simulator/inpatient.py`, change:

```python
    if forced_archetype:
        archetype = forced_archetype
    else:
        archetype = select_archetype(severity, patient.physiological_profile, rng)
```

to:

```python
    if forced_archetype:
        archetype = forced_archetype
    else:
        archetype = select_archetype(
            severity, patient.physiological_profile, rng,
            protocol_archetypes=protocol.course_archetypes or None,
        )
```

(Mirrors the existing `protocol_archetypes=protocol.course_archetypes or None` pattern at `inpatient.py:603`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_encounter_archetype_severity.py -v`
Expected: all tests PASS, including this new one and the 5 from Task 2/pre-existing.

- [ ] **Step 5: Commit**

```bash
git add clinosim/simulator/inpatient.py tests/unit/test_encounter_archetype_severity.py
git commit -m "fix(clinical_course): wire course_archetypes into natural archetype selection

select_archetype() was called without protocol_archetypes at the one call
site that performs natural (non-forced) archetype sampling, so every
disease used the generic fallback distribution instead of its own YAML.
A sibling call site (get_daily_directive) already passed this correctly;
this fix applies the same pattern. Confirmed via git history this was a
long-standing oversight predating the simulator.py -> package split, not
an intentional omission."
```

---

### Task 4: Full verification — suites, golden/regression fixtures, real-cohort spot check

**Files:**
- No source changes (verification only), unless golden/regression fixtures need regenerating (see below).

**Interfaces:**
- Consumes: the completed Tasks 1-3.
- Produces: a verified, green branch ready for the TODO.md wrap-up in Task 5.

- [ ] **Step 1: Run the full unit suite**

Run: `pytest -m unit -q`
Expected: all PASS, 0 failures. If anything outside `test_clinical_course.py`/`test_encounter_archetype_severity.py` fails, investigate before proceeding — do not assume it's unrelated.

- [ ] **Step 2: Run the full integration suite**

Run: `pytest -m integration -q`
Expected: all PASS (this suite is slower, budget ~10-12 minutes; do not edit any files while it runs in the background — see this project's own convention about background-verification contamination).

- [ ] **Step 3: Check whether golden/regression fixtures drift**

Run: `pytest -m regression -q`
Expected: this may FAIL now, since Fix A/B are real, intended output-changing behavior changes (course archetype distribution shift for the 21 diseases with `course_archetypes`; complication rates for `severity_severe`-gated complications). A failure here is expected and does NOT mean the fix is wrong — it means goldens need regenerating (see next step). If it passes unchanged, double check that at least one of the fixed diseases (e.g. `bacterial_pneumonia`) is actually exercised by a golden/regression fixture and uses natural (non-forced) archetype selection or a `severity_severe` risk factor — if none do, the regression suite simply doesn't exercise this code path and that's fine, move to Step 5.

- [ ] **Step 4: Regenerate goldens if they drifted (AD-66 Rule 1 + Rule 2)**

If Step 3 failed:

Run: `clinosim regenerate-goldens --all`

Then run `git diff` on the regenerated golden files and read it for clinical plausibility (AD-66 Rule 2) — confirm:
(a) only archetype-distribution-driven fields (e.g. `clinical_course_archetype`, trajectory-derived lab/vital values, narrative text referencing the course) and complication-related fields (e.g. `complications_occurred`, complication-driven state deltas) changed;
(b) no unrelated field (e.g. demographics, unrelated disease's data, an unrelated document type) changed — if something unrelated changed, STOP and investigate before proceeding, per this project's stale-regression-suspicion rule (AD-66 Rule 2).

Do not commit yet — bundle the golden diff into Task 5's final commit alongside the TODO.md entries, per AD-66 Rule 1 ("YAML/logic change + golden regen in the same commit" — here the "YAML change" is the code fix, same principle applies).

- [ ] **Step 5: Real-cohort spot check**

Generate a small cohort and confirm both fixes manifest in real output:

```bash
mkdir -p /tmp/clinical_course_fix_check
python -m clinosim.simulator.cli generate --population 200 --country US --seed 42 --output /tmp/clinical_course_fix_check/us200
```

Then inspect the structural CIF for `bacterial_pneumonia` (or another disease with a distinctive `course_archetypes` skew) encounters:

```bash
grep -l '"disease_id": "bacterial_pneumonia"' /tmp/clinical_course_fix_check/us200/cif/structural/patients/*.json | \
  xargs grep -o '"clinical_course_archetype": "[a-z_]*"' | sort | uniq -c
```

Expected: a visible distribution across the archetype names defined in `bacterial_pneumonia.yaml`'s `course_archetypes` (not just the 6 fallback names in some other unrelated proportion — though note bacterial_pneumonia's `smooth_recovery: 0.55` happens to match the fallback's 0.55, so for a clearer signal also check a disease whose `course_archetypes` differ more sharply from `_FALLBACK_PROBABILITIES`, e.g. one with `treatment_resistant` or `gradual_deterioration` weighted well above the fallback's 8%/5%).

Then confirm `severity_severe`-gated complications fire at all for a severe-tier encounter of a disease that authors this risk factor (grep the disease YAMLs for `severity_severe` to pick one, e.g. via `grep -l 'severity_severe' clinosim/modules/disease/reference_data/*.yaml`), by grepping generated `complications_occurred` in that disease's structural CIF for a nonzero count among severe-severity encounters. If the 200-patient cohort happens to produce zero severe-tier encounters of that specific disease, increase `--population` or note this as expected small-sample variance — the goal is a sanity check, not a statistical proof.

- [ ] **Step 6: Clean up the spot-check output**

```bash
rm -rf /tmp/clinical_course_fix_check
```

---

### Task 5: TODO.md formal entries for deferred scope + final wrap-up

**Files:**
- Modify: `TODO.md` (append new dated section)
- Modify: golden/regression fixture files (if Task 4 Step 4 produced a diff — commit them here)

**Interfaces:**
- Consumes: the review findings already documented in `docs/superpowers/specs/2026-07-05-clinical-course-severity-archetype-wiring-design.md`'s "Explicitly out of scope" section.
- Produces: nothing consumed by later tasks — this is the final task.

- [ ] **Step 1: Add a new dated TODO.md section**

Append to `TODO.md` (find the end of the file or the most recent dated deferred-items section and add after it — match the existing `### <topic>` heading style used elsewhere in the file):

```markdown
## clinical_course severity/archetype wiring fix — deferred scope (2026-07-05)

Full context: `docs/superpowers/specs/2026-07-05-clinical-course-severity-archetype-wiring-design.md`.
Comprehensive multi-agent code review + brainstorming session found a much
larger structural issue while fixing two concrete bugs (course_archetypes
wiring, severity_severe stub) — deliberately deferred per scope discipline.

### Two disconnected severity systems: disease YAML `severity.distribution`/`modifiers` vs locale `severity_beta`

`clinosim/modules/disease/protocol.py`'s `DiseaseProtocol` has no
`model_config = ConfigDict(extra="forbid")`, so the `severity:` block's
`distribution`/`modifiers` sub-keys (present in all 30 disease YAMLs, citing
real clinical literature — TIMI score, ACC/AHA, Tokyo Guidelines, JROAD, etc.)
are silently discarded at load time and never read by any Python code
(grep-verified: zero references to `protocol.severity`, `moderate_multiplier`,
`severe_multiplier`, `mild_multiplier` anywhere). The severity actually used
in simulation comes from an unrelated `severity_beta` 2-parameter Beta
distribution in `clinosim/locale/{us,jp}/demographics.yaml`, which is
comorbidity-blind. Options: (a) wire disease YAML's `severity.distribution` +
`modifiers` into the sampling path, replacing or supplementing
`severity_beta` (a real architecture change touching `population/engine.py`
and `simulator/inpatient.py`); (b) formally retire the disease-YAML
`severity:` block as non-machine-readable documentation (delete or clearly
annotate it, decide whether to keep the literature citations as comments);
(c) some hybrid (e.g. `severity.modifiers` becomes a small, well-scoped
comorbidity adjustment to the existing `severity_beta` draw, while
`distribution` stays descriptive-only). This is a genuine design decision,
not a mechanical fix — needs its own brainstorming session.

### `archetype_modifiers` YAML block is dead (28/30 disease YAMLs)

Meant to shift `course_archetypes` probabilities based on patient conditions
(e.g. `age_over_75`, `heart_failure`, `valvular_heart_disease`) — but
`select_archetype` (`clinosim/modules/clinical_course/engine.py:82-97`) has
its own separate, hardcoded severity/profile modifier logic instead of
reading this YAML block at all. Same missing-`extra="forbid"` root cause as
above. Options: wire it in (would need to decide how it composes with the
existing hardcoded modifiers — replace, or apply both?), or delete it from
the 30 YAMLs as abandoned/aspirational content.

### Smaller orphaned/duplicated disease-YAML top-level keys

Also silently dropped due to the missing `extra="forbid"` guard:
`differential_diagnosis` (5 files — `asthma_exacerbation`,
`deep_vein_thrombosis`, `hemorrhagic_stroke`, `influenza`,
`vertebral_compression_fracture` — duplicate the live nested
`diagnostic.differential`, dead top-level copy, active dual-maintenance
drift risk since nothing keeps the two in sync); `diagnostic_difficulty`
(top-level copy dead, only `diagnostic.diagnostic_difficulty` nested inside
the `diagnostic:` dict is read, at `inpatient.py:613`); `rehabilitation` (7
trauma/fracture files); `precipitants` (DKA); `prerequisite` (asthma); and a
fully vestigial `readmission: dict = {}` schema field with zero YAML usage
and zero Python readers. Each needs its own small decision (wire vs delete)
before `extra="forbid"` can be turned on safely.

### `model_config = ConfigDict(extra="forbid")` rollout blocked on the above

Cannot be added to `DiseaseProtocol` (`clinosim/modules/disease/protocol.py`)
until every orphaned key above is resolved (wired or deleted from all 30
YAMLs), or every existing disease YAML will fail to load. This is the actual
fix that would have caught all of the above at author time — worth
prioritizing once the per-key decisions are made.

### 9 diseases with no `course_archetypes` block

`heart_failure_exacerbation` plus 8 trauma/fracture diseases
(`crush_injury_hand`, `electrical_injury`, `fall_from_height`, `hip_fracture`,
`industrial_burn_severe`, `subdural_hematoma`, `traffic_accident_severe`,
`wrist_fracture_surgical`) have no `course_archetypes` block, so they
silently use the generic `_FALLBACK_PROBABILITIES`/`_FALLBACK_TRAJECTORIES`.
Plausibly acceptable for trauma (generic post-op recovery shape); a real gap
for `heart_failure_exacerbation`, which has a well-known diuresis-driven
recovery curve that isn't modeled. Needs per-disease YAML authoring, not a
code change.
```

- [ ] **Step 2: Stage and commit the TODO.md entry + any regenerated goldens**

```bash
git add TODO.md
# If Task 4 Step 4 regenerated golden/regression fixtures, add those specific
# fixture file paths here too (they will have been printed by `git status`
# after `clinosim regenerate-goldens --all`).
git commit -m "docs: file deferred severity-system/orphaned-YAML-key scope to TODO.md

Per scope discipline — the archetype-wiring and severity_severe fixes
surfaced a larger, genuine architecture question (two disconnected
severity systems, several orphaned disease-YAML keys silently dropped by
DiseaseProtocol's missing extra=\"forbid\" guard) that needs its own
brainstorming session rather than expanding this PR's scope."
```

- [ ] **Step 3: Final full-suite confirmation**

Run: `pytest -m unit -q && pytest -m integration -q`
Expected: both green. This is the final gate before considering the branch ready to push/PR (per this project's standard workflow — do not push without explicit user confirmation, per the session's operating norms).

---

## Self-review notes (for whoever executes this plan)

- Task 1 and Task 2 both touch `evaluate_complications`'s call semantics but are split because Task 1 is a pure, fast, RNG-light unit change fully contained in `clinical_course/engine.py`, while Task 2 requires the heavier `run_forced`-based integration-style test in `inpatient.py`'s territory — each has its own clean test gate.
- Task 3 is fully independent of Tasks 1-2 (different call site, different bug) and could technically run first — kept last among the "fix" tasks only because Fix B (Tasks 1-2) was discovered to have an extra undocumented use site (`_evaluate_mortality`) during planning, which was worth flagging prominently before Task 3's simpler, single-line change.
- All three fixes reuse `bacterial_pneumonia` as the test disease throughout (already proven to work with `run_forced` in the pre-existing `test_encounter_archetype_severity.py`), to avoid introducing risk from an unproven disease/`run_forced` combination.
- `evaluate_complications`'s new `severity` parameter defaults to `"moderate"` specifically so the 3 pre-existing calls in `tests/unit/test_clinical_course.py` (which don't pass it) keep passing without modification — verified by direct grep that these are the only other call sites.
