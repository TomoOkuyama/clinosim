# `clinosim.modules.clinical_course` — clinical trajectory engine

## Purpose

Models the **temporal progression** of a disease from admission to
discharge (or death). Where the
[`physiology`](../physiology/README.md) module holds the *current*
state, `clinical_course` decides *how the state should move on the
next day* by producing a `StateChangeDirective`.

This split lets clinosim generate:

- Different trajectories for the same disease across patients (smooth
  recovery / treatment resistant / sudden deterioration, etc.).
- Individual variation across age, immune reactivity, treatment
  sensitivity, reflected in the time axis.
- Diagnostic-correctness effects on treatment efficacy — a misdiagnosis
  leaves footprints such as prolonged CRP.
- Probabilistic complications (DVT, AKI, delirium, …) that cascade.
- Treatment-independent natural recovery (innate immune response).

## Scope

- **In scope**: day-by-day trajectory selection per disease and
  patient, six archetype models (smooth_recovery / dip_then_recovery /
  plateau_then_recovery / treatment_resistant / gradual_deterioration
  / sudden_deterioration), archetype-modifier adjustments per patient
  characteristic, complication sampling.
- **Out of scope**: the physiology state itself (in
  [`physiology`](../physiology/README.md)), the disease definitions
  (in [`disease`](../disease/README.md)), medication effects on state
  (in [`medication_pipeline`](../../simulator/README.md) and
  physiology).

## Public API

```python
from clinosim.modules.clinical_course import (
    ARCHETYPE_EXPRESSION_VARS,   # frozenset of allowed archetype-selection expression vars
    select_archetype,            # (protocol, patient, rng) -> ArchetypeSelection
    advance_state,               # (state, directive) -> new_state
    sample_complications,        # (state, day, rng) -> list[Complication]
)
```

## Design principles

- **YAML-driven with fallback** — per-disease trajectory definitions
  live in the disease YAML `course_archetypes` block; a built-in
  fallback covers diseases with no archetype block.
- **Six archetypes** — `smooth_recovery`, `dip_then_recovery`,
  `plateau_then_recovery`, `treatment_resistant`,
  `gradual_deterioration`, `sudden_deterioration`.
- **Deterministic (AD-16)** — patient-scoped sub-seed drives archetype
  selection and complication sampling.
- **Archetype modifiers** — per-patient traits (age, immune reactivity,
  treatment sensitivity) shift the archetype probability distribution.
- **Diagnostic-correctness aware** — misdiagnosis reduces the
  probability of `smooth_recovery` and increases
  `treatment_resistant` / `plateau_then_recovery`.

## Dependencies

- `clinosim.types.clinical` — `PhysiologicalState`.
- `clinosim.types.patient` — `PatientProfile`.
- `clinosim.types.encounter` — day-count arithmetic.
- `clinosim.modules.disease` — `DiseaseProtocol` and its
  `course_archetypes` block.

## Constants and configuration

- `ARCHETYPE_EXPRESSION_VARS` — the frozenset of variable names that
  archetype-selection expressions may reference. Extending this set is
  a public-API change; existing entries are covered by
  `tests/unit/modules/clinical_course/test_archetype_modifiers.py`.
- Archetype-modifier weights, complication onset probabilities, and
  timing curves are currently inline and flagged for extraction in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).

## Directory contents

```
clinosim/modules/clinical_course/
  __init__.py           public API
  engine.py             archetype selection + state-advance + complications
  audit.py              per-module audit spec
  reference_data/       archetype and complication reference data
```

## Testing

```bash
pytest tests/unit -k clinical_course -q
pytest tests/integration -k clinical_course -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
