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

`__init__.py` is a doc string only (`__all__ = []`). Consumers import
directly from `calendar`:

```python
from clinosim.modules.pediatric.calendar import (
    load_pediatric_schedule,     # (path=None) -> {encounter_key: entry_dict}
    generate_pediatric_events,   # (person, year, prng, schedule=None, *, country: str | None) -> list[LifeEvent]
    place_vaccination_visit,     # vaccination-visit day inside a dose window (Issue #2974)
    pediatric_presentation,      # (visit_id) -> Presentation | None (acute visits only)
    Presentation,                # pydantic model of one acute-visit clinical picture
)
```

`pediatric_presentation(disease_id)` returns the acute visit's
`Presentation` (or `None` for a preventive visit); the outpatient
simulator uses it to pick the visit's vitals, a stream-free
febrile / afebrile state (`Presentation.visit_state`, SHA Bernoulli on
the encounter id), the matching state-variable impact, and the
take-home prescriptions.

`load_pediatric_schedule` validates the file at load time and raises
`ValueError` on any schema violation (missing required field among
`age_min` / `age_max` / `visits_per_year` / `encounter_type` /
`disease_id`, non-list or empty `visits_per_year`, `age_min > age_max`,
non-dict `encounters` top-level). `generate_pediatric_events` computes
age-at-year as `year - date_of_birth.year` (falls back to the static
`person.age`) and returns `[]` when the schedule is empty, the age is
`> 18` or `< 0` (not yet born), or a per-person participation draw
`prng.random() < person.care_seeking_threshold` (default 0.20) skips
the whole year (Issue #922). Each matching entry emits
`LifeEvent(event_type="pediatric_visit", severity=0.0,
condition_type="pediatric", protocol_source="pediatric:<key>")`
visits spaced evenly across the year with a day-of-month jitter.

## Determinism

- The module uses **no master RNG**. `generate_pediatric_events`
  accepts a caller-supplied `prng` (the per-person spawned
  `np.random.Generator` already used by
  `generate_healthcare_calendar`), so YAML edits shift only the
  affected pediatric patients' downstream stream position — never
  unrelated adults.
- `load_pediatric_schedule` is cached with `@lru_cache(maxsize=8)`
  per `path` argument (it was previously uncached and hot in the
  per-patient calendar loop). Tests that mutate the schedule file
  invalidate it with `load_pediatric_schedule.cache_clear()`.

## Dependencies

- `numpy` — `np.random.Generator` (`prng.random`, `prng.choice`,
  `prng.integers`).
- `pydantic` — `_PediatricSchedule` / `_Visit` schedule models.
- `clinosim.datafiles` — `load_data_yaml`.
- `clinosim.modules._shared` — `random_day_of_month` (per-visit
  day-of-month jitter).
- `clinosim.modules.population.engine` — `LifeEvent` (imported
  lazily inside `generate_pediatric_events`).

## Constants and configuration

[`reference_data/pediatric_schedule.yaml`](reference_data/pediatric_schedule.yaml)
carries every registered encounter under an `encounters:` map and the
clinical picture of the acute visits under a `presentations:` map.
Each `encounters:` entry:

| Key | Meaning |
|---|---|
| `age_min` | Inclusive lower bound (years). |
| `age_max` | Inclusive upper bound (years). |
| `visits_per_year` | Non-empty `list[int]` — uniformly sampled per patient per year to give inter-patient variance. |
| `encounter_type` | Must be `"outpatient"` (the model rejects any other value) — copied onto `LifeEvent.encounter_type`. |
| `disease_id` | Copied onto `LifeEvent.disease_id`; used for department resolution and the visit-reason lookup. |
| `visit_reason` | Optional. Bilingual `{en, ja}` dict or string, read by `simulator/_setup.py::_pediatric_visit_reason` and emitted as the encounter's chief complaint. |
| `vaccination` | Optional, default `false`. A visit held to give vaccines (reason Z23). With a country, `generate_pediatric_events` moves it inside a series dose window of that country's immunization schedule that opens in the year and overlaps the age band (the day nearest the drawn date), and drops it when no window opens, so the visit always has a dose due (`place_vaccination_visit`, Issue #2974). Draws are unchanged. |
| `min_age_days` | Optional, default `0`. Youngest age in days at the visit: a visit drawn earlier is dropped (the draws are unchanged). The acute-illness entries open to infants (URI, otitis media, bronchiolitis) set `29`: a febrile infant of 28 days or less is admitted for a sepsis workup (AAP 2021 febrile infant guideline), not seen as an outpatient cold (Issue #2978). |

Each `presentations:` entry is keyed by an `encounters:` `disease_id`
(an unknown key fails at load):

| Key | Meaning |
|---|---|
| `vitals` | Non-empty list of vital fields measured at the visit. |
| `febrile_probability` | Probability (0–1) that the visit is febrile; > 0 requires a `state_impact.febrile` block. |
| `state_impact` | Optional `{febrile, afebrile}` → `{state_var: delta}`; state-variable names must be canonical physiology state vars. |
| `pulmonary_involvement` | Required. Whether the illness involves the lung, so its inflammation lowers SpO2 (bronchiolitis `true`; URI, otitis media and injury `false`, so a child with a febrile URI keeps a normal SpO2 — Issue #2987). |
| `prescriptions` | Optional list of take-home items: `drug_id` (must be in the drug catalog), `dose`, `route`, `frequency`, `duration_days` (age band → positive day count). |

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
(`generate_healthcare_calendar`):
`generate_healthcare_calendar` calls `generate_pediatric_events` with
the per-person spawned `prng` and the cohort country, and the returned `LifeEvent` list is
merged into the calendar `events` list. The rest of the pipeline
treats pediatric events like any other calendar event.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Population calendar loop | [`clinosim/modules/population/engine.py`](../population/engine.py) (inside `generate_healthcare_calendar`) | Calls `generate_pediatric_events(person, year, prng, country=country)` per (person, year) and extends the calendar's `events` list with the returned `LifeEvent` records. |
| Healthcare-calendar dispatch | [`clinosim/simulator/phases/_healthcare_calendar.py`](../../simulator/phases/_healthcare_calendar.py) | Routes `event_type == "pediatric_visit"` to an outpatient visit (department via `resolve_outpatient_department`, chief complaint via `_pediatric_visit_reason(disease_id)`). |
| Visit-reason lookup | [`clinosim/simulator/_setup.py`](../../simulator/_setup.py) (`_pediatric_visit_reason`) | Reads `visit_reason` from `load_pediatric_schedule()`. |
| Outpatient encounter | [`clinosim/simulator/outpatient.py`](../../simulator/outpatient.py), [`outpatient_dept.py`](../../simulator/outpatient_dept.py) | `visit_type == "pediatric_visit"` branches; `pediatric_presentation` supplies the acute visit's vitals, febrile state and prescriptions. |

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
