# `clinosim.modules.staff` — practitioner (staff) generation

## Purpose

Generates the practitioner roster (physicians, nurses, technicians)
that a simulated hospital employs, assigns per-encounter practitioners
(attending, admitting, discharging, primary nurse), and emits the
identifiers that FHIR `Practitioner` / `PractitionerRole` builders
consume.

## Scope

- **In scope**: staff-roster generation with country-appropriate
  name / phonetic-name pairs, per-encounter practitioner assignment,
  `StaffRoster.get_by_id` API for downstream lookup.
- **Out of scope**: patient identifiers (in
  [`clinosim/modules/identity/`](../identity/README.md)), facility /
  unit assignment (in [`clinosim/modules/facility/`](../facility/README.md)),
  nursing assessments (in [`clinosim/modules/nursing/`](../nursing/README.md)),
  FHIR serialisation (in [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.staff import (
    build_staff_roster,          # (country, size, rng) -> StaffRoster
    assign_encounter_practitioners,  # (encounter, roster, rng) -> None
)
```

`StaffRoster.get_by_id(id) -> Practitioner | None` is the lookup used
by tests and by FHIR emission.

## Dependencies

- `clinosim.types.staff` — `Practitioner`, `StaffRoster`.
- `clinosim.locale.{us,jp}` — name pools.
- `clinosim.simulator.helpers` — sub-seed derivation.

## Constants and configuration

- Roster size defaults live in
  `clinosim/config/hospital_operations.yaml` under `staffing`.
- Name / phonetic-name generation dispatches on the roster's
  country via `_generate_name_pair`.

## Directory contents

```
clinosim/modules/staff/
  __init__.py           public API
  engine.py             roster generation + per-encounter assignment
  audit.py              per-module audit spec
  reference_data/       role-mapping YAMLs (per country)
```

## Testing

```bash
pytest tests/unit -k staff -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
