# `clinosim.modules.healthcare_system` — cross-facility organisation model

## Purpose

Represents the healthcare organisation above the single-facility level:
health systems, hospital groups, and the referral patterns between
them. Used when a patient's encounter chain spans more than one
facility (transfer, referral-in, referral-out).

## Scope

- **In scope**: organisation-level identifiers, referral pattern
  reference data, cross-facility encounter linking.
- **Out of scope**: single-facility resource state (in
  [`clinosim/modules/facility/`](../facility/README.md)), FHIR
  `Organization` resource serialisation (in
  [`clinosim/modules/output/`](../output/README.md)), scheduling.

## Public API

```python
from clinosim.modules.healthcare_system import (
    load_healthcare_system_config,   # @lru_cache YAML loader
    resolve_referral,                # (source_facility, referral_type) -> target
)
```

## Dependencies

- `clinosim.types.encounter` — encounter linking.
- `clinosim.modules.facility` — facility identifiers.
- `pyyaml` for the config loader.

## Constants and configuration

- Organisation reference data lives in `reference_data/*.yaml`
  (health systems, referral patterns).
- Country-specific defaults dispatch on `SimulatorConfig.country`.

## Directory contents

```
clinosim/modules/healthcare_system/
  __init__.py           public API
  engine.py             config loader + referral resolution
  audit.py              per-module audit spec
  reference_data/       organisation and referral-pattern YAMLs
```

## Testing

```bash
pytest tests/unit -k healthcare_system -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
