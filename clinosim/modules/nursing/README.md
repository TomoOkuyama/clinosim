# `clinosim.modules.nursing` — nursing assessments and workflow

## Purpose

Generates nursing-specific data attached to inpatient / ICU / rehab-
inpatient encounters: primary-nurse assignment, ADL scoring (Barthel),
risk assessments (Braden pressure-ulcer scale, Morse fall scale, NEWS2
early-warning score), and per-disease nursing-focus scaffolding.

## Scope

- **In scope**: `assign_primary_nurse` (uniform sampling from the
  staff roster), `load_nursing_assessment` (YAML scaffolding for ADL,
  risk-assessment scales, disease-specific nursing focus),
  per-encounter nursing enricher wiring.
- **Out of scope**: nurse-identity generation (in
  [`clinosim/modules/staff/`](../staff/README.md)), nurse-narrative
  documents (in
  [`clinosim/modules/document/narrative/`](../document/narrative/README.md)),
  FHIR emission (in [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.nursing import (
    assign_primary_nurse,        # (encounter, staff_roster, rng) -> Practitioner
    load_nursing_assessment,     # @lru_cache YAML loader (with 6-layer validation)
    enrich_nursing,              # AD-56 post_records enricher entry
)
```

## Dependencies

- `clinosim.types.encounter` — Barthel / Braden / Morse / NEWS2
  fields (see `types.encounter`).
- `clinosim.modules.staff` — `StaffRoster`.
- `clinosim.modules.disease` — disease-specific nursing focus.

## Constants and configuration

- ADL / risk-assessment definitions live in `reference_data/*.yaml`.
- Load-time validation is 6-layer to catch orphan keys, invalid
  Barthel / Braden / Morse ranges, and unknown disease references.

## Directory contents

```
clinosim/modules/nursing/
  __init__.py           public API
  engine.py             assign_primary_nurse + assessment loader
  enricher.py           AD-56 post_records enricher (enrich_nursing)
  audit.py              per-module audit spec
  reference_data/       ADL / risk-scale / disease-focus YAMLs
```

## Testing

```bash
pytest tests/unit -k nursing -q
pytest tests/integration -k nursing -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
