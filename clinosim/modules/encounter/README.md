# `clinosim.modules.encounter` — encounter protocol registry

## Purpose

Loads the per-encounter-type protocol YAMLs that describe the shape of
outpatient / ED / inpatient encounters: SOAP note templates, ED-triage
templates, physical-exam categories, common triage levels, and the
JP-locale narrative-field templates (`chief_complaint_ja`, `hpi_ja`,
`disposition_ja`, etc.).

## Scope

- **In scope**: encounter-protocol Pydantic models
  (`EncounterConditionProtocol` and child types), YAML loader for
  encounter protocols, per-encounter-type template dispatch, ED-triage
  template selection.
- **Out of scope**: encounter simulation itself (in
  [`clinosim.simulator`](../../simulator/README.md) —
  `inpatient.py` / `outpatient.py` / `emergency.py`), triage-level
  assignment (in [`clinosim.modules.triage`](../triage/README.md)),
  disease-specific content (in
  [`clinosim.modules.disease`](../disease/README.md)).

## Public API

```python
from clinosim.modules.encounter import (
    EncounterConditionProtocol,  # Pydantic BaseModel
    load_encounter_condition,    # (condition_id) -> EncounterConditionProtocol
)
```

## Dependencies

- `pydantic` — schema definition and validation.
- `pyyaml` — YAML loading.
- `clinosim.types.encounter` — encounter-type enums.
- `clinosim.modules._shared` — dict / dataclass dual-access helper.

## Constants and configuration

- Encounter-protocol YAMLs live in `reference_data/*.yaml`.
- Per policy §4, JP-locale narrative fields (`subjective_ja` /
  `objective_ja` / `plan_ja` / `chief_complaint_ja` / `hpi_ja` /
  `physical_exam_ja` / `ed_workup_summary_ja` / `disposition_ja`)
  keep their `_ja` suffix and contain Japanese narrative-template
  text; these fields are read by the JP narrative pipeline.
- Load-time validation is enforced by Pydantic; unknown fields raise
  a `ValidationError`.

## Directory contents

```
clinosim/modules/encounter/
  __init__.py           public API
  protocol.py           EncounterConditionProtocol + child Pydantic models
  loader.py             load_encounter_condition
  audit.py              per-module audit spec
  reference_data/
    <condition_id>.yaml one YAML per ED / outpatient condition
```

## Testing

```bash
pytest tests/unit -k encounter -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
