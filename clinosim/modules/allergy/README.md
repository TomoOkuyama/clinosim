# `clinosim.modules.allergy` — patient allergy generation

## Purpose

Assigns allergy records (drug allergies, food allergies, environmental
allergies) to patients at population-generation time, and emits the
`Allergy` and `AllergyReaction` dataclasses that the FHIR
`AllergyIntolerance` builder consumes.

## Scope

- **In scope**: per-patient allergy sampling from country-appropriate
  prevalence tables, reaction-severity assignment (mild / moderate /
  severe / anaphylactic), reaction manifestations (rash / bronchospasm
  / anaphylaxis / etc.), coded-allergen selection (RxNorm for US
  drugs, SNOMED for food / environment).
- **Out of scope**: drug-allergy interaction with prescribing (in
  [`clinosim.modules.order`](../order/README.md)), FHIR serialisation
  (in [`clinosim.modules.output`](../output/README.md)), reaction-
  event generation during simulation.

## Public API

```python
from clinosim.modules.allergy import (
    assign_allergies,            # (patient, country, rng) -> list[Allergy]
)
```

## Dependencies

- `clinosim.types.allergy` — `Allergy`, `AllergyReaction`.
- `clinosim.types.patient` — `PatientProfile.allergies`.
- `clinosim.codes` (via FHIR builder) — RxNorm / SNOMED display
  lookup.

## Constants and configuration

- Allergy-prevalence tables (per age band × sex × country) live in
  `reference_data/*.yaml`.
- Reaction-manifestation catalogues use SNOMED CT for cross-country
  interoperability.

## Directory contents

```
clinosim/modules/allergy/
  __init__.py           public API
  engine.py             allergy assignment logic
  audit.py              per-module audit spec
  reference_data/       allergy-prevalence YAMLs
```

## Testing

```bash
pytest tests/unit -k allergy -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
