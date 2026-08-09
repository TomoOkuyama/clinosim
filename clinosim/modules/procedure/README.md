# `clinosim.modules.procedure` — surgical and therapeutic procedure generation

## Purpose

Generates surgical, invasive-bedside, and therapeutic procedure records
attached to inpatient / OR / ED encounters. Emits `SurgicalProcedure`,
`BedsideProcedure`, and `TherapySession` dataclasses that the FHIR
`Procedure` builder consumes.

## Scope

- **In scope**: procedure sampling from disease-protocol procedure
  blocks, surgical-team assignment (primary surgeon + assistants),
  procedure timing (start / end / duration), intraoperative-
  complication sampling, procedure-code assignment
  (CPT for US, K-code for JP, ICD-10-PCS where applicable),
  therapy-session records (physical / occupational / rehab).
- **Out of scope**: order *placement* (in
  [`clinosim.modules.order`](../order/README.md)), surgeon-identity
  generation (in [`clinosim.modules.staff`](../staff/README.md)),
  FHIR serialisation (in [`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.procedure import (
    generate_surgical_procedure,   # (order, encounter, staff, rng) -> SurgicalProcedure
    generate_bedside_procedure,    # (order, encounter, rng) -> BedsideProcedure
    generate_therapy_session,      # (order, encounter, rng) -> TherapySession
)
```

## Dependencies

- `clinosim.types.procedure` — `SurgicalProcedure`, `BedsideProcedure`,
  `TherapySession`.
- `clinosim.types.encounter` — `Order`, `Encounter`.
- `clinosim.types.staff` — practitioner IDs.
- `clinosim.locale.{us,jp}` — procedure-code mapping.

## Constants and configuration

- Intraoperative-complication probabilities and estimated-blood-loss
  distributions are currently inline and are flagged for extraction
  in [`docs/reviews/2026-08-09-constants-audit.md`](../../../docs/reviews/2026-08-09-constants-audit.md).
- Procedure-code sources:
  - US: CPT (Current Procedural Terminology), ICD-10-PCS for inpatient
    procedures.
  - JP: K-code (診療報酬点数表 K分類) from 厚生労働省.
- Procedure YAMLs live in `reference_data/*.yaml`.

## Directory contents

```
clinosim/modules/procedure/
  __init__.py           public API
  engine.py             procedure dispatch by order type
  audit.py              per-module audit spec
  reference_data/       procedure-code catalogues
```

## Testing

```bash
pytest tests/unit -k procedure -q
pytest tests/integration -k procedure -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
