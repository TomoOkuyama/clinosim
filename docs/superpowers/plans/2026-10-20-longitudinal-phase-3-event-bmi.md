# Longitudinal Phase 3 — Event Pattern + DM Complication Onset + BMI Drift AR(1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the third longitudinal pattern (event — gated one-shot ICD onset) and the BMI drift AR(1) attribute, closing the Phase 3 architecture in the longitudinal state-evolution subsystem. DM complication onset (E11.21 nephropathy, E11.311 retinopathy, E11.42 neuropathy) becomes rate-modulated by the HbA1c AR(1) latent landed in Phase 1; adult BMI gains per-year AR(1) drift so a BMI 32 person at year 0 is not frozen at 32 for 5 years.

**Architecture:** Add `EventSpec` + `step` to `clinosim.modules.longitudinal.patterns.event`, register in `PATTERN_REGISTRY` + loader `_IMPLEMENTED_PATTERNS`, add an `elif spec.pattern == "event"` branch in engine `_apply_pattern` that mutates `snapshot.new_complications` and also appends the fired ICD to `person.chronic_conditions`. BMI reuses the existing AR(1) pattern; one `bmi_drift.yaml` under `locale/shared/longitudinal/anthropometry/` + Layer-1 seed from `PatientProfile.bmi` into `YearSnapshot.continuous["bmi"]`. Treatment escalation + `_annual_chronic_onset` adult-chronic migration are explicitly OUT of scope — deferred to Phase 4 (separate PR) to keep this one reviewable.

**Tech Stack:** Python 3.12, pydantic, numpy, pyyaml.

**Spec:** `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` — §4.2.3 event yaml body, §5.2 pattern-level API, §8 Phase 3 scope, §12 follow-up queue.

## Global Constraints

- `pattern: event` yamls live under `clinosim/locale/shared/longitudinal/event/`. BMI AR(1) yaml lives under `clinosim/locale/shared/longitudinal/anthropometry/`. Loader already rglob-s per Phase 2.
- Event step signature: `step(prev_history: list[YearSnapshot], rng: np.random.Generator, spec: EventSpec, *, context: dict | None = None) -> EventResult`. `EventResult` is a named tuple `(fired: bool, emits_icd: str, med_additions: list[str], med_removals: list[str])`.
- `one_shot: true` events check whether `emits_icd` is already in `person.chronic_conditions` OR already in any prior `snapshot.new_complications` list — if yes, do not re-fire.
- Rate modifiers apply multiplicatively; final rate clamps to `[0.0, 1.0]`.
- Deterministic RNG salt: `aging_sub_seed(person_id, year, f"longitudinal:{attribute_id}")` (same convention as Phase 1 + Phase 2).
- Byte-identity across the migration is NOT required (spec §2.3 non-goal). DM patients with HbA1c > 9.0 will see new E11.2x / E11.3x / E11.4x complications appear; every adult person's BMI will drift per year.
- `reproduce.sh` same-seed-twice contract stays as CI gate.

## Review Focus

The five input classes most likely to bite a person using this software that the task tests do not naturally exercise:

1. **`one_shot` idempotence under re-exposure**: a person who already carries the emits_icd must not re-fire the event even if the chronic was added by a non-event path (e.g. the activator stub). Pinned in Task 1.
2. **Rate modifier referencing a missing latent**: a yaml declares `when: {attribute: hba1c, operator: ">", value: 9.0}` for a non-DM person whose `continuous["hba1c"]` is empty — the modifier must evaluate as "trigger absent" (no multiplier contribution), not raise. Pinned in Task 1.
3. **Clinical scope prefix overlap**: a person with `E11.21` (nephropathy, from a previous year's event fire) still satisfies `requires_chronic_codes: ["E11"]` — the complication yaml's `one_shot` guard must prevent re-firing nephropathy on itself. Pinned in Task 2.
4. **BMI drift bound**: AR(1) drift must stay inside the physiologic range `[13.0, 70.0]` — a 50-year sim must not drift a BMI 22 person to BMI 2 or BMI 150. Pinned in Task 5.
5. **BMI year-0 continuity**: `state_at(person, sim_start_year).continuous["bmi"]` must equal `PatientProfile.bmi` at sim start — the initial seed cannot resample from the AR(1) initial distribution (which would break Layer-1 consistency). Pinned in Task 5.

---

## File Structure

**Create:**
- `clinosim/modules/longitudinal/patterns/event.py` — `EventSpec` + `step` + `EventResult`.
- `clinosim/locale/shared/longitudinal/event/dm_nephropathy_e11_21.yaml` — E11.21 complication yaml.
- `clinosim/locale/shared/longitudinal/event/dm_retinopathy_e11_311.yaml` — E11.311 complication yaml.
- `clinosim/locale/shared/longitudinal/event/dm_neuropathy_e11_42.yaml` — E11.42 complication yaml.
- `clinosim/locale/shared/longitudinal/anthropometry/bmi_drift.yaml` — AR(1) BMI drift yaml.
- `tests/modules/longitudinal/test_event_step.py` — pattern math.
- `tests/modules/longitudinal/test_engine_event_dispatch.py` — engine wiring + chronic_conditions mutation + one_shot gate.
- `tests/modules/longitudinal/test_bmi_drift_bounds.py` — physiologic clamp.
- `tests/modules/longitudinal/test_bmi_initial_seed.py` — Layer-1 continuity.
- `tests/integration/test_dm_complication_onset_in_cif.py` — p=100 DM 5y cohort complication rate correlation with HbA1c.
- `tests/integration/test_bmi_drift_in_cif.py` — p=100 adult 5y BMI cohort variance.

**Modify:**
- `clinosim/modules/longitudinal/patterns/__init__.py` — register `event` in `PATTERN_REGISTRY`.
- `clinosim/modules/longitudinal/loader.py` — add `event` to `_IMPLEMENTED_PATTERNS`; add `_build_event_body` dispatch; relax `AttributeSpec.body` Union to include `EventSpec`.
- `clinosim/modules/longitudinal/engine.py` — extend `_apply_pattern` to dispatch `event`; when fired, append emits_icd to `snapshot.new_complications` AND to `person.chronic_conditions` (idempotent via `one_shot` gate + set-check).
- `clinosim/modules/population/engine.py` — `initial_snapshot` call site writes `snapshot.continuous["bmi"] = person.bmi` for adults as a Phase 3 bootstrap (OR the yaml's `initial_distribution` handles it — see Task 5 Ruling).
- `CHANGELOG.md` — Unreleased Added + Changed entries for Phase 3.

---

## Task 1: Event pattern math (EventSpec + step + EventResult)

**Files:**
- Create: `clinosim/modules/longitudinal/patterns/event.py`
- Test: `tests/modules/longitudinal/test_event_step.py`

**Interfaces:**
- Produces: `EventSpec` pydantic model (`event_name: str`, `emits_icd: str`, `base_annual_rate: float`, `rate_modifiers: list[dict]`, `one_shot: bool = True`); `EventResult` NamedTuple `(fired: bool, emits_icd: str, med_additions: list[str], med_removals: list[str])`; `step(person_chronic: list[str], prev_history: list[YearSnapshot], rng, spec, *, context: dict) -> EventResult`.

- [ ] **Step 1: Write failing tests**

```python
# tests/modules/longitudinal/test_event_step.py
import numpy as np
from clinosim.modules.longitudinal.patterns.event import EventSpec, step

def test_step_fires_at_base_rate():
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    result = step([], [], rng, spec, context={})
    assert result.fired
    assert result.emits_icd == "E11.21"

def test_step_zero_rate_never_fires():
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=0.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    for _ in range(100):
        assert not step([], [], rng, spec, context={}).fired

def test_step_one_shot_guard_against_chronic():
    """Review Focus #1 + #3: if emits_icd already in person_chronic,
    event never re-fires even at p=1.0 base rate."""
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    result = step(["E11.21"], [], rng, spec, context={})
    assert not result.fired

def test_step_one_shot_guard_against_prior_new_complications():
    from clinosim.modules.longitudinal.snapshot import YearSnapshot
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, new_complications=["E11.21"])]
    result = step([], prior, rng, spec, context={})
    assert not result.fired

def test_step_rate_modifier_multiplies():
    """A positive hba1c modifier triples the rate."""
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=0.1,
                     rate_modifiers=[{"when": {"attribute": "hba1c", "operator": ">", "value": 9.0},
                                       "factor": 3.0}],
                     one_shot=True)
    hits = 0
    for seed in range(2000):
        rng = np.random.default_rng(seed)
        r = step([], [], rng, spec, context={"continuous": {"hba1c": 10.0}})
        if r.fired:
            hits += 1
    rate = hits / 2000
    assert 0.26 < rate < 0.34, f"3.0 * 0.1 = 0.3 expected, got {rate:.3f}"

def test_step_rate_modifier_absent_latent_ignored():
    """Review Focus #2: when the modifier references hba1c but context
    has no continuous["hba1c"] (non-DM person), the modifier contributes
    no multiplier — base rate applies."""
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=0.1,
                     rate_modifiers=[{"when": {"attribute": "hba1c", "operator": ">", "value": 9.0},
                                       "factor": 3.0}],
                     one_shot=True)
    hits = 0
    for seed in range(2000):
        rng = np.random.default_rng(seed)
        r = step([], [], rng, spec, context={"continuous": {}})
        if r.fired:
            hits += 1
    rate = hits / 2000
    assert 0.08 < rate < 0.12, f"base 0.1 expected under absent-latent, got {rate:.3f}"

def test_step_rate_clamp_to_one():
    """Compounded modifiers that push rate past 1.0 clamp at 1.0."""
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=0.5,
                     rate_modifiers=[{"when": {"attribute": "hba1c", "operator": ">", "value": 9.0},
                                       "factor": 3.0}],
                     one_shot=True)
    rng = np.random.default_rng(0)
    for _ in range(50):
        r = step([], [], rng, spec, context={"continuous": {"hba1c": 10.0}})
        assert r.fired
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_event_step.py -v`
Expected: FAIL with "No module named 'clinosim.modules.longitudinal.patterns.event'"

- [ ] **Step 3: Implement `event.py`**

Define `EventResult` as `NamedTuple("EventResult", fired=bool, emits_icd=str, med_additions=list[str], med_removals=list[str])`. `EventSpec` is a pydantic model with the fields above (`rate_modifiers: list[dict]` for forward-compat; typed modifier model is Phase 4). `step()` logic:

1. If `one_shot` and (`emits_icd` in `person_chronic` OR any prior snapshot's `new_complications` contains `emits_icd`): return `EventResult(fired=False, ...)`.
2. Start `rate = base_annual_rate`.
3. For each modifier: evaluate `when.attribute` against `context["continuous"]` (or against `person_chronic` if `when.chronic_code` — Phase 3 ships only `attribute` triggers). Missing attribute in context → modifier is a no-op (not an error, not a 0-multiplier). If matched, multiply `rate` by `factor`.
4. Clamp `rate = min(1.0, max(0.0, rate))`.
5. Draw `u = rng.random()`; fire iff `u < rate`.
6. Returns `EventResult(fired=True_or_False, emits_icd=spec.emits_icd, med_additions=[], med_removals=[])` — med lists are empty in Phase 3 (treatment escalation lands in Phase 4).

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_event_step.py -v`
Expected: 7/7 pass

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/event.py tests/modules/longitudinal/test_event_step.py
git commit -s -m "feat(longitudinal): add event pattern math (EventSpec + step + EventResult)"
```

---

## Task 2: Register `event` in PATTERN_REGISTRY + loader + engine dispatch

**Files:**
- Modify: `clinosim/modules/longitudinal/patterns/__init__.py`, `loader.py`, `engine.py`
- Test: `tests/modules/longitudinal/test_engine_event_dispatch.py`

**Interfaces:**
- Consumes: `EventSpec` + `step` + `EventResult` from Task 1.
- Produces: `_apply_pattern` writes `snapshot.new_complications.append(emits_icd)` when the event fires AND appends `emits_icd` to `person.chronic_conditions` (if not already present). Caller supplies `context` dict populated with the just-filled `snapshot.continuous` so modifiers see the current year's AR(1) latents.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_engine_event_dispatch.py
# A person with E11 chronic + an hba1c=10.0 snapshot at year Y, running
# advance_one_year with an event yaml that emits E11.21 at rate 1.0,
# must land E11.21 on both snapshot.new_complications AND
# person.chronic_conditions. A second advance in year Y+1 must NOT
# re-fire E11.21 (one_shot gate).
```

Fixture: monkeypatch `_LONGITUDINAL_DIR` with one yaml `test_event.yaml` (event, emits E11.21, base_rate 1.0, one_shot). Create person with `chronic_conditions=["E11.9"]` and seed a prior-year snapshot carrying `continuous={"hba1c": 10.0}`. Call `advance_one_year(person, year=2025, rng)`. Assert `snap.new_complications == ["E11.21"]` and `"E11.21" in person.chronic_conditions`. Call again at year=2026 — assert `snap.new_complications == []` and chronic_conditions still has exactly one `E11.21`.

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_engine_event_dispatch.py -v`
Expected: FAIL with `NotImplementedError: pattern 'event' not implemented in Phase 2`

- [ ] **Step 3: Register event in registry + loader + engine**

- In `patterns/__init__.py`, add `event` entry to `PATTERN_REGISTRY` with `"spec": EventSpec`, `"step": event.step`, and no `initial` key (events don't have an initial draw — add `None` or a no-op).
- In `loader.py`, add `event` to `_IMPLEMENTED_PATTERNS`; relax `AttributeSpec.body: AR1Spec | MarkovSpec | EventSpec`; implement `_build_event_body(body_dict)` returning `(EventSpec(...), aux)`.
- In `engine.py`, extend `_apply_pattern`:

```python
elif spec.pattern == "event":
    context = {"continuous": dict(snapshot.continuous)}  # same-year AR1 reads
    result = handler["step"](
        person.chronic_conditions,
        person.longitudinal_history[:-1] if person.longitudinal_history else [],
        rng,
        spec.body,
        context=context,
    )
    if result.fired:
        snapshot.new_complications.append(result.emits_icd)
        if result.emits_icd not in person.chronic_conditions:
            person.chronic_conditions.append(result.emits_icd)
        for drug in result.med_additions:
            snapshot.med_additions.append(drug)
        for drug in result.med_removals:
            snapshot.med_removals.append(drug)
```

The `prev_snapshot` argument becomes irrelevant for events (events read the current-year snapshot being built, not the prior year); the dispatch handler-selection path should pass `prev_snapshot=prev` but inside the `event` branch we read `snapshot` + `person.longitudinal_history[:-1]` (the just-appended partial snapshot is NOT in `longitudinal_history` yet — the engine appends after `_apply_pattern` returns). The `[:-1]` guard protects against a dispatch order where the engine has already appended, but Phase 3 appends after.

- [ ] **Step 4: Verify test passes**

Run: `pytest tests/modules/longitudinal/test_engine_event_dispatch.py -v`
Expected: 1/1 pass

- [ ] **Step 5: Full regression check**

Run: `pytest tests/modules/longitudinal/`
Expected: all green (Phase 1 + Phase 2 + Phase 3 events)

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/__init__.py clinosim/modules/longitudinal/loader.py clinosim/modules/longitudinal/engine.py tests/modules/longitudinal/test_engine_event_dispatch.py
git commit -s -m "feat(longitudinal): register event pattern + wire new_complications and chronic_conditions mutation"
```

---

## Task 3: DM complication onset yamls (E11.21, E11.311, E11.42)

**Files:**
- Create: 3 yamls under `clinosim/locale/shared/longitudinal/event/`
- Test: extend `tests/modules/longitudinal/test_stage_yamls_load.py` OR add `test_event_yamls_load.py`

**Interfaces:**
- Consumes: `EventSpec` + loader dispatch from Task 2.
- Produces: 3 `AttributeSpec` registered at import time under keys `dm_nephropathy_onset_e11_21`, `dm_retinopathy_onset_e11_311`, `dm_neuropathy_onset_e11_42`.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_event_yamls_load.py
from clinosim.modules.longitudinal.loader import load_attribute_specs

EXPECTED = {
    "dm_nephropathy_onset_e11_21": "E11.21",
    "dm_retinopathy_onset_e11_311": "E11.311",
    "dm_neuropathy_onset_e11_42": "E11.42",
}

def test_dm_complication_event_yamls_load():
    specs = load_attribute_specs()
    for attr_id, icd in EXPECTED.items():
        assert attr_id in specs
        body = specs[attr_id].body
        assert body.emits_icd == icd
        assert body.one_shot is True
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_event_yamls_load.py -v`
Expected: FAIL — 3 missing keys.

- [ ] **Step 3: Author the 3 yamls**

Base rates and modifiers from DM epidemiology:

- **Nephropathy (E11.21)**: Molitch M et al, Diabetes Care 2004;27 Suppl1:S79. Microalbuminuria onset ~2 %/yr base; proteinuria stage ~4 %/yr under uncontrolled DM. Phase 3 uses E11.21 as a single lumped "diabetic nephropathy" onset; base_annual_rate 0.015 (1.5 %/yr) scaled 3.0× for HbA1c > 9.0 and 1.5× for HbA1c > 7.5.
- **Retinopathy (E11.311)**: UKPDS 1998; Klein 2006 Ophthalmology. Cumulative incidence ~2.5 %/yr base; 4-6× under A1c > 9.0. base_annual_rate 0.020, modifier A1c > 9.0 → 4.0×, A1c > 7.5 → 2.0×.
- **Neuropathy (E11.42)**: Dyck 1993 Neurology; Pop-Busui 2017 Diabetes Care. ~2 %/yr base in DM cohorts; A1c > 9.0 doubles rate. base_annual_rate 0.020, modifier A1c > 9.0 → 2.5×.

Yaml skeleton (nephropathy):

```yaml
# clinosim/locale/shared/longitudinal/event/dm_nephropathy_e11_21.yaml
# Diabetic nephropathy onset — event pattern.
# Phase 3 of the longitudinal state-evolution subsystem (Issue #1697).
# Base rate 1.5 %/yr, scaled by HbA1c trajectory latent.
#
# Clinical basis: Molitch ME et al, Diabetes Care 2004;27 Suppl1:S79;
# UKPDS 1998 NEJM:837 nephropathy incidence; Nathan DM et al JAMA 2003.

attribute_id: dm_nephropathy_onset_e11_21
pattern: event
depends_on: [hba1c]
clinical_scope:
  requires_chronic_codes: ["E11", "E10"]
  requires_age_band: [18, 120]

event_name: dm_nephropathy_onset
emits_icd: E11.21
base_annual_rate: 0.015
rate_modifiers:
  - when: {attribute: hba1c, operator: ">", value: 9.0}
    factor: 3.0
  - when: {attribute: hba1c, operator: ">", value: 7.5}
    factor: 1.5
one_shot: true
narrative_label:
  en: "Diabetic nephropathy onset"
  ja: "糖尿病性腎症発症"
source:
  - "Molitch ME et al. Nephropathy in diabetes. Diabetes Care 2004;27 Suppl1:S79."
```

**Ruling (plan author)**: The two overlapping modifiers (`> 9.0` AND `> 7.5`) compound when a patient's A1c crosses both — a patient at A1c 10.0 sees `3.0 * 1.5 = 4.5× base`. This matches the clinical intuition that A1c 10.0 is worse than A1c 7.5. Implementers who find this double-counts in a specific publication's modeling may replace with a single step function in the attribute yaml — ledger it.

Author retinopathy and neuropathy yamls analogously.

- [ ] **Step 4: Verify test passes**

Run: `pytest tests/modules/longitudinal/test_event_yamls_load.py -v`
Expected: 1/1 pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/event/ tests/modules/longitudinal/test_event_yamls_load.py
git commit -s -m "feat(longitudinal): add DM complication onset event yamls (E11.21 / E11.311 / E11.42)"
```

---

## Task 4: Topological ordering — events run AFTER AR1 for the same year

**Files:**
- Modify: `clinosim/modules/longitudinal/engine.py` (confirm topo order gives AR1 attributes before events depending on them)
- Test: `tests/modules/longitudinal/test_event_reads_same_year_ar1.py`

**Interfaces:**
- Consumes: topological sort from Phase 1 loader.
- Produces: ordering guarantee that in `advance_one_year`, `hba1c` AR(1) attribute executes before any event attribute that lists `depends_on: [hba1c]`.

- [ ] **Step 1: Write failing test**

Build a mock loader with `hba1c` (AR1, phi=1.0 sigma=0 target=10.0 — deterministic 10.0 after any step) and `dm_nephropathy` (event, depends_on=[hba1c], modifier triggers at hba1c > 9.0). Advance a DM person with a prior-year `continuous.hba1c=7.0`. Assert nephropathy triggers (because this-year hba1c is 10.0, past the > 9.0 threshold). If events ran BEFORE AR1, the context would still show hba1c=7.0 and the modifier wouldn't trigger.

- [ ] **Step 2: Verify failing OR already green**

Run: `pytest tests/modules/longitudinal/test_event_reads_same_year_ar1.py -v`
Expected: GREEN if topo order already handles it (likely — the loader's topological_order follows depends_on). If GREEN at Step 2, treat the test as a regression pin and skip Step 3; else fix.

- [ ] **Step 3: Fix if needed**

If the test fails, inspect `advance_one_year`'s iteration — ensure the loop reads the just-updated `snapshot.continuous` for the event's `context`, not a stale copy. The dispatch in Task 2 already does `context = {"continuous": dict(snapshot.continuous)}` AT THE TIME the event is dispatched, so topo order wins.

- [ ] **Step 4: Commit**

```bash
git add tests/modules/longitudinal/test_event_reads_same_year_ar1.py
git commit -s -m "test(longitudinal): pin event-reads-same-year-AR1 topo-order contract"
```

---

## Task 5: BMI drift AR(1) yaml + Layer-1 continuity

**Files:**
- Create: `clinosim/locale/shared/longitudinal/anthropometry/bmi_drift.yaml`
- Modify: `clinosim/modules/population/engine.py` — seed BMI into initial snapshot after `initial_snapshot(person, year, rng)` returns, override `snap.continuous["bmi"]` with `person.bmi` for adults.
- Test: `tests/modules/longitudinal/test_bmi_initial_seed.py`, `tests/modules/longitudinal/test_bmi_drift_bounds.py`

**Interfaces:**
- Consumes: AR(1) pattern from Phase 1.
- Produces: `state_at(person, sim_start_year).continuous["bmi"] == person.bmi` (Review Focus #5); AR(1) drift over 50 years stays in `[13.0, 70.0]` (Review Focus #4).

- [ ] **Step 1: Write BMI yaml**

```yaml
# clinosim/locale/shared/longitudinal/anthropometry/bmi_drift.yaml
# Adult BMI drift — AR(1) around the person's Layer-1 BMI anchor.
# Phase 3 of the longitudinal state-evolution subsystem (Issue #1705).
#
# Clinical basis: Framingham longitudinal BMI tracking;
# Rissanen 1991 Int J Obes 15:647 adult weight-change epidemiology.
# phi=0.95 reflects strong year-to-year BMI persistence.
# sigma=0.6 BMI units matches the ~1 kg/yr adult drift SD after age 30.

attribute_id: bmi_drift
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: []
  requires_age_band: [18, 120]

latent_name: bmi
ar1:
  phi: 0.95
  sigma: 0.6
  mean_reversion_target: 24.5
clamp: [13.0, 70.0]
# initial_distribution not used — Layer-1 seeds person.bmi directly
# via population/engine.py after initial_snapshot returns.
initial:
  mu: 3.20   # dummy log(24.5) ≈ 3.20, never consumed under Layer-1 override
  sigma: 0.10
  clamp: [13.0, 70.0]
narrative_label:
  en: "BMI trajectory"
  ja: "BMI 推移"
source:
  - "Rissanen AM et al. Determinants of weight gain and overweight in adult Finns. Int J Obes 1991;15:647."
```

- [ ] **Step 2: Write failing test — Layer-1 continuity**

```python
def test_bmi_initial_seed_matches_layer1_bmi():
    """Review Focus #5: state_at(person, sim_start).continuous["bmi"]
    equals person.bmi exactly."""
    # Build person with bmi=28.4 via population generator; assert state_at matches.
```

- [ ] **Step 3: Wire Layer-1 override in population/engine.py**

After the `initial_snapshot(person, year=base_year, init_rng=_ls_rng)` call, add:

```python
if person.longitudinal_history and person.age >= 18:
    person.longitudinal_history[-1].continuous["bmi"] = float(person.bmi)
```

(Only adults get BMI drift per `requires_age_band: [18, 120]`; pediatric persons grow via the existing growth-chart path and don't participate in BMI drift here.)

- [ ] **Step 4: Verify continuity test passes**

Run: `pytest tests/modules/longitudinal/test_bmi_initial_seed.py -v`
Expected: pass.

- [ ] **Step 5: Write failing test — physiologic clamp**

```python
def test_bmi_drift_stays_in_physiologic_range_over_50_years():
    """Review Focus #4: AR(1) drift under 50 iterations must not escape
    [13.0, 70.0] regardless of seed."""
    # Fixture: adult with bmi=22.0; advance 50 years; assert every snapshot's
    # continuous["bmi"] is within [13.0, 70.0].
```

- [ ] **Step 6: Verify clamp test passes**

The engine's `_apply_pattern` AR1 branch already clamps per spec body — should be GREEN. Pin as regression.

- [ ] **Step 7: Commit**

```bash
git add clinosim/locale/shared/longitudinal/anthropometry/ clinosim/modules/population/engine.py tests/modules/longitudinal/test_bmi_initial_seed.py tests/modules/longitudinal/test_bmi_drift_bounds.py
git commit -s -m "feat(longitudinal): BMI drift AR(1) + Layer-1 continuity seed"
```

---

## Task 6: Integration — DM complication onset rate correlates with HbA1c in CIF

**Files:**
- Create: `tests/integration/test_dm_complication_onset_in_cif.py`

**Interfaces:**
- Consumes: full longitudinal engine + Phase 1 HbA1c + Phase 3 event dispatch + CIF writer.
- Produces: a cohort-level sanity check — DM patients with elevated HbA1c trajectories accumulate more E11.2x / E11.3x / E11.4x codes than DM patients at target.

- [ ] **Step 1: Write failing cohort test**

```python
# p=100 US seed=42 5y. Extract DM patients from CIF JSON. Count
# patients carrying E11.21 / E11.311 / E11.42 after 5 years. Assert
# at least 2 patients have gained a complication the first year's
# CIF did not show (proving mid-sim onset works via event pattern).
```

- [ ] **Step 2: Verify failing on pre-Phase-3 repo**

Expected: zero E11.2x / E11.3x / E11.4x codes exist in any DM patient (events not yet wired). Phase 3 flips it green.

- [ ] **Step 3: Verify test passes with Phase 3 engine wired**

Run: `pytest tests/integration/test_dm_complication_onset_in_cif.py -v`
Expected: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_dm_complication_onset_in_cif.py
git commit -s -m "test(longitudinal): DM complication onset event cohort integration"
```

---

## Task 7: Integration — BMI drift produces per-year variance in CIF

**Files:**
- Create: `tests/integration/test_bmi_drift_in_cif.py`

**Interfaces:**
- Consumes: Phase 3 BMI AR(1) + CIF writer.
- Produces: cohort-level check — a p=100 adult cohort's BMI distribution shifts year-over-year by at least 0.3 SD at the cohort mean level.

- [ ] **Step 1: Write failing cohort test**

Extract per-person BMI from CIF JSON (patient.bmi field) × multiple encounter snapshots. Assert at least 10 patients show BMI variance > 0.3 across their encounter time series.

Note: patient.bmi in CIF is currently frozen at Layer-1 generation. Phase 3's job is to decide whether per-encounter CIF emits a time-varying BMI or whether the CIF schema stays "Layer-1-frozen" with BMI drift living in `longitudinal_history.continuous["bmi"]` only.

**Ruling (plan author)**: Phase 3 does NOT change the `patient.bmi` CIF emit — that stays at Layer-1 for now (schema stability for downstream consumers). Per-encounter time-varying BMI is a Phase 4 consumer-side migration (will touch `metabolic/engine.py` BMI readers). The Phase 3 integration test instead verifies the BMI drift reaches `longitudinal_history` via a different extraction path (e.g. CIF JSON's `longitudinal_history` serialization if present, OR direct engine-side check via a per-person-record query). If `longitudinal_history` is not yet CIF-serialized (deferred from Phase 1 I1), the test falls back to engine-level assertion using `generate_population` + `advance_population` without CIF emit.

- [ ] **Step 2-4: Standard RED → GREEN → commit**

```bash
git commit -s -m "test(longitudinal): BMI drift cohort integration"
```

---

## Task 8: CHANGELOG + reproduce.sh + regression suite

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything from Tasks 1-7.
- Produces: documentation complete; CI gate green.

- [ ] **Step 1: Update CHANGELOG.md Unreleased**

- **Added**: Event pattern + DM complication onset (E11.21, E11.311, E11.42) + BMI drift AR(1).
- **Changed**: Adults' BMI now drifts year-over-year per the AR(1) latent at `longitudinal_history[y].continuous["bmi"]`; `PatientProfile.bmi` CIF emit stays at Layer-1 anchor (Phase 4 may migrate per-encounter readers).

- [ ] **Step 2: Full suite + reproduce.sh**

```bash
pytest -x tests/modules/longitudinal/ tests/unit/ tests/integration/
scripts/reproduce.sh
```

Expected: all green; byte-identical.

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git commit -s -m "docs(changelog): Phase 3 longitudinal event + BMI drift"
```
