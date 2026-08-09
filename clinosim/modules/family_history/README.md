# `clinosim.modules.family_history` — family-history record generation

## Purpose

Assigns family-history entries (parent, sibling, grandparent) to
patients with plausible condition prevalences and emits
`FamilyMemberHistoryRecord` dataclasses that the FHIR
`FamilyMemberHistory` builder consumes.

## Scope

- **In scope**: per-patient family-history sampling with
  age-appropriate condition prevalences, first-degree vs. second-
  degree relative assignment, ICD-coded conditions on family
  members.
- **Out of scope**: genetic-risk propagation to the patient's own
  disease sampling (that's a Phase 2+ scope in
  [`clinosim.modules.population`](../population/README.md) / risk
  factor logic), FHIR serialisation (in
  [`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.family_history import (
    assign_family_history,       # (patient, country, rng) -> list[FamilyMemberHistoryRecord]
)
```

## Dependencies

- `clinosim.types.family_history` — `FamilyMemberHistoryRecord`,
  `condition_codes`.
- `clinosim.types.patient` — `PatientProfile.family_history`.

## Constants and configuration

- Condition-prevalence tables per relative type live in
  `reference_data/*.yaml`.

## Directory contents

```
clinosim/modules/family_history/
  __init__.py           public API
  engine.py             family-history assignment logic
  audit.py              per-module audit spec
  reference_data/       relative-condition prevalence YAMLs
```

## Testing

```bash
pytest tests/unit -k family_history -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
