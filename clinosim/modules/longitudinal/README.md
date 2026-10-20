# `clinosim.modules.longitudinal` — year-indexed trajectory engine for patient state

## Purpose

The longitudinal subsystem replaces the pre-#1695 pattern of per-attribute, per-aging-pass trajectory code (`glycemic_trajectory`, `disease_stage_history`, `_advance_glycemic_trajectory`, etc.) with one engine that composes a small number of math patterns against per-attribute yaml declarations. One `YearSnapshot` is written to `PersonRecord.longitudinal_history` per sim year per alive person; per-encounter emit sites read the year-matched snapshot through `state_at` to produce lab / stage / medication values that evolve across the sim's time span.

Phase 1 ships the engine plus the first attribute (HbA1c, AR(1)). Phase 2 adds Markov transitions (CKD / CCS / NYHA / CDR / GOLD); Phase 3 adds event firing (DM complication onset, treatment escalation, BMI drift).

## Scope

- **In scope**: `YearSnapshot` dataclass, three trajectory patterns (AR(1) continuous, Markov stage transition, event firing), per-attribute yaml loader + DAG topological sort, `advance_one_year` / `state_at` / `initial_snapshot` entry points, Layer-1 seeding + aging-driver integration.
- **Out of scope**: per-encounter sub-year interpolation (Phase-4 extension if ever); mortality trajectory (stays in `aging._condition_reactive_mortality`); pediatric growth-chart (handled by `anthropometric_reference.yaml` + the per-encounter FHIR anthropometric emit).

## Public API

```python
from clinosim.modules.longitudinal import (
    YearSnapshot,           # per-year state container
    advance_one_year,       # (person, year, year_rng) -> new YearSnapshot
    state_at,               # (person, when) -> YearSnapshot
    initial_snapshot,       # (person, year, init_rng) -> first YearSnapshot
)
```

Internals under `patterns/` (AR(1) in Phase 1), `loader.py` (yaml → `AttributeSpec`), and `snapshot.py` (dataclass + serialisation) are not part of the public surface — the engine's three entry points are the stable contract.

## Determinism

- Each year, the engine is called with a single `np.random.Generator` passed by `advance_population` and `generate_population`. Draws per attribute execute in topological order of `depends_on` edges; no internal sub-seed namespace is used in Phase 1.
- `aging_sub_seed(person_id, year, "longitudinal")` seeds the per-person per-year generator for `advance_one_year`; `aging_sub_seed(person_id, base_year, "longitudinal:init")` seeds the Layer-1 `initial_snapshot` call.
- `state_at(person, when)` is pure (no RNG, O(1) lookup by year).
- `advance_one_year` raises on duplicate or backward year — the monotonicity invariant is upheld in the caller.

## Dependencies

- `clinosim.modules.longitudinal.patterns` — the pattern registry.
- `clinosim.modules.longitudinal.loader` — yaml → `AttributeSpec`.
- `clinosim.types.population.PersonRecord` — the mutation target.
- `clinosim.locale.shared.longitudinal/` — per-attribute yaml data.
- `pydantic` — yaml schema validation.
- `numpy` — RNG + math.

## Data files

Per-attribute yaml under `clinosim/locale/shared/longitudinal/`:

- `hba1c_trajectory.yaml` — AR(1) HbA1c latent for E11 / E10 adults; literature-calibrated against DCCT/EDIC, ADVANCE, Wu 2023 meta-analysis. See the yaml's `source:` block.

Phase 2 / 3 attributes land their own yamls here; the loader globs all `*.yaml` files.

## Caller integration

- `clinosim.modules.population.engine.generate_population` — calls `initial_snapshot` for every alive person at Layer-1 generation.
- `clinosim.modules.population.aging.advance_population` — calls `advance_one_year` once per alive person per year, after the existing aging passes finalise chronic_conditions.
- `clinosim.modules.physiology.engine.derive_lab_values` — reads `hba1c_latent` from `state_at(person, when).continuous["hba1c"]` and applies the per-encounter measurement-noise overlay (sigma 0.20 % from the yaml).
- `clinosim.modules.patient.activator._derive_chronic_conditions` — reads HbA1c from the current year's snapshot to build the DM stage string.

## Related modules

- `clinosim.modules.population.aging` — hosts the sibling non-DM aging passes (`_annual_chronic_onset`, `_stroke_sequela_promotion`, `_disease_progression`, `_allergy_drift`, `_condition_reactive_mortality`).
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

## Design document

See [`docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md`](../../../docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md) for the full phased architecture (Phase 1 shipping, Phase 2 Markov, Phase 3 event).
