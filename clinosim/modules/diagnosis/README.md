# `clinosim.modules.diagnosis` — diagnosis assignment and confirmation

## Purpose

Assigns primary and secondary diagnoses to each encounter, tracks
working-diagnosis vs. discharge-diagnosis divergence (misdiagnosis
signal), and manages the encounter-time confirmation state that
downstream FHIR `Condition` and `ClinicalImpression` builders consume.

## Scope

- **In scope**: primary / secondary diagnosis sampling, working-
  diagnosis vs. discharge-diagnosis tracking, diagnosis confirmation
  flags (`confirmed` field), non-specific-code handling (e.g.
  `ICD_COUGH = R05` as a symptom-only pseudo-diagnosis), diagnosis-
  correctness signal for the clinical-course engine.
- **Out of scope**: disease definitions (in
  [`clinosim.modules.disease`](../disease/README.md)), the ICD /
  SNOMED code registries (`clinosim/codes/`), FHIR serialisation
  (in [`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.diagnosis import (
    assign_diagnoses,            # (encounter, protocol, rng) -> None
    enrich_diagnosis,            # AD-56 post_records enricher entry
)
from clinosim.modules.diagnosis.nonspecific_codes import (
    ICD_COUGH,                   # R05
    UNRESOLVED_DIAGNOSIS_ICD,    # placeholder for pending diagnosis
)
```

## Dependencies

- `clinosim.types.diagnosis` — `DiagnosisRecord`, `DiagnosisStatus`.
- `clinosim.types.encounter` — `Encounter`.
- `clinosim.modules.disease` — disease-code sources.

## Constants and configuration

- `ICD_COUGH = "R05"` — symptom-only pseudo-diagnosis used as a
  sentinel for encounters that presented with cough but received no
  specific respiratory diagnosis (asserted in
  `tests/unit/simulator/test_r05_cough_not_wrong_diagnosis.py`).
- `UNRESOLVED_DIAGNOSIS_ICD` — sentinel for pending diagnosis.
- Non-specific-code catalogue lives in `nonspecific_codes.py`.

## Directory contents

```
clinosim/modules/diagnosis/
  __init__.py           public API
  engine.py             diagnosis assignment logic
  nonspecific_codes.py  symptom-only pseudo-diagnosis constants
  enricher.py           post_records enricher (confirmation state)
  audit.py              per-module audit spec
```

## Testing

```bash
pytest tests/unit -k diagnosis -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
