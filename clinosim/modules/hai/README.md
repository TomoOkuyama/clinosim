# `clinosim.modules.hai` — healthcare-associated infection (CLABSI / CAUTI / VAP) sampling

## Purpose

Opt-in Module (AD-55) that consumes `extensions["device"]` from
[`clinosim.modules.device`](../device/README.md), samples the incidence
of CLABSI (central-line-associated bloodstream infection), CAUTI
(catheter-associated urinary-tract infection), and VAP (ventilator-
associated pneumonia) using **CDC NHSN baseline per-line-day risk
rates**, and emits FHIR `Condition` plus a culture chain (`Specimen` +
`Observation` + `DiagnosticReport`).

Establishes the first cross-module dependency point in the device / HAI
4-PR series: HAI reads `extensions["device"]` and never writes back
(one-way boundary).

## Scope

- **In scope**: per-device line-days walk, per-device × per-HAI-type
  probability sampling, HAI onset date determination (CDC ≥ 48 h HAI
  definition — `onset_offset ≥ 2`), organism sampling from CDC NHSN
  distributions, `HAIEvent` and `MicrobiologyResult` emission.
- **Out of scope**: peripheral-IV-associated bacteraemia (device module
  excludes peripheral IVs), susceptibility (S / I / R) modelling
  (Phase 3b-2 follow-up), antibiotic prescribing (in
  [`clinosim.modules.antibiotic`](../antibiotic/README.md)), FHIR
  serialisation for the culture chain (already handled by the existing
  microbiology output builder — no new builder needed).

## Public API

```python
from clinosim.modules.hai import (
    HAI_TYPES,                       # ("CLABSI", "CAUTI", "VAP")
    sample_hai_events_for_encounter, # (record, encounter, rng, config) -> list[HAIEvent]
    enrich_hai,                      # AD-56 post_records enricher entry
)
```

## Rates and organisms

Per-line-day baseline rates (per 2015-2019 CDC NHSN benchmark; see
`reference_data/hai_rates.yaml` for cited source):

| HAI type | Baseline rate |
|---|---|
| CLABSI | ~0.0010 – 0.0015 per line-day |
| CAUTI | ~0.0015 per catheter-day |
| VAP | ~0.0010 per ventilator-day |

Organism distributions per HAI type (top pathogens, CDC NHSN
2015-2020): `reference_data/hai_organisms.yaml`.

## Dependencies

- `clinosim.types.hai` — `HAIEvent`.
- `clinosim.types.microbiology` — `MicrobiologyResult`, `Specimen`.
- `clinosim.types.encounter` — `Encounter`.
- `clinosim.types.output` — `CIFPatientRecord`.
- `clinosim.modules.device` (upstream only) — reads
  `extensions["device"]`.
- `clinosim.codes` (via FHIR builder) — ICD-10-CM (billable US) +
  WHO ICD-10 (4-char, JP) + SNOMED code lookup.
- `clinosim.simulator.helpers` (formerly `seeding`) —
  `ENRICHER_SEED_OFFSETS["hai"] = 0x4841`, `derive_sub_seed`.

## Constants and configuration

- `ENRICHER_SEED_OFFSETS["hai"] = 0x4841` (`"HA"`) — sub-seed offset.
- CDC ≥ 48 h HAI definition — enforced in `sample_hai_onset`
  (`onset_offset ≥ 2`).
- All per-day risk rates, organism distributions, ICD / SNOMED coding,
  and CDC NHSN susceptibility rates live in `reference_data/*.yaml`;
  no rate is hard-coded in engine code.

## Directory contents

```
clinosim/modules/hai/
  __init__.py            public API
  engine.py              pure functions (sampling + organism + date arithmetic)
  enricher.py            AD-56 post_records enricher (enrich_hai)
  audit.py               per-module audit spec
  reference_data/
    hai_rates.yaml        CDC NHSN per-line-day risk rates
    hai_codes.yaml        ICD-10-CM + WHO ICD-10 + SNOMED
    hai_organisms.yaml    CDC NHSN top organism distributions per HAI type
    hai_specimens.yaml    Specimen SNOMED + culture LOINC per HAI type
    hai_antibiogram.yaml  CDC NHSN AR 2018-2020 susceptibility rates (Phase 3b-2)
```

## Testing

```bash
pytest tests/unit -k hai -q
pytest tests/integration -k hai -q
```

## Related

- [DESIGN.md](../../../DESIGN.md) AD-55 / AD-56 / AD-57.
- Upstream: [`clinosim/modules/device/`](../device/README.md).
- Downstream: [`clinosim/modules/antibiotic/`](../antibiotic/README.md)
  materialises empirical regimens for the HAI events emitted here.
- [`docs/CONTRIBUTING-modules.md`](../../../docs/CONTRIBUTING-modules.md).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
