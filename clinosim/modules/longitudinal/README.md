# `clinosim.modules.longitudinal` — year-indexed trajectory engine for patient state

## Purpose

The longitudinal subsystem replaces the pre-#1695 pattern of per-attribute, per-aging-pass trajectory code (`glycemic_trajectory`, `disease_stage_history`, `_advance_glycemic_trajectory`, etc.) with one engine that composes a small number of math patterns against per-attribute yaml declarations. One `YearSnapshot` is written to `PersonRecord.longitudinal_history` per sim year per alive person; per-encounter emit sites read the year-matched snapshot through `state_at` to produce lab / stage / medication values that evolve across the sim's time span.

Phase 1 shipped the engine plus the first attribute (HbA1c, AR(1)). Later phases added Markov stage transitions (CKD / COPD / heart failure / IHD / dementia / liver / Parkinson / AF / MS / stroke sequela / cancer stage), event firing (adult chronic-condition onset, DM complication onset, treatment escalation) and further AR(1) latents (BMI drift, LDL, SBP); all three patterns are live.

## Scope

- **In scope**: `YearSnapshot` dataclass, three trajectory patterns (AR(1) continuous, Markov stage transition, event firing), per-attribute yaml loader + DAG topological sort, `advance_one_year` / `state_at` / `initial_snapshot` entry points, Layer-1 seeding + aging-driver integration.
- **Out of scope**: per-encounter sub-year interpolation (Phase-4 extension if ever); community mortality (drawn once per person per year in `population.aging.advance_population` via `population.mortality`); pediatric growth-chart (handled by `anthropometric_reference.yaml` + the per-encounter FHIR anthropometric emit).

## Public API

```python
from clinosim.modules.longitudinal import (
    YearSnapshot,           # per-year state container
    advance_one_year,       # (person, year, year_rng) -> new YearSnapshot
    state_at,               # (person, when) -> YearSnapshot
    initial_snapshot,       # (person, year, init_rng) -> first YearSnapshot
    yearsnapshot_from_dict, # dict -> YearSnapshot (deserialisation helper)
)
```

Internals under `patterns/` (`ar1.py`, `markov.py`, `event.py`, dispatched through `PATTERN_REGISTRY`), `loader.py` (yaml → `AttributeSpec`), `med_lookup.py` (event `emits_meds` drug name → `HomeMedication` from `chronic_medications.yaml`), and `snapshot.py` (dataclass + serialisation) are not part of the public surface — the engine's three entry points are the stable contract.

## Determinism

- Each year, the engine is called with a single `np.random.Generator` passed by `advance_population` and `generate_population`. Draws per attribute execute in topological order of `depends_on` edges. Event yamls flagged `rng_isolated: true` draw from their own `seeding.longitudinal_event_seed(person_id, year, event_name)` generator instead of the shared per-person-year stream; base home meds added for a newly acquired ICD use the patient-scoped `chronic_medication_seed`.
- `aging_sub_seed(person_id, year, "longitudinal")` seeds the per-person per-year generator for `advance_one_year`; `aging_sub_seed(person_id, base_year, "longitudinal:init")` seeds the Layer-1 `initial_snapshot` call.
- `state_at(person, when)` is pure (no RNG; scans `longitudinal_history` for the matching year and raises `IndexError` when absent).
- `advance_one_year` raises `ValueError` on empty history, duplicate year or backward year; forward year gaps are permitted.

## Dependencies

- `clinosim.modules.longitudinal.patterns` — the pattern registry.
- `clinosim.modules.longitudinal.loader` — yaml → `AttributeSpec`.
- `clinosim.types.population.PersonRecord` — the mutation target.
- `clinosim.locale.shared.longitudinal/` — per-attribute yaml data.
- `pydantic` — yaml schema validation.
- `numpy` — RNG + math.

## Data files

Per-attribute yaml under `clinosim/locale/shared/longitudinal/` (the loader globs `*.yaml` recursively):

- `hba1c_trajectory.yaml` — AR(1) HbA1c latent for E11 / E10 adults; literature-calibrated against DCCT/EDIC, ADVANCE, Wu 2023 meta-analysis. See the yaml's `source:` block.
- `anthropometry/bmi_drift.yaml`, `labs/ldl_trajectory.yaml`, `vitals/sbp_trajectory.yaml` — further AR(1) latents.
- `stage/*.yaml` — 19 Markov stage attributes.
- `event/*.yaml` — 35 event attributes (32 `*_onset.yaml` chronic-onset events + 3 DM complication events).
- `med/*.yaml` — 6 treatment-escalation events (DM / HTN / lipid).

## Caller integration

- `clinosim.modules.population.engine.generate_population` — calls `initial_snapshot` for every alive person at Layer-1 generation.
- `clinosim.modules.population.aging.advance_population` — calls `advance_one_year` once per alive person per year (with `multiplier_fn=_comorbidity_multiplier` for Markov rates), after the community-mortality draw and the remaining aging passes.
- `clinosim.modules.physiology.engine.derive_lab_values` — reads `hba1c_latent` from `state_at(person, when).continuous["hba1c"]` and applies the per-encounter measurement-noise overlay (sigma 0.20 % from the yaml).
- `clinosim.modules.patient.activator._derive_chronic_conditions` — reads HbA1c from the current year's snapshot to build the DM stage string.

## Related modules

- `clinosim.modules.population.aging` — hosts the remaining aging passes (`_stroke_sequela_promotion`, `_allergy_drift`) and the community-mortality draw (`population.mortality.draw_community_death`); the former `_annual_chronic_onset` / `_disease_progression` passes now run as event / Markov attributes in this engine.
- `clinosim.modules.physiology.engine` — HbA1c + glucose emit path.
- `clinosim.modules.patient.activator` — Layer-2 PatientProfile build.

## Testing

- `tests/modules/longitudinal/test_year_snapshot_serialisation.py` — YearSnapshot dataclass round-trip.
- `tests/modules/longitudinal/test_ar1_step_math.py` — AR(1) math (stationarity, clamp, lognormal initial).
- `tests/modules/longitudinal/test_loader_dependency_sort.py` — loader + DAG.
- `tests/modules/longitudinal/test_engine.py` + `test_state_at_lookup.py` — entry points.
- `tests/modules/longitudinal/test_hba1c_physiological_bounds.py` — RBC-lifespan smoothness sweep.
- `tests/modules/longitudinal/test_layer1_initial_snapshot.py` — Layer-1 wiring.
- `tests/modules/longitudinal/test_aging_integration.py` — aging-driver wiring.
- `tests/modules/longitudinal/test_physiology_hba1c_emit.py` — physiology.engine HbA1c migration.
- `tests/modules/longitudinal/test_activator_dm_stage.py` — activator stage-string migration.
- `tests/modules/longitudinal/test_glycemic_control_retirement.py` — sweep gate.
- Later-phase coverage (39 test files in total) includes `test_markov_step.py`, `test_event_step.py`, `test_engine_markov_dispatch.py`, `test_engine_event_dispatch.py`, `test_engine_med_dispatch.py`, `test_med_lookup.py` and the `test_*_yamls_load.py` schema gates.

## Design document

See [`docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md`](../../../docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md) for the full phased architecture (Phase 1 AR(1), Phase 2 Markov, Phase 3 event).
