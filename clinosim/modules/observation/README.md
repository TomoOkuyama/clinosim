# `clinosim.modules.observation` — laboratory and vital-sign generation

## Purpose

Turns an order for a lab test or vital-sign measurement into a
concrete result value that reflects the patient's current physiology
state, disease-specific reference ranges, and (for JP) locale-
appropriate reference bands.

## Scope

- **In scope**: lab-value generation from physiology state, vital-sign
  generation (heart rate / respiratory rate / SpO2 / temperature /
  blood pressure), microbiology culture result formation, LOINC /
  JLAC10 coding of results, nursing enricher for NEWS2 / fluid-
  balance / oxygen-delivery derived fields.
- **Out of scope**: order *placement* (in
  [`clinosim.modules.order`](../order/README.md)), physiology-state
  updates (in
  [`clinosim.modules.physiology`](../physiology/README.md)), FHIR
  serialisation (in [`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.observation import (
    generate_lab_result,         # (order, state, rng) -> ObservationResult
    generate_vital_signs,        # (order, state, rng) -> list[VitalSignRecord]
    enrich_observations,         # AD-56 post_records enricher entry
)
from clinosim.modules.observation.microbiology import (
    antibiotic_loinc_lookup,     # single source of truth for antibiotic LOINC
    generate_microbiology_result,
)
```

## Dependencies

- `clinosim.types.encounter` — `Order`, `ObservationResult`,
  `VitalSignRecord`.
- `clinosim.types.microbiology` — `MicrobiologyResult`, `Specimen`.
- `clinosim.types.clinical` — `PhysiologicalState`.
- `clinosim.codes` (via FHIR builder) — LOINC / SNOMED / JLAC10
  display lookup.
- `clinosim.locale` — country-specific reference ranges.

## Constants and configuration

- Vital-sign reference / critical bounds are currently positional
  tuples in `observations.py` — one of the three high-leverage
  hotspots identified in
  [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md)
  (Hotspot B).
- Lab reference ranges are sourced from JCCLS 共用基準範囲 2022 (JP)
  and Tietz Clinical Guide (US); values live in
  `clinosim/locale/{jp,us}/reference_range_lab.yaml`.
- `vitals_thresholds.py` — compliant `_thresholds`-style file that
  can serve as a model for the pending Hotspot-B extraction.
- Microbiology reference data (organism prevalences by specimen,
  antibiogram susceptibility rates) lives in
  `reference_data/microbiology.yaml`.

## Directory contents

```
clinosim/modules/observation/
  __init__.py           public API
  engine.py             lab-value generation dispatcher
  observations.py       core lab / vital derivation (Hotspot B)
  microbiology.py       culture-result formation + LOINC lookups
  vitals_thresholds.py  vital-sign threshold constants (compliant model)
  fluid_balance.py      fluid-balance derived observations
  nursing_enricher.py   NEWS2 / oxygen-delivery enrichment
  audit.py              per-module audit spec
  reference_data/
    microbiology.yaml   organism / antibiogram data
```

## Testing

```bash
pytest tests/unit -k observation -q
pytest tests/integration -k observation -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
