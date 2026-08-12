# clinosim.modules.pediatric

Age-band-driven pediatric encounter emission (Issue [#760](https://github.com/TomoOkuyama/clinosim/issues/760) META). Fills the gap
identified by [#740](https://github.com/TomoOkuyama/clinosim/issues/740):
the cohort's under-20 patient share (5% in the US baseline) reflects
"who reached an encounter" rather than the sampled demographics — and
pediatric persons rarely reach the encounter gate because the disease /
incidence YAMLs have very low rates for pediatric-eligible conditions.

The population-sampler weights were confirmed correct
(`age_distribution` matches US Census 2020); the fix belongs at the
**encounter-emission layer**. This module adds pediatric encounter types
the simulator does not currently produce (well-child, immunization,
pediatric acute, adolescent behavioural), each backed by a per-age-band
frequency table.

## Foundation (pass 1 — the state shipped in this file)

- Module scaffold + YAML loader + integration point in
  `clinosim/modules/population/engine.py::generate_healthcare_calendar`.
- **Byte-diff neutral**: with no encounter types registered in
  `reference_data/pediatric_schedule.yaml`, no events are emitted and
  cohort output is bit-identical to pre-module runs.

## Follow-up passes

Per META [#760](https://github.com/TomoOkuyama/clinosim/issues/760):

- **Pass 2** — well-child visits (0-18, 1/yr routine + 6-8/yr infants per AAP schedule).
- **Pass 3** — immunization visits (0-18, ~5 in year-1 + 1-2/yr thereafter).
- **Pass 4** — pediatric acute (bronchiolitis / pneumonia / otitis media / URI fever).
- **Pass 5** — injury (playground / MVA passenger, age 5-18) + adolescent behavioural health (12-18).

Each pass is a pure YAML edit under the schema documented below and one
follow-up regen check for the cohort delta.

## YAML schema (evolving; empty in this pass)

`reference_data/pediatric_schedule.yaml`:

```yaml
encounters:
  well_child_infant:                       # canonical encounter-type key
    age_min: 0                             # inclusive (years)
    age_max: 1                             # inclusive
    visits_per_year: [6, 7, 8]             # sampled uniformly per year per patient
    encounter_type: "outpatient"           # dispatch key for engine.py
    disease_id: "well_child_infant"        # follows the health_screening dispatch pattern
    visit_reason: "Well-child visit — infant"
```

Empty top-level `encounters:` block → no events emitted (foundation
default). Adding entries triggers per-patient event generation in
`calendar.generate_pediatric_events`.

## RNG isolation

`generate_pediatric_events(person, year, prng)` accepts a per-person
sub-RNG spawned in the caller (`generate_healthcare_calendar`'s existing
per-person `prng.spawn(1)[0]` pattern), so master RNG is untouched and
adding encounter types shifts only the affected pediatric patients'
downstream stream position — not unrelated adults.

## Success criteria (per META #760, when to close)

- Emitted US cohort age distribution ≥12% under-20 (currently 5%),
  matching NAMCS 2016 ambulatory-visit distribution.
- `Patient.birthDate` demographic realism preserved (no change to
  `demographics.yaml age_distribution`).
- Well-child + immunization encounter counts non-zero for every
  pediatric patient (0-18).

## Tests

`tests/unit/test_pediatric_calendar.py` covers: YAML loader validation
(empty schema round-trips, malformed entries fail loud), event
generation is a no-op when the schema is empty, event count matches
schema when a mapping is present (pass 2+ will extend this).

## Non-goals (per META #760)

- Modeling neonatal ICU-level physiology (separate high-fidelity campaign).
- Perfect real-world pediatric care-utilization fidelity (goal is ±50%,
  not ±5%; simulator is synthetic).
- Restructuring the adult encounter engine — pediatric emission plugs
  into the existing engine's calendar loop.
