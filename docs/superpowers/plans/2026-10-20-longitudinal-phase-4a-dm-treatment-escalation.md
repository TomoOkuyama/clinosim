# Longitudinal Phase 4a — DM Treatment Escalation (SGLT2i + Basal Insulin)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the event pattern to add medications (not just ICD codes) and ship two HbA1c-driven DM treatment escalation yamls — SGLT2i add when HbA1c > 9.0 % and basal insulin add when HbA1c > 10.0 %. On fire, the engine appends the new drug to `PersonRecord.current_medications` as a `HomeMedication`, so Phase 3's longitudinal HbA1c latent now drives real medication-list evolution across sim years instead of frozen single-agent monotherapy.

**Architecture:** Two additive fields on `EventSpec` — `emits_meds: list[str]` (drug names to add on fire) and `fire_marker: str` (dedup key for `one_shot` events that emit meds instead of ICDs). `event.step()` scans prior-year `snapshot.med_additions` for the fire_marker to dedup; `engine._apply_pattern`'s event branch gains a drug-name → `HomeMedication` lookup that resolves against `chronic_medications.yaml`, so the ICD/dose/route metadata stays single-sourced. Two new yamls under `clinosim/locale/shared/longitudinal/med/` carry the clinical rules; `chronic_medications.yaml` gains Empagliflozin / Dapagliflozin / Insulin glargine entries under `E11.9` with `probability: 0.0` so activation sampling never picks them (byte-identity preserved) but the lookup still resolves. The `_annual_chronic_onset` adult-chronic migration and HTN / lipid escalation stay in Phase 4b — explicitly out of scope here to keep this one reviewable.

**Tech Stack:** Python 3.12, pydantic 2.x, numpy, pyyaml.

**Spec:** `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` — §4.2.3 event yaml body, §5.2 pattern-level API, §8 Phase 3 scope (treatment escalation sub-item, carved out as this plan's "Phase 4a").

## Global Constraints

- `pattern: event` yamls that emit meds live under `clinosim/locale/shared/longitudinal/med/`. The ICD-emitting event yamls stay under `clinosim/locale/shared/longitudinal/event/`.
- `EventSpec` adds two fields and keeps `extra="forbid"`: `emits_meds: list[str] = []` and `fire_marker: str = ""`. Pydantic `model_post_init` validates that `emits_icd` and `emits_meds` are not both empty — an event that produces nothing is a yaml authoring error.
- `one_shot: true` dedup key: when `emits_icd` is set, the existing dedup against `person.chronic_conditions` + `prev_history[*].new_complications` applies. When `emits_icd == ""` and `fire_marker != ""`, dedup against `prev_history[*].med_additions` by exact string match on `fire_marker`.
- Drug-name → `HomeMedication` lookup rule: scan `chronic_medications.yaml` for an entry whose `drug` field matches the requested name; return a `HomeMedication` built from `drug` / `drug_ja` / `dose` / `route` / `frequency`. On miss, fall back to `HomeMedication(drug_name=name, route="PO", frequency="daily")` — a yaml authoring warning, not a crash.
- Rate modifiers remain multiplicative with final clamp to `[0.0, 1.0]`; the escalation yamls use the `operator: "<="` form (introduced in Phase 3) with `factor: 0.0` to gate OUT the controlled-HbA1c case.
- Byte-identity across the migration is NOT required (spec §2.3 non-goal). DM patients whose HbA1c > 9.0 will gain SGLT2i; those whose HbA1c > 10.0 will gain basal insulin. Non-DM cohorts byte-identical when they never had E11.* chronic — the activator path for them never touches these yamls.
- `scripts/reproduce.sh` same-seed-twice contract stays as CI gate. CI merge gate: `scripts/wait-pr-ci.sh <num>` + grep `"FAILURE"` = 0.
- No Claude attribution lines in PR body or commit messages (DCO signoff only via `git commit -s`).
- CHANGELOG + PR body entries written as a single Markdown paragraph per bullet, NOT hard-wrapped.

## Review Focus

The five input classes most likely to bite a person using this software that the task tests do not naturally exercise:

1. **`one_shot` dedup for med-only events against prior-year `med_additions`**: a patient escalated to Empagliflozin in year Y must not re-escalate at year Y+1 even if HbA1c stays > 9.0. The dedup must walk `prev_history[*].med_additions` and match on `fire_marker` (or on each name in `emits_meds` when `fire_marker` is empty). Pinned in Task 2.
2. **Drug-name lookup resolves across locale fallback**: Empagliflozin lives under `E11.9` in `chronic_medications.yaml`; the lookup must find it there, not require a top-level `drugs:` index. A missing drug falls through to the default `HomeMedication(drug_name=X, route="PO", frequency="daily")` with a one-line log line, not a crash. Pinned in Task 3.
3. **Escalation does not duplicate an existing drug**: a patient already on Empagliflozin (sampled at activation — hypothetical since `probability: 0.0` prevents this, but a future yaml bump might set non-zero) must not have Empagliflozin re-appended by the escalation event. The engine checks `current_medications[*].drug_name` membership before appending. Pinned in Task 4.
4. **Non-DM cohort stays byte-identical**: a cohort with zero `E11` chronic patients produces byte-identical CIF before and after Phase 4a (no event in scope → no RNG draws from the event pattern → no cursor shift). Pinned in Task 7 integration.
5. **Insulin escalation at HbA1c > 10.0 — one-shot vs SGLT2i independence**: a patient at sustained HbA1c > 10.0 should accumulate BOTH Empagliflozin (via SGLT2i yaml, > 9.0 threshold) AND Insulin glargine (via insulin yaml, > 10.0 threshold) across sim years — the two events are independent, no yaml declares `depends_on: dm_escalate_sglt2i`. Pinned in Task 5.

---

## File Structure

**Create:**
- `clinosim/locale/shared/longitudinal/med/dm_escalate_sglt2i_e11.yaml` — HbA1c > 9 → add Empagliflozin.
- `clinosim/locale/shared/longitudinal/med/dm_escalate_insulin_e11.yaml` — HbA1c > 10 → add Insulin glargine.
- `tests/modules/longitudinal/test_event_med_additions.py` — event pattern meds path (dedup + modifier + lookup).
- `tests/modules/longitudinal/test_engine_med_dispatch.py` — engine wiring (person.current_medications mutation + idempotence + duplicate guard).
- `tests/modules/longitudinal/test_med_yamls_load.py` — yaml schema validation + emits_meds presence.
- `tests/integration/test_dm_escalation_in_cif.py` — p=100 DM 5y cohort escalation rate correlation with HbA1c.

**Modify:**
- `clinosim/modules/longitudinal/patterns/event.py` — add `emits_meds` + `fire_marker` fields, `model_post_init` validation, extend `step()` dedup and return `EventResult.med_additions`.
- `clinosim/modules/longitudinal/loader.py` — carry the two new keys through `_build_event_body`.
- `clinosim/modules/longitudinal/engine.py` — in the event branch, resolve each `result.med_additions` entry to a `HomeMedication` via the lookup helper and append to `person.current_medications` with duplicate guard.
- `clinosim/modules/longitudinal/med_lookup.py` — NEW module holding the drug-name → `HomeMedication` resolver (keeps engine.py focused on dispatch).
- `clinosim/locale/shared/chronic_medications.yaml` — under `E11.9`, add `Empagliflozin`, `Dapagliflozin`, `Insulin glargine` entries with `probability: 0.0` so activation sampling never picks them.
- `CHANGELOG.md` — one Unreleased Fixed entry describing the escalation + the three new chronic_medications.yaml entries.

---

## Task 1: Extend EventSpec with emits_meds + fire_marker

**Files:**
- Modify: `clinosim/modules/longitudinal/patterns/event.py`
- Test: `tests/modules/longitudinal/test_event_med_additions.py`

**Interfaces:**
- Consumes: Phase 3 `EventSpec` + `step()` + `EventResult` (already in `event.py`).
- Produces: `EventSpec` gains `emits_meds: list[str] = []` and `fire_marker: str = ""`; `model_post_init` raises `ValueError` when both `emits_icd` and `emits_meds` are empty. The step() return populates `EventResult.med_additions = spec.emits_meds` on fire.

- [ ] **Step 1: Write failing tests**

```python
# tests/modules/longitudinal/test_event_med_additions.py
import numpy as np
import pytest
from clinosim.modules.longitudinal.patterns.event import EventSpec, step


def test_event_spec_emits_meds_default_empty():
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    assert spec.emits_meds == []
    assert spec.fire_marker == ""


def test_event_spec_rejects_fully_empty_event():
    """Both emits_icd and emits_meds empty = yaml authoring error."""
    with pytest.raises(ValueError):
        EventSpec(event_name="x", emits_icd="",
                  base_annual_rate=1.0, rate_modifiers=[], one_shot=True)


def test_event_spec_accepts_med_only_event():
    """emits_icd empty + emits_meds populated = valid med-only event."""
    spec = EventSpec(event_name="dm_escalate_sglt2i", emits_icd="",
                     emits_meds=["Empagliflozin"],
                     fire_marker="dm_escalate_sglt2i",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    assert spec.emits_meds == ["Empagliflozin"]
    assert spec.fire_marker == "dm_escalate_sglt2i"


def test_step_med_only_fire_populates_med_additions():
    """When the event fires and emits_meds is non-empty,
    EventResult.med_additions == spec.emits_meds."""
    spec = EventSpec(event_name="x", emits_icd="",
                     emits_meds=["Empagliflozin"],
                     fire_marker="x",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    result = step([], [], rng, spec, context={})
    assert result.fired
    assert result.emits_icd == ""
    assert result.med_additions == ["Empagliflozin"]


def test_step_med_only_no_fire_returns_empty_med_additions():
    spec = EventSpec(event_name="x", emits_icd="",
                     emits_meds=["Empagliflozin"],
                     fire_marker="x",
                     base_annual_rate=0.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    result = step([], [], rng, spec, context={})
    assert not result.fired
    assert result.med_additions == []


def test_event_spec_rejects_unknown_field():
    """extra='forbid' still applies — a typo'd field is a loud failure."""
    with pytest.raises(ValueError):
        EventSpec(event_name="x", emits_icd="E11.21", typo_field="oops",
                  base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
```

- [ ] **Step 2: Run tests to verify failing**

Run: `pytest tests/modules/longitudinal/test_event_med_additions.py -v`
Expected: 6 FAIL — `TypeError: EventSpec() got unexpected keyword argument 'emits_meds'` on the three construction tests; the fully-empty rejection test fails because the current spec accepts `emits_icd=""`.

- [ ] **Step 3: Extend EventSpec and step()**

In `clinosim/modules/longitudinal/patterns/event.py`:

- Add `emits_meds: list[str] = Field(default_factory=list)` on `EventSpec`.
- Add `fire_marker: str = ""` on `EventSpec`.
- Add `def model_post_init(self, _ctx: Any) -> None` to `EventSpec` that raises `ValueError` when `self.emits_icd == "" and not self.emits_meds` (message: `"EventSpec {self.event_name!r}: emits_icd and emits_meds cannot both be empty"`).
- In `step()`, on fire, return `EventResult(fired=True, emits_icd=spec.emits_icd, med_additions=list(spec.emits_meds), med_removals=[])`. On no-fire or dedup, keep the empty-list return.

The one_shot dedup extension lives in Task 2 — don't touch it here.

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest tests/modules/longitudinal/test_event_med_additions.py -v`
Expected: 6/6 pass.

- [ ] **Step 5: Full event-pattern regression**

Run: `pytest tests/modules/longitudinal/test_event_step.py -v`
Expected: 7/7 pass (Phase 3 tests still green).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/event.py tests/modules/longitudinal/test_event_med_additions.py
git commit -s -m "feat(longitudinal): extend EventSpec with emits_meds + fire_marker"
```

---

## Task 2: Extend step() dedup for med-only events

**Files:**
- Modify: `clinosim/modules/longitudinal/patterns/event.py` (step() body)
- Test: extend `tests/modules/longitudinal/test_event_med_additions.py`

**Interfaces:**
- Consumes: Task 1's `fire_marker` field + `EventResult.med_additions`.
- Produces: `step()` dedup logic that handles med-only one_shot events — when `emits_icd == ""` and `one_shot=True`, scan `prev_history[*].med_additions` for `spec.fire_marker` and return `fired=False` on hit.

- [ ] **Step 1: Write failing tests**

Append to `tests/modules/longitudinal/test_event_med_additions.py`:

```python
def test_step_med_only_one_shot_dedup_against_prior_med_additions():
    """Review Focus #1: a med-only event that fired last year must not
    re-fire this year, even at p=1.0."""
    from clinosim.modules.longitudinal.snapshot import YearSnapshot
    spec = EventSpec(event_name="dm_escalate_sglt2i", emits_icd="",
                     emits_meds=["Empagliflozin"],
                     fire_marker="dm_escalate_sglt2i",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, med_additions=["dm_escalate_sglt2i"])]
    result = step([], prior, rng, spec, context={})
    assert not result.fired
    assert result.med_additions == []


def test_step_med_only_dedup_requires_fire_marker():
    """Without fire_marker set, med-only event has no dedup key and
    will re-fire every year — the yaml author must set fire_marker."""
    from clinosim.modules.longitudinal.snapshot import YearSnapshot
    spec = EventSpec(event_name="x", emits_icd="",
                     emits_meds=["Empagliflozin"],
                     fire_marker="",   # intentionally empty
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, med_additions=["Empagliflozin"])]
    result = step([], prior, rng, spec, context={})
    # Without a dedup key, event still fires — this is intentional
    # (Phase 4a's yamls always set fire_marker; this test pins that
    # the engine does not silently invent one).
    assert result.fired


def test_step_med_only_dedup_does_not_affect_icd_only_events():
    """ICD-only events keep their Phase 3 dedup via emits_icd — the
    new fire_marker logic doesn't interfere."""
    from clinosim.modules.longitudinal.snapshot import YearSnapshot
    spec = EventSpec(event_name="x", emits_icd="E11.21",
                     base_annual_rate=1.0, rate_modifiers=[], one_shot=True)
    rng = np.random.default_rng(0)
    prior = [YearSnapshot(year=2024, new_complications=["E11.21"])]
    result = step([], prior, rng, spec, context={})
    assert not result.fired
```

- [ ] **Step 2: Run tests to verify failing**

Run: `pytest tests/modules/longitudinal/test_event_med_additions.py::test_step_med_only_one_shot_dedup_against_prior_med_additions -v`
Expected: FAIL — dedup not yet implemented; the event fires despite the prior-year marker.

- [ ] **Step 3: Extend step() dedup**

In `event.py::step()`, replace the current one_shot block with:

```python
if spec.one_shot:
    # ICD-emitting event: dedup against chronic_conditions + prior new_complications.
    if spec.emits_icd and spec.emits_icd in person_chronic:
        return EventResult(False, spec.emits_icd, [], [])
    if spec.emits_icd:
        for snap in prev_history or []:
            if spec.emits_icd in getattr(snap, "new_complications", []):
                return EventResult(False, spec.emits_icd, [], [])
    # Med-emitting event: dedup against prior med_additions via fire_marker.
    if spec.fire_marker:
        for snap in prev_history or []:
            if spec.fire_marker in getattr(snap, "med_additions", []):
                return EventResult(False, spec.emits_icd, [], [])
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest tests/modules/longitudinal/test_event_med_additions.py -v`
Expected: all tests from Task 1 + Task 2 pass (9 total).

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/patterns/event.py tests/modules/longitudinal/test_event_med_additions.py
git commit -s -m "feat(longitudinal): add fire_marker dedup for med-only one_shot events"
```

---

## Task 3: Drug-name → HomeMedication lookup helper

**Files:**
- Create: `clinosim/modules/longitudinal/med_lookup.py`
- Test: `tests/modules/longitudinal/test_med_lookup.py`

**Interfaces:**
- Produces: `resolve_med_name(drug_name: str) -> HomeMedication`. Scans every entry in `chronic_medications.yaml` for a match on the `drug` field; returns a `HomeMedication` built from the matched entry's `drug` / `drug_ja` / `dose` / `route` / `frequency`. On miss, returns `HomeMedication(drug_name=drug_name, route="PO", frequency="daily")`. `lru_cache(maxsize=256)` so repeated lookups hit cached results.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_med_lookup.py
from clinosim.modules.longitudinal.med_lookup import resolve_med_name
from clinosim.types.patient import HomeMedication


def test_resolve_known_drug_returns_full_metadata():
    """Metformin is defined under E11.9 in chronic_medications.yaml."""
    hm = resolve_med_name("Metformin")
    assert hm.drug_name == "Metformin"
    assert hm.route == "PO"
    assert hm.frequency == "bid"
    assert hm.dose == "500mg"


def test_resolve_unknown_drug_returns_default():
    """Review Focus #2: a drug not in chronic_medications.yaml falls
    back to a sensible default HomeMedication, not a crash."""
    hm = resolve_med_name("UnknownNewDrug")
    assert hm.drug_name == "UnknownNewDrug"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == ""


def test_resolve_is_cached():
    """Idempotent calls return equal HomeMedication instances."""
    hm1 = resolve_med_name("Metformin")
    hm2 = resolve_med_name("Metformin")
    assert hm1 == hm2
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_med_lookup.py -v`
Expected: FAIL — `ModuleNotFoundError: clinosim.modules.longitudinal.med_lookup`.

- [ ] **Step 3: Implement med_lookup.py**

Signature: `def resolve_med_name(drug_name: str) -> HomeMedication`. Internally:
1. Load `chronic_medications.yaml` via `clinosim.locale.loader.load_chronic_medications` (already cached).
2. Iterate every ICD block's `medications: list[dict]`, matching on `entry["drug"] == drug_name`.
3. On match, construct `HomeMedication(drug_name=entry["drug"], drug_name_ja=entry.get("drug_ja", ""), route=entry.get("route", "PO"), dose=entry.get("dose", ""), frequency=entry.get("frequency", "daily"))`.
4. On miss, return `HomeMedication(drug_name=drug_name, route="PO", frequency="daily")`.
5. Wrap in `functools.lru_cache(maxsize=256)` so repeated same-name lookups are O(1).

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_med_lookup.py -v`
Expected: 3/3 pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/longitudinal/med_lookup.py tests/modules/longitudinal/test_med_lookup.py
git commit -s -m "feat(longitudinal): add drug-name to HomeMedication lookup helper"
```

---

## Task 4: Engine wiring — mutate person.current_medications on fire

**Files:**
- Modify: `clinosim/modules/longitudinal/engine.py` (event branch of `_apply_pattern`)
- Test: `tests/modules/longitudinal/test_engine_med_dispatch.py`

**Interfaces:**
- Consumes: Task 1 `EventSpec.emits_meds`, Task 2 fire_marker dedup, Task 3 `resolve_med_name`.
- Produces: when an event fires with non-empty `med_additions`, each drug name is resolved to a `HomeMedication` and appended to `person.current_medications`, deduped against existing `drug_name`.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_engine_med_dispatch.py
# Build a person with E11.9 chronic and no current_medications.
# Monkeypatch _LONGITUDINAL_DIR to a yaml dir with:
#   - hba1c AR(1) attribute (phi=1.0, sigma=0, target=10.0 — deterministic 10)
#   - dm_escalate_sglt2i (event, emits_meds=["Empagliflozin"],
#       fire_marker="dm_escalate_sglt2i", base_annual_rate=1.0, one_shot)
# Call initial_snapshot(person, 2024, rng) then advance_one_year(person, 2025, rng).
# Assert:
#   - person.current_medications has one entry with drug_name="Empagliflozin"
#   - snap.med_additions contains the fire_marker string
# Call advance_one_year(person, 2026, rng) again:
#   - person.current_medications still has exactly one Empagliflozin entry
#     (idempotent — fire_marker dedup held via prev_history)
#   - snap.med_additions for year 2026 is empty
```

Also pin Review Focus #3 (duplicate drug guard):

```python
def test_engine_does_not_duplicate_existing_drug():
    """Review Focus #3: if person already has Empagliflozin in
    current_medications, the escalation event does not duplicate it
    even on fire."""
    # Build person with current_medications=[HomeMedication(drug_name="Empagliflozin", ...)]
    # Fire the escalation event. Assert current_medications stays length 1.
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_engine_med_dispatch.py -v`
Expected: FAIL — `person.current_medications` empty after fire (engine not yet mutating it).

- [ ] **Step 3: Wire engine.py event branch**

In `clinosim/modules/longitudinal/engine.py::_apply_pattern`, inside the `event` branch (currently around line 155-175), after the existing `snapshot.med_additions.extend(result.med_additions)` line, add:

```python
if result.med_additions:
    from clinosim.modules.longitudinal.med_lookup import resolve_med_name
    existing_drug_names = {hm.drug_name for hm in person.current_medications}
    for drug_name in result.med_additions:
        if drug_name in existing_drug_names:
            continue
        person.current_medications.append(resolve_med_name(drug_name))
        existing_drug_names.add(drug_name)
```

Also change the `snapshot.med_additions.extend(result.med_additions)` line to append the fire_marker (not the drug names) so dedup in Task 2 works. Specifically: when the fired event has a `fire_marker`, record the fire_marker as the dedup token in `snapshot.med_additions`; when it has only `emits_meds` and no `fire_marker`, record the drug names (fallback).

Ruling (plan author): `snapshot.med_additions` serves TWO consumers now — (a) Task 2's dedup scan (needs fire_marker string), and (b) downstream CIF emit (needs drug names for human-readable history). To avoid a schema fork, keep `med_additions` carrying the fire_marker when set, and let CIF emit resolve back to drug names via the fire_marker → spec lookup. This matches how `new_complications` carries ICD codes that are both the dedup token AND the clinical payload. Implementer: if this coupling becomes awkward downstream, split `med_additions` into `fired_markers` + `med_names` in a Phase 4b follow-up — ledger it.

Concretely in engine.py:

```python
elif spec.pattern == "event":
    # ... existing dispatch ...
    if result.fired:
        if result.emits_icd:
            snapshot.new_complications.append(result.emits_icd)
            if result.emits_icd not in person.chronic_conditions:
                person.chronic_conditions.append(result.emits_icd)
        if spec.body.fire_marker:
            snapshot.med_additions.append(spec.body.fire_marker)
        elif result.med_additions:
            snapshot.med_additions.extend(result.med_additions)
        if result.med_additions:
            from clinosim.modules.longitudinal.med_lookup import resolve_med_name
            existing_drug_names = {hm.drug_name for hm in person.current_medications}
            for drug_name in result.med_additions:
                if drug_name in existing_drug_names:
                    continue
                person.current_medications.append(resolve_med_name(drug_name))
                existing_drug_names.add(drug_name)
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_engine_med_dispatch.py -v`
Expected: 2/2 pass.

- [ ] **Step 5: Full longitudinal regression**

Run: `pytest tests/modules/longitudinal/`
Expected: all green (Phase 1 + Phase 2 + Phase 3 + Phase 4a).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/longitudinal/engine.py tests/modules/longitudinal/test_engine_med_dispatch.py
git commit -s -m "feat(longitudinal): mutate person.current_medications on med-emitting event fire"
```

---

## Task 5: SGLT2i + basal insulin yamls

**Files:**
- Create: `clinosim/locale/shared/longitudinal/med/dm_escalate_sglt2i_e11.yaml`
- Create: `clinosim/locale/shared/longitudinal/med/dm_escalate_insulin_e11.yaml`
- Test: `tests/modules/longitudinal/test_med_yamls_load.py`

**Interfaces:**
- Consumes: Tasks 1-2 EventSpec extensions, Task 3 lookup helper (via engine wiring from Task 4).
- Produces: two `AttributeSpec` registered at import under `dm_escalate_sglt2i_e11` and `dm_escalate_insulin_e11`.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_med_yamls_load.py
from clinosim.modules.longitudinal.loader import load_attribute_specs


EXPECTED = {
    "dm_escalate_sglt2i_e11": {
        "emits_meds": ["Empagliflozin"],
        "fire_marker": "dm_escalate_sglt2i_e11",
        "requires_chronic_codes": ["E11"],
    },
    "dm_escalate_insulin_e11": {
        "emits_meds": ["Insulin glargine"],
        "fire_marker": "dm_escalate_insulin_e11",
        "requires_chronic_codes": ["E11"],
    },
}


def test_dm_escalation_yamls_load():
    specs = load_attribute_specs()
    for attr_id, want in EXPECTED.items():
        assert attr_id in specs
        body = specs[attr_id].body
        assert body.emits_meds == want["emits_meds"]
        assert body.fire_marker == want["fire_marker"]
        assert body.emits_icd == ""
        assert body.one_shot is True
        assert specs[attr_id].clinical_scope.requires_chronic_codes == want["requires_chronic_codes"]
```

Also pin Review Focus #5 (independence):

```python
def test_dm_escalation_yamls_independent():
    """Review Focus #5: insulin yaml does not depend_on sglt2i yaml."""
    specs = load_attribute_specs()
    insulin_deps = specs["dm_escalate_insulin_e11"].depends_on
    assert "dm_escalate_sglt2i_e11" not in insulin_deps
    assert "hba1c" in insulin_deps  # does depend on hba1c
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_med_yamls_load.py -v`
Expected: FAIL — 2 missing attribute_ids.

- [ ] **Step 3: Author the two yamls**

Clinical calibration anchors:

- **SGLT2i add (Empagliflozin)**: ADA Standards of Care in Diabetes 2024, §9 "Pharmacologic Approaches to Glycemic Treatment". When HbA1c above individualized target on metformin monotherapy, add SGLT2i (or GLP-1) as second agent — strong recommendation. In practice ~40-60 % of US T2DM patients with HbA1c > 9 initiate SGLT2i within 1 year (CDC NHANES 2017-2020 secondary therapy uptake). Pick `base_annual_rate: 0.6` under uncontrolled; gate OUT when HbA1c ≤ 9.0 via factor 0.0.
- **Basal insulin add (Insulin glargine)**: ADA 2024 §9 Figure 9.3 — insulin initiation when HbA1c > 10 %, severe symptomatic hyperglycemia, or when oral therapy fails. US T2DM cohort uptake ~30 % within 1 year at HbA1c > 10 (NHANES 2017-2020 insulin initiation). Pick `base_annual_rate: 0.5` under uncontrolled; gate OUT when HbA1c ≤ 10.0 via factor 0.0.

Yaml 1 (`dm_escalate_sglt2i_e11.yaml`):

```yaml
# SGLT2i treatment escalation — event pattern.
#
# Phase 4a of the longitudinal state-evolution subsystem (Issue #1697).
# Base rate 60 %/yr under uncontrolled HbA1c (> 9.0 %), gated OUT when
# HbA1c ≤ 9.0 % via a factor-zero modifier.
#
# Clinical basis: ADA Standards of Care in Diabetes 2024, §9 Figure 9.3
# (second-agent intensification). SGLT2i (empagliflozin / dapagliflozin
# / canagliflozin) and GLP-1 RA (semaglutide / liraglutide) are the
# preferred second-line agents on top of metformin when HbA1c remains
# above target; SGLT2i is preferred when ASCVD / HF / CKD comorbidity
# is present. Phase 4a emits Empagliflozin as a single representative
# SGLT2i; locale JP alternative (Dapagliflozin / Luseogliflozin) can
# ship as a Phase 4b locale_exclude variant.
attribute_id: dm_escalate_sglt2i_e11
pattern: event
depends_on: [hba1c]
clinical_scope:
  requires_chronic_codes: ["E11"]
  requires_age_band: [18, 120]

event_name: dm_escalate_sglt2i_e11
emits_icd: ""
emits_meds: ["Empagliflozin"]
fire_marker: dm_escalate_sglt2i_e11
base_annual_rate: 0.6
rate_modifiers:
  - when: {attribute: hba1c, operator: "<=", value: 9.0}
    factor: 0.0
one_shot: true
narrative_label:
  en: "DM SGLT2i escalation"
  ja: "糖尿病 SGLT2 阻害薬 追加"
source:
  - "American Diabetes Association. Standards of Care in Diabetes — 2024. Section 9: Pharmacologic Approaches to Glycemic Treatment. Diabetes Care 2024;47(Suppl 1):S158."
  - "CDC NHANES 2017-2020 secondary oral antidiabetic therapy uptake in uncontrolled T2DM."
```

Yaml 2 (`dm_escalate_insulin_e11.yaml`):

```yaml
# Basal insulin initiation — event pattern.
#
# Phase 4a of the longitudinal state-evolution subsystem (Issue #1697).
# Base rate 50 %/yr under severe uncontrolled HbA1c (> 10.0 %), gated
# OUT when HbA1c ≤ 10.0 % via a factor-zero modifier. Independent of
# the SGLT2i escalation yaml — a patient at sustained HbA1c > 10.0
# accumulates both agents across sim years.
#
# Clinical basis: ADA Standards of Care in Diabetes 2024, §9 Figure 9.3
# — insulin initiation when HbA1c > 10 %, severe symptomatic
# hyperglycemia, or failure of oral intensification. Insulin glargine
# ships as the representative long-acting basal; detemir / degludec
# alternatives are a Phase 4b locale variant.
attribute_id: dm_escalate_insulin_e11
pattern: event
depends_on: [hba1c]
clinical_scope:
  requires_chronic_codes: ["E11"]
  requires_age_band: [18, 120]

event_name: dm_escalate_insulin_e11
emits_icd: ""
emits_meds: ["Insulin glargine"]
fire_marker: dm_escalate_insulin_e11
base_annual_rate: 0.5
rate_modifiers:
  - when: {attribute: hba1c, operator: "<=", value: 10.0}
    factor: 0.0
one_shot: true
narrative_label:
  en: "DM insulin initiation"
  ja: "糖尿病 インスリン導入"
source:
  - "American Diabetes Association. Standards of Care in Diabetes — 2024. Section 9: Pharmacologic Approaches to Glycemic Treatment. Diabetes Care 2024;47(Suppl 1):S158."
```

Implementer may factor out an `_escalation_body(name, hba1c_threshold, drug, rate)` helper if the two yamls duplicate too much — but each yaml stands alone as domain-expert-reviewable, so prefer two full yamls over a template.

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_med_yamls_load.py -v`
Expected: 2/2 pass.

- [ ] **Step 5: Full longitudinal regression**

Run: `pytest tests/modules/longitudinal/`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add clinosim/locale/shared/longitudinal/med/ tests/modules/longitudinal/test_med_yamls_load.py
git commit -s -m "feat(longitudinal): add SGLT2i + basal insulin DM escalation yamls"
```

---

## Task 6: Extend chronic_medications.yaml with Empagliflozin / Dapagliflozin / Insulin glargine

**Files:**
- Modify: `clinosim/locale/shared/chronic_medications.yaml` (under `E11.9` block)
- Test: extend `tests/modules/longitudinal/test_med_lookup.py` to pin new resolutions.

**Interfaces:**
- Consumes: Task 3 lookup helper.
- Produces: `resolve_med_name("Empagliflozin")` returns full metadata (dose / route / frequency). Same for `Dapagliflozin` and `Insulin glargine`. Activation sampling at `_derive_home_medications` NEVER picks these because `probability: 0.0` (byte-identity preserved for existing E11.9 patients).

- [ ] **Step 1: Write failing test**

Append to `tests/modules/longitudinal/test_med_lookup.py`:

```python
def test_resolve_empagliflozin_full_metadata():
    hm = resolve_med_name("Empagliflozin")
    assert hm.drug_name == "Empagliflozin"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "10mg"


def test_resolve_insulin_glargine_full_metadata():
    hm = resolve_med_name("Insulin glargine")
    assert hm.drug_name == "Insulin glargine"
    assert hm.route == "SC"
    assert hm.frequency == "daily"
```

Also pin that activation sampling doesn't change (byte-identity gate):

```python
# tests/unit/patient/test_e11_activation_byte_identity_phase4a.py
def test_e11_activation_meds_byte_identical_pre_phase4a():
    """Phase 4a adds new E11.9 entries with probability: 0.0. Repeat
    a p=100 US seed=42 activation; the current_medications set per
    patient must be identical to the pre-Phase-4a baseline captured
    in tests/fixtures/.../e11_activation_meds_baseline_seed42.json
    (regenerated by the plan author on first run)."""
    # Implementation: snapshot current_medications per patient after
    # activation, compare to the baseline fixture. On first run,
    # record the fixture; subsequent runs must match byte-for-byte.
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_med_lookup.py::test_resolve_empagliflozin_full_metadata -v`
Expected: FAIL — Empagliflozin falls through to the default (`dose == ""`, `route == "PO"` is correct by accident but `frequency` is `"daily"` not from the yaml).

- [ ] **Step 3: Extend chronic_medications.yaml E11.9 block**

Add three entries under `E11.9::medications`:

```yaml
    - {drug: "Empagliflozin", drug_ja: "エンパグリフロジン", dose: "10mg", drug_class: "sglt2i", route: "PO", frequency: "daily", probability: 0.0}
    - {drug: "Dapagliflozin", drug_ja: "ダパグリフロジン", dose: "10mg", drug_class: "sglt2i", route: "PO", frequency: "daily", probability: 0.0}
    - {drug: "Insulin glargine", drug_ja: "インスリン グラルギン", dose: "10U", drug_class: "basal_insulin", route: "SC", frequency: "daily", probability: 0.0}
```

Keep the existing Metformin + Sliding scale insulin entries unchanged. The `probability: 0.0` guarantees activation sampling never picks these three — only the longitudinal engine's escalation path adds them.

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_med_lookup.py -v`
Expected: 5/5 pass (3 original + 2 new).

Run the byte-identity test: `pytest tests/unit/patient/test_e11_activation_byte_identity_phase4a.py -v`
Expected: pass (fixture matches since `probability: 0.0` means zero RNG consumption on these entries).

Ruling (plan author): if `probability: 0.0` entries still shift the RNG cursor by one draw per entry at activation (depends on `_derive_home_medications` sampling order), byte-identity on E11.9 breaks and the test will fail on the first run. In that case the implementer records the new baseline (regenerating the fixture is NOT a bug — Phase 4a is accepted MINOR-track for DM cohorts per Global Constraints) and ledgers the ruling as "P4a shifts E11.9 cursor by 3 draws; non-DM cohorts byte-identical". Non-DM byte-identity (Review Focus #4) is the real gate — tested separately in Task 7.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/chronic_medications.yaml tests/modules/longitudinal/test_med_lookup.py tests/unit/patient/test_e11_activation_byte_identity_phase4a.py
git commit -s -m "feat(meds): add Empagliflozin / Dapagliflozin / Insulin glargine to E11.9 (prob=0 at activation)"
```

---

## Task 7: Integration — DM escalation rate correlates with HbA1c in CIF; non-DM byte-identical

**Files:**
- Create: `tests/integration/test_dm_escalation_in_cif.py`

**Interfaces:**
- Consumes: full longitudinal engine + Phase 1 HbA1c + Phase 4a escalation + CIF writer.
- Produces: cohort-level check — DM patients with sustained HbA1c > 9 accumulate Empagliflozin; patients with sustained HbA1c > 10 accumulate both Empagliflozin AND Insulin glargine; non-DM patients produce byte-identical CIF.

- [ ] **Step 1: Write failing cohort test**

```python
# tests/integration/test_dm_escalation_in_cif.py
# p=200 US seed=42 5y. Extract DM patients from CIF JSON.
# Assertion set:
#   1. At least 10 DM patients (E11.* in chronic_conditions) have
#      "Empagliflozin" in current_medications after 5y.
#   2. Among those 10+, their mean HbA1c across the sim > 9.0.
#   3. At least 3 DM patients have both "Empagliflozin" AND
#      "Insulin glargine" in current_medications — the independent-
#      escalation Review Focus #5 pin.
#   4. Zero non-DM patients (no E11.* code) have Empagliflozin or
#      Insulin glargine in current_medications.
```

Also pin Review Focus #4 (non-DM byte-identity):

```python
def test_non_dm_cohort_byte_identical_pre_phase4a():
    """Review Focus #4: a cohort with zero E11.* patients produces
    byte-identical CIF before and after Phase 4a. Fixture:
    scripts/reproduce.sh gold baseline on a filtered non-DM cohort.
    """
    # Implementation: run generate_cif on a seed/filter pair guaranteed
    # to contain no E11.* chronic. Diff the output against the pre-
    # Phase-4a baseline captured in tests/fixtures/.../non_dm_cohort.json.
    # Byte-for-byte must match.
```

- [ ] **Step 2: Verify failing on pre-fix repo state (RED)**

Expected: zero `Empagliflozin` + `Insulin glargine` in any patient (escalation yamls not yet loaded; the activation sampler has `probability: 0.0`); Review Focus #4 test passes (no change yet).

- [ ] **Step 3: Verify tests pass with Phase 4a wired end-to-end**

Run: `pytest tests/integration/test_dm_escalation_in_cif.py -v`
Expected: 2/2 pass.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_dm_escalation_in_cif.py
git commit -s -m "test(longitudinal): DM escalation CIF integration + non-DM byte-identity"
```

---

## Task 8: CHANGELOG + reproduce.sh + full regression

**Files:**
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: Tasks 1-7.
- Produces: docs complete; CI gates green.

- [ ] **Step 1: Update CHANGELOG.md Unreleased ### Fixed**

Add one bullet (single physical line, NOT hard-wrapped):

```
- **DM patients with HbA1c > 9.0 now escalate to SGLT2i, and > 10.0 to basal insulin, instead of staying on single-agent metformin for 5y** (Issue #1697 — Phase 4a of the longitudinal state-evolution subsystem). The event pattern (Phase 3) is extended with `emits_meds: list[str]` + `fire_marker: str` fields on `EventSpec`, and `clinosim/modules/longitudinal/engine.py` now mutates `PersonRecord.current_medications` directly on fire via a new `clinosim/modules/longitudinal/med_lookup.py` resolver that maps drug names to full `HomeMedication` metadata from `chronic_medications.yaml`. Two new yamls `dm_escalate_sglt2i_e11.yaml` + `dm_escalate_insulin_e11.yaml` fire at HbA1c thresholds 9.0 % and 10.0 % respectively (gated via `operator: "<="` + `factor: 0.0` modifiers so controlled patients never escalate). Three new entries (Empagliflozin / Dapagliflozin / Insulin glargine) under `E11.9` in `clinosim/locale/shared/chronic_medications.yaml` carry `probability: 0.0` so activation sampling never picks them — only the longitudinal escalation path adds them. Clinical basis: ADA Standards of Care in Diabetes 2024, §9 Figure 9.3 pharmacologic intensification pathway. MINOR-track CIF change for DM patients only; non-DM cohorts byte-identical.
```

- [ ] **Step 2: Full project test suite**

Run: `pytest -x tests/modules/longitudinal/ tests/integration/ tests/unit/`
Expected: all green.

- [ ] **Step 3: reproduce.sh gate**

Run: `scripts/reproduce.sh`
Expected: pass (same seed twice → byte-identical).

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -s -m "docs(changelog): Phase 4a DM treatment escalation"
```

---

## Self-review notes (plan author)

**1. Spec coverage.** Spec §4.2.3 names `rate_modifiers` + `emits_icd` + `one_shot`; Phase 3 landed those. Spec §8 Phase 3 includes `dm_treatment_escalation.yaml (metformin → + SGLT2i → + insulin, driven by HbA1c trajectory)` — Phase 4a's scope. The `_annual_chronic_onset` adult-chronic migration also listed under Phase 3 is explicitly deferred to Phase 4b per the Phase 3 plan's §Out of scope and this plan's Architecture section.

**2. Step scan.** Each step produces one artifact: a failing test, a run+expected comparison, a code change against a named signature, or a commit. The one place I used a code block for a body (engine.py Task 4 Step 3) is where the dispatch's "which snapshot field to write" decision isn't inferrable from signatures alone — the Ruling in that step explains why.

**3. Type consistency.** `EventSpec.emits_meds: list[str]` and `fire_marker: str` are defined in Task 1 and consumed by Tasks 2, 4, 5 under the same names. `resolve_med_name(str) -> HomeMedication` defined in Task 3 and called by Task 4. `HomeMedication` field names (`drug_name`, `route`, `dose`, `frequency`) match `clinosim/types/patient.py:145-170`.

**4. Review Focus.** 5 items pinned, each with its owning task listed (Task 2 / 3 / 4 / 7 / 5 respectively). All exercise behaviors not covered by Phase 3 test suite.

**5. Proportion.** Plan is ~15 KB; the code it specifies is ~2 yamls (120 LOC) + ~60 LOC Python + ~200 LOC tests. Ratio reasonable; the plan's bulk is spec references, calibration rationale, and Ruling lines explaining the three plan-author decisions (med_additions dual-use, probability=0 at activation, insulin-independence vs dependency chain).

**Risks the plan accepts (not findings — settled):**

- **Byte-identity for E11.9 cohorts breaks even on `probability: 0.0`.** Task 6's Ruling. Non-DM byte-identity (the Review Focus gate) is tested separately.
- **`snapshot.med_additions` carries fire_marker, not drug names.** Task 4's Ruling. CIF emit resolves back via fire_marker → spec lookup; if awkward, Phase 4b can split into `fired_markers` + `med_names`.
- **Insulin escalation independent of SGLT2i.** Task 5. A patient at HbA1c > 10 escalates both independently — matches ADA 2024 intensification pathway where severe uncontrolled directly initiates insulin without requiring SGLT2i failure first.
