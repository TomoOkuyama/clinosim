# `clinosim.modules.disease` — disease protocol registry

## Purpose

Loads and validates the YAML-defined disease protocols that drive
patient simulation. A `DiseaseProtocol` is the single source of truth
for a disease's clinical shape: severity distribution, presenting
symptoms, expected labs / vitals distributions, order protocols
(admission / daily monitoring / medications), narrative templates,
course archetypes, complications, and drug interactions.

## Scope

- **In scope**: `DiseaseProtocol` Pydantic model + child models
  (`HpiTemplate`, `PhysicalExamDayFindings`, `NarrativeSpec`,
  `ImagingOrderSpec`), YAML loader (`load_disease_protocol`), YAML
  loader for the full registry, severity-expression evaluator,
  drug-interaction cross-check.
- **Out of scope**: disease-generation orchestration (in
  [`clinosim.simulator`](../../simulator/README.md)), physiology-state
  update logic (in
  [`clinosim.modules.physiology`](../physiology/README.md)),
  clinical-course trajectory selection (in
  [`clinosim.modules.clinical_course`](../clinical_course/README.md)),
  the YAML files themselves (they live in `reference_data/`).

## Public API

```python
from clinosim.modules.disease import (
    DiseaseProtocol,             # Pydantic BaseModel
    load_disease_protocol,       # (disease_id) -> DiseaseProtocol
    load_all_disease_protocols,  # () -> dict[str, DiseaseProtocol]
)
```

## Dependencies

- `pydantic` — schema definition and validation.
- `pyyaml` — YAML loading.
- `clinosim.types.diagnosis` — code types.
- `clinosim.modules._shared` — probability normalisation helpers.
- No dependency on `clinosim.simulator` (one-way boundary — disease is
  read by simulator, not the other way).

## Constants and configuration

- Disease protocol YAMLs live in `reference_data/*.yaml` (one file per
  disease, filename = disease_id).
- Load-time validation is enforced by Pydantic; unknown fields raise
  a `ValidationError`.
- Severity-expression variables allowed inside `severity.if_expr` are
  documented at the head of `severity.py` (whitelisted set).

## Directory contents

```
clinosim/modules/disease/
  __init__.py           public API
  protocol.py           DiseaseProtocol + all child Pydantic models
  loader.py             load_disease_protocol + load_all_disease_protocols
  severity.py           severity-expression evaluator
  audit.py              per-module audit spec
  reference_data/
    <disease_id>.yaml   one YAML per disease (32 inpatient + 46 ED/outpatient)
```

## Testing

```bash
pytest tests/unit -k disease -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
