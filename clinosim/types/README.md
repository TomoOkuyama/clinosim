# `clinosim.types` — shared dataclasses at the bottom of the dependency graph

## Purpose

`clinosim.types` is the pure data-shape layer that every other package
imports from. It defines the `@dataclass`, `StrEnum`, `TypedDict`, and
`Protocol` shapes used for patients, encounters, orders, results,
diagnoses, procedures, allergies, imaging, documents, and simulator
configuration. Splitting the types by clinical domain (AD-18) keeps
individual files readable and makes cross-module imports
self-documenting: `from clinosim.types.encounter import Encounter`
reads better than a giant top-level module.

The package holds **no runtime logic** beyond `__post_init__`
normalisation. Any code that mutates a type's fields belongs in the
owning module (`simulator/`, `modules/*/`, `output/`), not here.

## Scope

- **In scope**: dataclasses, StrEnums, TypedDicts, and Protocols for
  the clinical, operational, identity, and configuration domains;
  minimal `__post_init__` normalisation for defaulting and type
  coercion.
- **Out of scope**: any code that reads, writes, or mutates the fields
  beyond simple normalisation — business logic lives in `simulator/`
  and `modules/*/`. YAML loading, code lookups, and serialisation
  belong to their owning packages.

## Public API

Two idiomatic imports:

```python
from clinosim.types.encounter import Encounter
# or:
from clinosim.types import Encounter          # convenience re-export
```

The convenience re-export in `__init__.py` covers a curated subset of
sub-modules only — everything else must be imported by its sub-module
path:

| Sub-module | Contains | Re-exported at top level? |
|---|---|---|
| `clinical.py` | Clinical event core types (documents, findings) | ✅ |
| `config.py` | `SimulatorConfig` and related runtime configuration models | ✅ |
| `encounter.py` | `Encounter`, `EncounterType`, `EncounterStatus`, orders, medication administration | ✅ |
| `identity.py` | `PatientProfile` identifiers, JP マイナンバー / insurance types | ✅ |
| `microbiology.py` | Culture / sensitivity types | ✅ |
| `output.py` | Cohort-level output metadata | ✅ |
| `patient.py` | `PatientProfile`, `BaselineVitals`, chronic-condition types | ✅ |
| `population.py` | Population-generation intermediate types | ✅ |
| `procedure.py` | Surgical / therapeutic procedure types | ✅ |
| `staff.py` | Staff / practitioner types | ✅ |
| `allergy.py` | `Allergy`, `AllergyReaction` | ❌ import direct |
| `device.py` | Medical device types | ❌ import direct |
| `diagnosis.py` | Diagnosis event types | ❌ import direct |
| `document.py` | Document / narrative types | ❌ import direct |
| `family_history.py` | Family history types | ❌ import direct |
| `hai.py` | Healthcare-associated infection types | ❌ import direct |
| `imaging.py` | Imaging study / report types | ❌ import direct |
| `triage.py` | ED triage types | ❌ import direct |

The "not re-exported" set is intentional: those domains are consumed
by narrow subsets of callers (imaging output, triage assessment,
diagnosis history builders), and forcing an explicit path makes the
dependency visible at the import site.

## Determinism

Not applicable — the package contains no random draws, wall-clock
reads, filesystem I/O, or environment-variable reads at import or at
dataclass construction. `_UNSET_DATETIME` and `_UNSET_DATE` sentinels
are fixed literals (`1970-01-01`), so identical inputs always produce
identical dataclass instances.

## Dependencies

- Standard library: `dataclasses`, `enum`, `datetime`, `typing`.
- `typing_extensions` for backport imports on older Python versions.
- **No dependency on any other `clinosim.*` module.** Types are the
  bottom of the dependency graph — importing anything from
  `clinosim.simulator` or `clinosim.modules.*` here would create a
  cycle and is a review-blocker.

## Constants and configuration

- **`_UNSET_DATETIME = datetime(1970, 1, 1)` and
  `_UNSET_DATE = date(1970, 1, 1)`** — defined in `clinical.py`
  (block-level comment dated 2026-07-04) and re-declared in
  `encounter.py`, `procedure.py`, `diagnosis.py`. These sentinels are
  private (leading underscore) and used only for optional fields where
  `None` would break downstream serialisation. The 1970-01-01 epoch
  is deliberately unambiguous so downstream serialisers can filter it.
- **StrEnum wire values** — e.g. `EncounterType.INPATIENT = "inpatient"`
  are the strings serialised into CIF / FHIR / CSV output. Changing a
  StrEnum value is a wire-format break and requires a coordinated
  update across every output adapter and every consumer's CIF
  fixtures.
- No YAML configuration. The package does not read any config file
  itself; consumers pass `SimulatorConfig` instances constructed
  elsewhere.

## Directory contents

```
clinosim/types/
  __init__.py           re-exports the 10 curated sub-modules listed above
  clinical.py           clinical events, documents, findings (238 lines)
  config.py             SimulatorConfig and runtime config models (254 lines)
  encounter.py          Encounter and adjacent operational types (311 lines)
  document.py           document / narrative types (343 lines — largest file)
  patient.py            PatientProfile, baseline vitals, chronic conditions (211 lines)
  output.py             cohort-level output metadata (132 lines)
  population.py         population-generation intermediates (111 lines)
  procedure.py          surgical / therapeutic procedures (84 lines)
  imaging.py            imaging study / report (75 lines)
  identity.py, microbiology.py, staff.py, allergy.py, device.py,
  diagnosis.py, family_history.py, hai.py, triage.py
                        one file per clinical domain (see table above)
```

## Testing

```bash
pytest tests/unit -k types -q
```

Approximately 155 test files import from `clinosim.types`. Because
these are pure data types, they are mostly tested indirectly through
consumer code; direct type tests focus on `__post_init__`
normalisation and StrEnum wire values.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
