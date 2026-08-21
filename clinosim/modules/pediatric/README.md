# `clinosim.modules.pediatric` — pediatric encounter emission

## Purpose

Emits pediatric encounters (well-child visits, immunization visits,
pediatric acute, adolescent behavioural) into a person's yearly
healthcare calendar based on their age. Addresses Issue #760 META:
the population sampler correctly matches US Census under-20 age
weights, but adults dominate the emitted cohort because the
adult-oriented disease incidence YAMLs rarely fire for pediatric
patients. This module fills the gap at the **encounter-emission
layer** by adding a per-age-band pediatric visit schedule.

## Scope

- **In scope**: loading the pediatric encounter registry YAML,
  validating its schema at load time, and generating `LifeEvent`
  records for a given (person, year) pair using a caller-supplied
  per-person sub-RNG. Currently registered encounter families:
  well-child (infant / early / school), immunization (infant /
  kindergarten / adolescent), pediatric acute (bronchiolitis,
  otitis media, URI × 3 age bands), pediatric injury (school /
  adolescent), pediatric behavioural (adolescent).
- **Out of scope**: neonatal ICU-level physiology (separate campaign),
  the adult encounter engine itself (this module plugs in via the
  existing population calendar loop), disease specifications for
  the emitted `disease_id` values (each maps to its own YAML under
  [`clinosim.modules.disease`](../disease/README.md)).

## Public API

`__init__.py` is a doc string only. Consumers import the two
functions directly from `calendar`:

```python
from clinosim.modules.pediatric.calendar import (
    load_pediatric_schedule,     # (path=None) -> {encounter_key: entry_dict}
    generate_pediatric_events,   # (person, year, prng, schedule=None) -> list[LifeEvent]
)
```

`load_pediatric_schedule` validates the file at load time and raises
`ValueError` on any schema violation (missing required field,
non-list `visits_per_year`, `age_min > age_max`, non-dict `encounters`
top-level). `generate_pediatric_events` no-ops when the schedule is
empty or the person's age falls outside every entry's band.

## Determinism

- The module uses **no master RNG**. `generate_pediatric_events`
  accepts a caller-supplied `prng` (the per-person spawned
  `np.random.Generator` already used by
  `generate_healthcare_calendar`), so YAML edits shift only the
  affected pediatric patients' downstream stream position — never
  unrelated adults.
- `load_pediatric_schedule` intentionally has **no `@lru_cache`** —
  it stays hot-reload friendly for tests. Callers that care about
  repeated cost can cache the result themselves.

## Dependencies

- `numpy` — `np.random.Generator` (`prng.choice`, `prng.integers`).
- `yaml` — YAML parser.
- `clinosim.modules.population.engine` — `LifeEvent` (imported
  lazily inside `generate_pediatric_events`).
- No dependency on any other `clinosim.modules.*` at import time.

## Constants and configuration

[`reference_data/pediatric_schedule.yaml`](reference_data/pediatric_schedule.yaml)
carries every registered encounter under a single `encounters:` map.
Each entry:

| Key | Meaning |
|---|---|
| `age_min` | Inclusive lower bound (years). |
| `age_max` | Inclusive upper bound (years). |
| `visits_per_year` | Non-empty `list[int]` — uniformly sampled per patient per year to give inter-patient variance. |
| `encounter_type` | `"outpatient"` / `"emergency"` / `"inpatient"` — dispatch key for the engine. |
| `disease_id` | Reused by the engine's dispatch to identify the visit's clinical protocol. |
| `visit_reason` | Human-readable, emitted as the encounter's chief complaint. |

Extending the schedule is a **pure YAML edit** — no code changes
required. Adding a bad entry surfaces at load time as `ValueError`.

## Directory contents

```
clinosim/modules/pediatric/
  __init__.py                     package docstring only
  calendar.py                     load_pediatric_schedule + generate_pediatric_events
  reference_data/
    pediatric_schedule.yaml       registered encounter entries
```

The module has **no `engine.py`, no `enricher.py`, and no `audit.py`**.
It is not registered with `register_builtin_enrichers` and has no
seed offset in `ENRICHER_SEED_OFFSETS` — it hooks into the population
calendar loop instead.

## Enricher wiring

Not applicable — this module hooks into the population calendar loop
directly instead of registering an enricher. It has no entry in
`register_builtin_enrichers` and no seed offset in
`ENRICHER_SEED_OFFSETS`.

Integration lives in
[`clinosim/modules/population/engine.py`](../population/engine.py)
(`~L807-815`):
`generate_healthcare_calendar` calls `generate_pediatric_events` with
the per-person spawned `prng`, and the returned `LifeEvent` list is
merged into the calendar `events` list. The rest of the pipeline
treats pediatric events like any other calendar event.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Population calendar loop | [`clinosim/modules/population/engine.py`](../population/engine.py) (`~L807-815`, inside `generate_healthcare_calendar`) | Calls `generate_pediatric_events(person, year, prng)` per (person, year) and extends the calendar's `events` list with the returned `LifeEvent` records. |
| Encounter engine dispatch | [`clinosim.modules.encounter`](../encounter/README.md) | Reads `LifeEvent.encounter_type` / `disease_id` / `protocol_source` (prefix `"pediatric:"`) to identify pediatric visits at encounter build time. |

## Testing

```bash
pytest tests/unit/test_pediatric_calendar.py -q
```

Covers: loader schema validation (empty schedule round-trips,
malformed entries fail loud) and `generate_pediatric_events` behaviour
(no-op on empty schedule, correct event count when the schedule has
matching entries).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
