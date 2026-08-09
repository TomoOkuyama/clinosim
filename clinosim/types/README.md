# `clinosim.types` — shared data types (dataclasses)

## Purpose

`clinosim.types` centralises the `@dataclass` / `StrEnum` /
`typing.TypedDict` definitions used everywhere else in the project.
Splitting the types by domain (per AD-18) keeps the file sizes
manageable and makes cross-module imports self-documenting: `from
clinosim.types.encounter import Encounter` reads better than a giant
top-level module.

`clinosim.types` is a **pure data-shape package** — it has no runtime
logic beyond `__post_init__` normalisation. Any code that would modify
a type's fields belongs in the owning module (`simulator/`, `modules/*/`,
`output/`), not here.

## Scope

- **In scope**: dataclasses, StrEnums, TypedDicts, Protocol definitions,
  and `__post_init__` normalisers for the core clinical / operational /
  configuration types.
- **Out of scope**: any code that reads / writes / mutates the fields
  beyond simple normalisation. Business logic lives in `simulator/`
  and `modules/*/`.

## Public API

`clinosim/types/__init__.py` re-exports every public name from every
sub-module using `from clinosim.types.<domain> import *`, so callers
can do either:

```python
from clinosim.types.encounter import Encounter
# or:
from clinosim.types import Encounter          # convenience re-export
```

### Sub-modules (by domain)

| Sub-module | Contains |
|---|---|
| `clinical.py` | Clinical event core types (documents, findings) |
| `config.py` | `SimulatorConfig` and related runtime configuration models |
| `encounter.py` | `Encounter`, `EncounterType`, `EncounterStatus`, orders, medication administration |
| `identity.py` | `PatientProfile` identifiers, JP マイナンバー / insurance types |
| `microbiology.py` | Culture / sensitivity types |
| `output.py` | Cohort-level output metadata |
| `patient.py` | `PatientProfile`, `BaselineVitals`, chronic-condition types |
| `population.py` | Population-generation intermediate types |
| `procedure.py` | Surgical / therapeutic procedure types |
| `staff.py` | Staff / practitioner types |
| `allergy.py` | `Allergy`, `AllergyReaction` |
| `device.py` | Medical device types |
| `diagnosis.py` | Diagnosis event types |
| `document.py` | Document / narrative types |
| `family_history.py` | Family history types |
| `hai.py` | Healthcare-associated infection types |
| `imaging.py` | Imaging study / report types |
| `triage.py` | ED triage types |

## Dependencies

- Standard library `dataclasses`, `enum`, `datetime`, `typing`.
- `typing_extensions` for older-Python compatibility (imports only).
- **No dependency on any other `clinosim.*` module.** Types are the
  bottom of the dependency graph.

## Constants and configuration

- Sentinel values `_UNSET_DATETIME = datetime(1970, 1, 1)` and
  `_UNSET_DATE = date(1970, 1, 1)` — see the block-level comment in
  `clinical.py` for the determinism rationale (2026-07-04). These
  sentinels are private (leading underscore) and used only for
  optional field defaults where `None` would break downstream
  serialisation.
- StrEnum values (e.g. `EncounterType.INPATIENT = "inpatient"`) are
  the wire-level string values consumed by FHIR / CIF output builders.
  Changing a StrEnum value is a wire-format break.

## Directory contents

Everything is a data-only Python file at the top level of the package:

```
clinosim/types/
  __init__.py           re-exports from all sub-modules
  clinical.py           document / findings core types
  config.py             SimulatorConfig, runtime config models
  encounter.py          Encounter and adjacent operational types (largest file)
  patient.py            PatientProfile, baseline vitals, chronic conditions
  identity.py           MRN / insurance / national ID types
  <other-domain>.py     one file per clinical domain (see table above)
```

## Testing

```bash
pytest tests/unit -k types -q
```

Approximately 152 test files reference `clinosim.types`. Because these
are pure data types, they are mostly tested indirectly through consumer
code; direct type tests focus on `__post_init__` normalisation and
StrEnum wire values.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).
