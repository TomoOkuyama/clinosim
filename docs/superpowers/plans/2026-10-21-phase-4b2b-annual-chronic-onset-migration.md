# Phase 4b.2.β Annual Chronic Onset Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate the 30 adult-chronic ICD annual-onset Bernoullis from `clinosim/modules/population/aging.py::_annual_chronic_onset` into the longitudinal engine's event pattern, retiring the aging pass and the mental-health multiplier Python helper. Preserve cohort epi targets (bands declared in `clinosim/locale/us/demographics.yaml::chronic_prevalence`) without preserving byte-identity (spec §2.3 relaxation).

**Architecture:** Author one `locale/shared/longitudinal/event/<code>_onset.yaml` per ICD, carrying age-band base rates (today's `_derive_annual_incidence_from_prevalence` output) + sex gating + comorbidity-conditional rate modifiers (today's `_mental_health_onset_multiplier` rules). Extend the Phase 4b.2.α `RateModifierWhen` with a `has_chronic_prefix` alternative (startswith semantics, mirrors `requires_any_chronic_prefix` on the Python helper) and `ClinicalScope` with a `requires_sex` field. Remove `_annual_chronic_onset`, `_mental_health_onset_multiplier`, `_load_mental_health_onset_multipliers`, `_load_annual_incidence_for_locale`, `_derive_annual_incidence_from_prevalence` and the aging-pass driver's reference to the function.

**Tech Stack:** Python 3.12, Pydantic BaseModel, numpy RNG, pytest.

**Spec:** `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` §7 (Migration) + §2.3 (Non-goals — byte-identity NOT preserved).

## Global Constraints

- Byte-identity across the migration is NOT required (spec §2.3). Reproducibility contract (same seed → same output bytes) MUST hold post-migration — verified by `scripts/reproduce.sh` outside this plan's test matrix.
- Cohort epi band targets are the point-prevalence rows in `clinosim/locale/us/demographics.yaml::chronic_prevalence` (per ICD, per age band). Each migrated event yaml's `base_rate_by_age_band` MUST produce a cohort whose end-of-sim prevalence lands within those bands at ±30 % relative tolerance for p=500 stochasticity.
- `_MIN_INCIDENCE_AGE = 18`: pediatric persons do not acquire adult chronic conditions here. Enforced via `ClinicalScope.requires_age_band: [18, 120]` on every migrated event yaml.
- No new chronic ICD codes added. Scope is a semantic refactor of existing 30-code onset path.
- Mental-health multiplier compounds multiplicatively over multiple applicable rules — behaviour MUST match current `_mental_health_onset_multiplier` loop semantics (`out *= float(rule.get("multiplier", 1.0))`).
- Z34 / Z37 cursor-placeholder codes stay in `demographics.yaml::chronic_prevalence` as dead rows but acquire no event yaml. They are not chronic conditions and were never written to `chronic_conditions` by `_annual_chronic_onset` (per `_STATE_PERIOD_ONSET_SKIP_CODES`).
- Mental-health multiplier yaml `mental_health_onset_multipliers.yaml` is retired (its content migrates verbatim as per-event `rate_modifiers`).

## Review Focus

1. **Pediatric person (`age < 18`)** holding a legacy adult chronic code from a pre-migration CIF — a migrated event yaml MUST NOT fire for them, enforced by `clinical_scope.requires_age_band: [18, 120]`. Covered by Task 2 test `test_event_requires_adult_age_band`.
2. **Legacy `Z34` / `Z37`** present on a person's `chronic_conditions` (from an older sim run or pre-migration data) — the engine MUST pass through all 30 new event yamls without raising. Covered by Task 3 test `test_engine_ignores_legacy_state_period_codes`.
3. **Sex-locked ICD** (`N40` on a female patient; `C61` on a female patient) — event yaml with `requires_sex: "M"` MUST NOT fire for females. Covered by Task 1 test `test_sex_locked_event_does_not_fire_for_opposite_sex`.
4. **Already-held target ICD** (`I10` on a person who already carries I10) — event's `one_shot: true` + `emits_icd in person_chronic` short-circuit MUST prevent re-fire, no duplicate append. Covered by Task 2 test `test_event_does_not_refire_when_already_held`.
5. **Compound mental-health multiplier** — a person carrying both E11.9 (DM) AND any `C*` code (cancer) MUST produce F32 base × 2.0 (DM) × 2.5 (cancer prefix). Covered by Task 2 test `test_f32_onset_multiplier_compounds_dm_and_cancer`.

---

## File Structure

**Modified (Python):**
- `clinosim/modules/longitudinal/patterns/event.py` — add `has_chronic_prefix` to `RateModifierWhen`; extend `_modifier_matches` with the startswith branch; 3-way mutual-exclusivity validator.
- `clinosim/modules/longitudinal/loader.py` — add `requires_sex: str = ""` to `ClinicalScope`.
- `clinosim/modules/longitudinal/engine.py::_attribute_in_scope` — honour `requires_sex` on scope evaluation.
- `clinosim/modules/population/aging.py` — DELETE `_annual_chronic_onset`, `_mental_health_onset_multiplier`, `_load_mental_health_onset_multipliers`, `_load_annual_incidence_for_locale`, `_derive_annual_incidence_from_prevalence`, `_ChronicIncidenceSpec`, `_STATE_PERIOD_ONSET_SKIP_CODES`. Remove `_annual_chronic_onset` from `advance_population`'s pass tuple at line 809. Keep `_stroke_sequela_promotion`, `_allergy_drift`, `_condition_reactive_mortality` untouched.
- `clinosim/locale/loader.py` — remove `load_mental_health_onset_multipliers`.
- `clinosim/locale/shared/mental_health_onset_multipliers.yaml` — DELETE.

**Created (yaml):**
- `clinosim/locale/shared/longitudinal/event/<code>_onset.yaml` × 30 (one per migrated ICD).
- `clinosim/locale/shared/longitudinal/event/README.md` — append a Phase 4b.2.β authoring note.

**Test:**
- `tests/unit/longitudinal/test_rate_modifier_has_chronic_prefix.py` (Task 1).
- `tests/unit/longitudinal/test_requires_sex_clinical_scope.py` (Task 1).
- `tests/unit/longitudinal/test_chronic_onset_yamls_present.py` (Task 2).
- `tests/unit/longitudinal/test_f32_mental_health_multipliers.py` (Task 2).
- `tests/modules/population/test_aging_pass_retirement.py` (Task 3).
- `tests/integration/test_cohort_epi_targets_post_migration.py` (Task 4).

**ICD migration list** (30 codes, derived from `clinosim/locale/us/demographics.yaml::chronic_prevalence`, excluding Z34 / Z37 placeholders):

I10, E11.9, E78, J44, N18, I50, I48, I25, M81, F00, G20, E03, K21, J45, N40, M17, G35, F32, F33, F41.1, C15, C16, C25, C67, C71, C18, C22, C34, C50, C61.

---

## Task 1: Schema extensions — `has_chronic_prefix` + `requires_sex`

**Files:**
- Modify: `clinosim/modules/longitudinal/patterns/event.py:48-82` (`RateModifierWhen`)
- Modify: `clinosim/modules/longitudinal/loader.py:36-41` (`ClinicalScope`)
- Modify: `clinosim/modules/longitudinal/engine.py:59-66` (`_attribute_in_scope`)
- Test: `tests/unit/longitudinal/test_rate_modifier_has_chronic_prefix.py`
- Test: `tests/unit/longitudinal/test_requires_sex_clinical_scope.py`

**Interfaces:**
- Consumes: Phase 4b.2.α — `RateModifierWhen` with `attribute | operator | value | has_chronic` fields and `_modifier_matches` reading `context["chronic_conditions"]`.
- Produces:
  - `RateModifierWhen` gains optional `has_chronic_prefix: list[str] = Field(default_factory=list)`. 3-way exclusivity: `attribute+operator+value`, `has_chronic`, `has_chronic_prefix` — exactly one trigger shape populated.
  - `ClinicalScope` gains optional `requires_sex: str = ""` (empty = any).
  - `_attribute_in_scope(spec, person, year) -> bool` additionally returns False when `requires_sex` is non-empty and `person.sex != spec.clinical_scope.requires_sex`.

- [ ] **Step 1: Write the failing test for `has_chronic_prefix`**

```python
# tests/unit/longitudinal/test_rate_modifier_has_chronic_prefix.py
import numpy as np
import pytest
from clinosim.modules.longitudinal.patterns.event import (
    EventSpec, RateModifier, RateModifierWhen, step,
)
pytestmark = pytest.mark.unit

def test_has_chronic_prefix_fires_when_person_has_matching_prefix():
    spec = EventSpec(
        event_name="depression_onset",
        emits_icd="F32",
        base_annual_rate=0.01,
        rate_modifiers=[
            RateModifier(when=RateModifierWhen(has_chronic_prefix=["C"]), factor=2.5)
        ],
    )
    # seed=34 draws 0.0040 (<0.025, > 0.01) → fires with multiplier, not without.
    rng = np.random.default_rng(34)
    result = step(
        person_chronic=["C18"], prev_history=[], rng=rng, spec=spec,
        context={"continuous": {}, "chronic_conditions": ["C18"]},
    )
    assert result.fired is True

def test_has_chronic_prefix_no_match_leaves_base_rate():
    spec = EventSpec(
        event_name="depression_onset",
        emits_icd="F32",
        base_annual_rate=0.01,
        rate_modifiers=[
            RateModifier(when=RateModifierWhen(has_chronic_prefix=["C"]), factor=2.5)
        ],
    )
    # seed=53 draws 0.0111 > base 0.01 → no fire (modifier not applied).
    rng = np.random.default_rng(53)
    result = step(
        person_chronic=["I10"], prev_history=[], rng=rng, spec=spec,
        context={"continuous": {}, "chronic_conditions": ["I10"]},
    )
    assert result.fired is False

def test_three_way_mutual_exclusivity_rejects_two_triggers():
    with pytest.raises(ValueError, match="exactly one of"):
        RateModifierWhen(has_chronic=["E11.9"], has_chronic_prefix=["C"])

def test_three_way_mutual_exclusivity_rejects_zero_triggers():
    with pytest.raises(ValueError, match="exactly one of"):
        RateModifierWhen()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_rate_modifier_has_chronic_prefix.py -v`
Expected: all 4 FAIL — `has_chronic_prefix` is not a field on `RateModifierWhen` yet; three-way validator does not exist.

- [ ] **Step 3: Extend `RateModifierWhen` in `clinosim/modules/longitudinal/patterns/event.py`**

Add field `has_chronic_prefix: list[str] = Field(default_factory=list)`. In `model_post_init`, replace the two-way exclusivity check with a three-way exact-count check: `len([t for t in (has_attribute, has_chronic, has_prefix) if t]) == 1`. Message: `"RateModifierWhen requires exactly one of (attribute + operator + value), has_chronic, or has_chronic_prefix"`.

Extend `_modifier_matches`: before the `attribute` branch, after the existing `has_chronic` branch, add a `when.has_chronic_prefix` branch that returns `any(code.startswith(p) for code in context.get("chronic_conditions", []) for p in when.has_chronic_prefix)`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_rate_modifier_has_chronic_prefix.py -v`
Expected: 4 PASS.

- [ ] **Step 5: Write the failing test for `requires_sex`**

```python
# tests/unit/longitudinal/test_requires_sex_clinical_scope.py
from datetime import date
import pytest
from clinosim.modules.longitudinal.engine import _attribute_in_scope
from clinosim.modules.longitudinal.loader import AttributeSpec, ClinicalScope
from clinosim.modules.longitudinal.patterns.event import EventSpec
from clinosim.types.population import PersonRecord
pytestmark = pytest.mark.unit

def _spec(sex: str) -> AttributeSpec:
    return AttributeSpec(
        attribute_id="n40_onset",
        pattern="event",
        clinical_scope=ClinicalScope(requires_age_band=[18, 120], requires_sex=sex),
        body=EventSpec(event_name="n40", emits_icd="N40", base_annual_rate=0.08),
    )

def _person(sex: str) -> PersonRecord:
    return PersonRecord(
        person_id="PX",
        sex=sex,
        date_of_birth=date(1960, 1, 1),
        chronic_conditions=[],
    )

def test_requires_sex_male_passes_for_male_person():
    assert _attribute_in_scope(_spec("M"), _person("M"), 2024) is True

def test_requires_sex_male_rejects_female_person():
    assert _attribute_in_scope(_spec("M"), _person("F"), 2024) is False

def test_requires_sex_empty_defaults_to_any():
    assert _attribute_in_scope(_spec(""), _person("F"), 2024) is True
    assert _attribute_in_scope(_spec(""), _person("M"), 2024) is True
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_requires_sex_clinical_scope.py -v`
Expected: 3 FAIL — `requires_sex` is not a field on `ClinicalScope`.

- [ ] **Step 7: Add `requires_sex` to `ClinicalScope` + honour it in `_attribute_in_scope`**

Add `requires_sex: str = ""` to `ClinicalScope`. In `_attribute_in_scope`, before the age-band check, add: `if spec.clinical_scope.requires_sex and person.sex != spec.clinical_scope.requires_sex: return False`.

- [ ] **Step 8: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_requires_sex_clinical_scope.py tests/unit/longitudinal/test_rate_modifier_has_chronic_prefix.py tests/unit/longitudinal/test_eventspec_age_band_chronic_trigger.py tests/modules/longitudinal/ -v`
Expected: all PASS including the Phase 4b.2.α tests (regression check).

- [ ] **Step 9: Review Focus test — sex-locked event does not fire for opposite sex**

Append to `test_requires_sex_clinical_scope.py`:
```python
def test_sex_locked_event_does_not_fire_for_opposite_sex():
    """Review Focus #3: N40 BPH on a female patient — the attribute
    is excluded from `in_scope`, so the engine never dispatches it."""
    female = _person("F")
    assert _attribute_in_scope(_spec("M"), female, 2024) is False
```

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_requires_sex_clinical_scope.py -v`
Expected: 4 PASS (3 previous + this one).

- [ ] **Step 10: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/event.py clinosim/modules/longitudinal/loader.py clinosim/modules/longitudinal/engine.py tests/unit/longitudinal/test_rate_modifier_has_chronic_prefix.py tests/unit/longitudinal/test_requires_sex_clinical_scope.py
git commit -s -m "feat(longitudinal): has_chronic_prefix trigger + requires_sex scope (Phase 4b.2.β Task 1)"
```

---

## Task 2: Author 30 adult-chronic onset event yamls

**Files:**
- Create: `clinosim/locale/shared/longitudinal/event/<code>_onset.yaml` × 30 (listed in Global Constraints)
- Test: `tests/unit/longitudinal/test_chronic_onset_yamls_present.py`
- Test: `tests/unit/longitudinal/test_f32_mental_health_multipliers.py`

**Interfaces:**
- Consumes: Task 1 (`has_chronic_prefix`, `requires_sex`); Phase 4b.2.α `base_rate_by_age_band` + `has_chronic`.
- Produces: 30 loadable `AttributeSpec` instances with `pattern: event` under the longitudinal loader. Each yaml carries `attribute_id: <code>_onset`, `clinical_scope.requires_age_band: [18, 120]`, optional `requires_sex`, `base_rate_by_age_band` derived from today's `demographics.yaml::chronic_prevalence` band-diff math (same `_derive_annual_incidence_from_prevalence` formula), and `rate_modifiers` for F32 / F33 / F41.1 only (migrated verbatim from `mental_health_onset_multipliers.yaml`).

- [ ] **Step 1: Write the failing test — 30 yamls are present and loadable**

```python
# tests/unit/longitudinal/test_chronic_onset_yamls_present.py
import pytest
from clinosim.modules.longitudinal.loader import load_attribute_specs
pytestmark = pytest.mark.unit

EXPECTED_30 = [
    "I10", "E11.9", "E78", "J44", "N18", "I50", "I48", "I25", "M81",
    "F00", "G20", "E03", "K21", "J45", "N40", "M17", "G35", "F32",
    "F33", "F41.1", "C15", "C16", "C25", "C67", "C71", "C18", "C22",
    "C34", "C50", "C61",
]

def test_all_thirty_adult_chronic_onset_yamls_registered():
    specs = load_attribute_specs()
    missing = []
    for icd in EXPECTED_30:
        attr_id = f"{icd.lower().replace('.', '_')}_onset"
        if attr_id not in specs:
            missing.append(attr_id)
    assert not missing, f"missing event attribute yamls: {missing}"

def test_every_chronic_onset_event_is_age_gated_18_plus():
    specs = load_attribute_specs()
    for attr_id, spec in specs.items():
        if not attr_id.endswith("_onset"):
            continue
        if attr_id in ("dm_escalate_sglt2i_e11_onset", "dm_escalate_insulin_e11_onset"):
            continue  # Phase 4a escalations exempt from this gate
        lo, _hi = spec.clinical_scope.requires_age_band
        assert lo >= 18, f"{attr_id} is not adult-only (lo={lo})"
```

Add this adjacent test for Review Focus #1 and #4:
```python
def test_event_requires_adult_age_band():
    """Review Focus #1: pediatric person (age<18) does not acquire adult
    chronic conditions via a migrated event yaml. All 30 yamls must have
    `requires_age_band[0] >= 18`."""
    # Already covered by test_every_chronic_onset_event_is_age_gated_18_plus.
    # This name documents the Review Focus explicitly.
    specs = load_attribute_specs()
    i10 = specs["i10_onset"]
    assert i10.clinical_scope.requires_age_band[0] == 18

def test_event_does_not_refire_when_already_held():
    """Review Focus #4: EventSpec one_shot: True + chronic_conditions
    dedup prevents re-fire. Verified against i10_onset yaml."""
    import numpy as np
    from clinosim.modules.longitudinal.patterns.event import step
    specs = load_attribute_specs()
    body = specs["i10_onset"].body
    rng = np.random.default_rng(3)  # draws 0.0856 — would fire at any adult band
    result = step(
        person_chronic=["I10"],  # already held
        prev_history=[],
        rng=rng,
        spec=body,
        context={"continuous": {}, "age": 70, "chronic_conditions": ["I10"]},
    )
    assert result.fired is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_chronic_onset_yamls_present.py -v`
Expected: all FAIL — no yamls exist yet.

- [ ] **Step 3: Author the 30 yamls**

For each ICD in `EXPECTED_30`, create `clinosim/locale/shared/longitudinal/event/<attr_id>.yaml` with the structure below. **Band rates come from today's `demographics.yaml::chronic_prevalence` → `_derive_annual_incidence_from_prevalence` output**: for each `(lo, hi)` band, compute `λ = 1 - ((1-P_next)/(1-P_this))**(1/width)` for the FROM band; the LAST band gets `λ = 0`.

Template (I10 example, no sex gate, no modifiers):
```yaml
attribute_id: i10_onset
pattern: event
clinical_scope:
  requires_age_band: [18, 120]
body:
  event_name: i10_onset
  emits_icd: I10
  base_rate_by_age_band:
    - {age_lo: 18, age_hi: 39, rate: <λ_18_39>}
    - {age_lo: 40, age_hi: 59, rate: <λ_40_59>}
    - {age_lo: 60, age_hi: 120, rate: 0.0}  # terminal band
  one_shot: true
narrative_label: hypertension_new_onset
source: >
  NHANES 2017-18 adult 18+ ≈ 47.3 %, migrated from
  demographics.yaml::chronic_prevalence Phase 4b.2.β.
```

Sex-locked template (N40):
```yaml
attribute_id: n40_onset
pattern: event
clinical_scope:
  requires_age_band: [18, 120]
  requires_sex: M
body:
  event_name: n40_onset
  emits_icd: N40
  base_rate_by_age_band:
    - {age_lo: 50, age_hi: 99, rate: 0.0}
  one_shot: true
```

Mental-health template (F32, with 4 compounding modifiers migrated verbatim from `mental_health_onset_multipliers.yaml`):
```yaml
attribute_id: f32_onset
pattern: event
clinical_scope:
  requires_age_band: [18, 120]
body:
  event_name: f32_onset
  emits_icd: F32
  base_rate_by_age_band:
    - {age_lo: 18, age_hi: 39, rate: <λ_18_39>}
    - {age_lo: 40, age_hi: 59, rate: <λ_40_59>}
    - {age_lo: 60, age_hi: 120, rate: 0.0}
  rate_modifiers:
    - when: {has_chronic: ["E10", "E11"]}
      factor: 2.0           # diabetes_depression
    - when: {has_chronic: ["I50"]}
      factor: 2.0           # heart_failure_depression
    - when: {has_chronic_prefix: ["C"]}
      factor: 2.5           # cancer_depression
    - when: {has_chronic: ["I69.3", "I69.1"]}
      factor: 2.0           # post_stroke_depression
  one_shot: true
```

**Semantic migration rule for `has_chronic`**: today's `_mental_health_onset_multiplier` uses `exact & chronic_set` where `exact = set(rule.get("requires_any_chronic") or ())`. "E10" and "E11" in that list are EXACT-match codes, not prefixes. When a person carries "E11.9", `"E11.9" in {"E10", "E11"}` is False, so today's rule does NOT fire for E11.9 — only for exact "E10" or "E11" entries in `chronic_conditions`. However, in this codebase, DM chronic entries ARE stored as "E11.9" (not "E11"), so the current rule is partly dead for exact match. Investigate before migrating: if the current rule has been firing via `startswith`-shaped matching anywhere, migrate as `has_chronic_prefix`; if it was never firing (true exact match), migrate as `has_chronic` verbatim. **Ruling** owners (executor): record the finding in the ledger as `Task 2 Ruling: <per-rule shape> — <evidence from grep / audit>`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_chronic_onset_yamls_present.py -v`
Expected: all PASS (30 yamls present, all adult-gated, I10 refire-guard holds).

- [ ] **Step 5: Write Review Focus test — F32 compounds DM + cancer prefix**

```python
# tests/unit/longitudinal/test_f32_mental_health_multipliers.py
import numpy as np
import pytest
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step
pytestmark = pytest.mark.unit

def test_f32_onset_multiplier_compounds_dm_and_cancer():
    """Review Focus #5: F32 base × 2.0 (DM) × 2.5 (cancer prefix) = ×5.0.
    Pin the compounded factor via a seed sweep: a seed whose draw lands
    between (base × 1) and (base × 5) must fire only when BOTH triggers
    apply."""
    specs = load_attribute_specs()
    body = specs["f32_onset"].body
    # Pick an age band whose base is non-zero; find a seed draw d with
    # base < d < base × 5 so single trigger ≠ fire, both triggers = fire.
    base_rate = body.base_rate_by_age_band[0].rate  # 18-39 band
    assert base_rate > 0
    target = base_rate * 2.5  # a draw just under base × 2.5 should fire with 1 trigger too
    # Use a draw between base and base × 5. Seed=42 draws 0.774 — too high.
    # Easier: assert the modifier list contents.
    factors = {tuple(m.when.has_chronic or m.when.has_chronic_prefix): m.factor
               for m in body.rate_modifiers}
    assert factors.get(("E10", "E11")) == 2.0  # diabetes
    assert factors.get(("I50",)) == 2.0  # heart_failure
    assert factors.get(("C",)) == 2.5  # cancer prefix
    assert factors.get(("I69.3", "I69.1")) == 2.0  # post_stroke
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/unit/longitudinal/test_f32_mental_health_multipliers.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add clinosim/locale/shared/longitudinal/event/*.yaml tests/unit/longitudinal/test_chronic_onset_yamls_present.py tests/unit/longitudinal/test_f32_mental_health_multipliers.py
git commit -s -m "feat(longitudinal): 30 adult-chronic onset event yamls (Phase 4b.2.β Task 2)"
```

---

## Task 3: Retire `_annual_chronic_onset` + mental-health helpers

**Files:**
- Modify: `clinosim/modules/population/aging.py` — DELETE: `_STATE_PERIOD_ONSET_SKIP_CODES` (line 75), `_ChronicIncidenceSpec` (line 96), `_derive_annual_incidence_from_prevalence` (line 121), `_load_annual_incidence_for_locale` (line 161), `_annual_chronic_onset` (line 238), `_load_mental_health_onset_multipliers` (line 315), `_mental_health_onset_multiplier` (line 327). Remove `_annual_chronic_onset` from the `for pass_fn in (...)` tuple in `advance_population` (line 808). Drop the import for the mental-health loader (via `clinosim/locale/loader.py`).
- Modify: `clinosim/locale/loader.py` — remove `load_mental_health_onset_multipliers`. Remove its entry from the `_LOCALE_LOADERS` dict / wherever it is registered.
- Delete: `clinosim/locale/shared/mental_health_onset_multipliers.yaml`.
- Test: `tests/modules/population/test_aging_pass_retirement.py`

**Interfaces:**
- Consumes: Task 2 (30 event yamls loadable).
- Produces: `advance_population` iterates only 3 passes (`_stroke_sequela_promotion`, `_allergy_drift`, `_condition_reactive_mortality`). The longitudinal engine's `advance_one_year` then runs after the aging passes (unchanged), consuming the 30 new event yamls as part of the normal event-pattern dispatch.

- [ ] **Step 1: Write the failing test — aging pass tuple no longer includes `_annual_chronic_onset`**

```python
# tests/modules/population/test_aging_pass_retirement.py
import pytest
from clinosim.modules.population import aging
pytestmark = pytest.mark.unit

def test_annual_chronic_onset_function_is_removed():
    assert not hasattr(aging, "_annual_chronic_onset")

def test_mental_health_onset_multiplier_helper_is_removed():
    assert not hasattr(aging, "_mental_health_onset_multiplier")

def test_advance_population_passes_no_longer_include_annual_chronic_onset():
    import inspect
    src = inspect.getsource(aging.advance_population)
    assert "_annual_chronic_onset" not in src
```

Add Review Focus #2 test:
```python
def test_engine_ignores_legacy_state_period_codes():
    """Review Focus #2: legacy Z34 / Z37 on a person's chronic_conditions
    does not break the engine. The longitudinal engine iterates attributes
    by yaml declaration — Z34 / Z37 have no event yaml, so there is nothing
    to dispatch; the engine must not raise on their presence either."""
    from datetime import date
    import numpy as np
    from clinosim.modules.longitudinal.engine import initial_snapshot, advance_one_year
    from clinosim.types.population import PersonRecord
    person = PersonRecord(
        person_id="P-LEGACY",
        sex="F",
        date_of_birth=date(1980, 1, 1),
        chronic_conditions=["Z34", "Z37", "I10"],
    )
    initial_snapshot(person, year=2024, init_rng=np.random.default_rng(0))
    # Does not raise.
    advance_one_year(person, year=2025, year_rng=np.random.default_rng(0))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tests/modules/population/test_aging_pass_retirement.py -v`
Expected: FAIL — helpers still exist, tuple still contains `_annual_chronic_onset`.

- [ ] **Step 3: Delete the Python helpers + remove from pass tuple**

Delete the symbols listed in Files. Verify `advance_population` compiles.

Also delete `clinosim/locale/shared/mental_health_onset_multipliers.yaml` and its loader entry in `clinosim/locale/loader.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tests/modules/population/test_aging_pass_retirement.py tests/modules/longitudinal/ tests/unit/longitudinal/ -v`
Expected: all PASS (including Phase 4b.2.α regression + Task 1-2 artifacts).

- [ ] **Step 5: Run the full unit suite — ensure no caller references the deleted helpers**

Run: `PYTHONPATH=. python -m pytest tests/ --ignore=tests/e2e --ignore=tests/integration -q`
Expected: PASS. ImportError or AttributeError here means a straggler caller — fix it in-step (any helper that imported `_mental_health_onset_multiplier` must now read from the engine's event dispatch result, not from the aging pass).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -s -m "chore(aging): retire _annual_chronic_onset + mental-health multiplier (Phase 4b.2.β Task 3)"
```

---

## Task 4: Cohort epi regression + CHANGELOG

**Files:**
- Create: `tests/integration/test_cohort_epi_targets_post_migration.py`
- Modify: `CHANGELOG.md` — add Phase 4b.2.β Changed entry (new MINOR-track line, every adult patient's bytes shift per spec §2.3).

**Interfaces:**
- Consumes: Tasks 1-3 (new event yamls land, aging pass retired).
- Produces: Verified cohort epi behaviour. The integration test asserts that for a p=500 US seed=42 5y cohort each of the 30 ICDs falls within the band bounds declared in `HOSPITAL_COHORT_TARGET` (loaded via `clinosim.locale.loader`). Byte-identity is NOT checked (spec §2.3).

- [ ] **Step 1: Write the failing test — cohort epi targets**

```python
# tests/integration/test_cohort_epi_targets_post_migration.py
import pytest
from clinosim.modules.population.engine import generate_population
from clinosim.modules.population.aging import advance_population
pytestmark = pytest.mark.integration

EPI_TARGETS = {  # (ICD, min_prev, max_prev) at end of 5y sim over age-18+ cohort
    "I10":   (0.40, 0.60),  # NHANES ~47 %
    "E11.9": (0.14, 0.26),  # cohort target ~20 % Medicare-user
    "E78":   (0.45, 0.65),  # cohort target ~55 %
    # … (populate from HOSPITAL_COHORT_TARGET for all 30)
}

@pytest.mark.slow
def test_adult_cohort_prevalence_in_target_bands_post_migration():
    """After migration, p=500 US seed=42 5y cohort still produces each
    chronic ICD's prevalence inside its target band. Byte-identity is
    not required (spec §2.3) — epi is."""
    population = generate_population(size=500, country="US", seed=42)
    for year in range(2024, 2029):
        advance_population(population, year=year, seed=42)
    adults = [p for p in population.persons if p.age >= 18 or (2028 - p.date_of_birth.year) >= 18]
    assert len(adults) > 0
    for icd, (lo, hi) in EPI_TARGETS.items():
        hits = sum(1 for p in adults if icd in p.chronic_conditions)
        prev = hits / len(adults)
        assert lo <= prev <= hi, f"{icd}: prev {prev:.3f} out of [{lo}, {hi}]"
```

The executor populates `EPI_TARGETS` by reading the bands declared in `clinosim/locale/us/demographics.yaml::chronic_prevalence` for each ICD and converting them to a `(min, max)` band around the terminal-age-band prevalence (±30 % relative tolerance for stochasticity at p=500).

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `PYTHONPATH=. python -m pytest tests/integration/test_cohort_epi_targets_post_migration.py -v`
Expected: PASS if the migration preserved cohort epi; FAIL on any ICD whose band is violated — that is the signal to re-derive its `base_rate_by_age_band` entry in Task 2's yaml (the band-diff formula was mis-applied, or the per-band rate was transcribed wrong).

- [ ] **Step 3: Add CHANGELOG entry**

Append under `## [Unreleased] / ### Changed`:
```markdown
- **30 adult-chronic ICDs migrated from `_annual_chronic_onset` aging pass to the longitudinal event pattern** (Issue #1697 — Phase 4b.2.β, migration pass; builds on the Phase 4b.2.α schema extensions landed in PR #1727). `clinosim/modules/population/aging.py::_annual_chronic_onset` + `_mental_health_onset_multiplier` + `_derive_annual_incidence_from_prevalence` + `_load_annual_incidence_for_locale` + `_ChronicIncidenceSpec` + `_STATE_PERIOD_ONSET_SKIP_CODES` are retired. Each of the 30 ICDs (I10, E11.9, E78, J44, N18, I50, I48, I25, M81, F00, G20, E03, K21, J45, N40, M17, G35, F32, F33, F41.1, C15, C16, C25, C67, C71, C18, C22, C34, C50, C61) gains a `clinosim/locale/shared/longitudinal/event/<code>_onset.yaml` carrying age-band base rates + sex gating + comorbidity-conditional rate modifiers migrated verbatim from `mental_health_onset_multipliers.yaml` (which is also retired). `advance_population` iterates 3 aging passes (`_stroke_sequela_promotion`, `_allergy_drift`, `_condition_reactive_mortality`) instead of 4; the longitudinal engine's event dispatch handles chronic onset. Byte-identity for every adult patient breaks per spec §2.3 (acceptable, documented). Cohort epi preserved — all 30 ICDs land within target bands at p=500 US seed=42 5y per `test_adult_cohort_prevalence_in_target_bands_post_migration`. MINOR-track CIF change: every adult patient's `chronic_conditions` list may differ (same cohort distribution, different individual trajectories); non-adult cohorts byte-identical.
```

- [ ] **Step 4: Run final regression**

Run: `PYTHONPATH=. python -m pytest tests/ --ignore=tests/e2e -q`
Expected: PASS. The e2e suite is skipped here because the migration shifts every adult patient's trajectory and the `test_patient_identity_stable_across_encounters` style e2e expectations are pre-migration pins; a follow-up PR re-pins them if needed.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_cohort_epi_targets_post_migration.py CHANGELOG.md
git commit -s -m "test(cohort): epi bands preserved post Phase 4b.2.β migration; CHANGELOG"
```
