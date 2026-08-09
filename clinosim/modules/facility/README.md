# `clinosim.modules.facility` — facility / department definitions and hospital state

## Purpose

Provides the facility / department model that the rest of the simulator
uses to represent "where" an encounter happens (department, unit, ED
zone, ICU bed, OR suite) and the shared operational state
(`HospitalState`) that tracks resource utilisation across a
simulation run.

## Scope

- **In scope**: facility / department reference data, `HospitalState`
  dataclass, queue-length tracking for MRI / X-ray / ultrasound / OR,
  ED-crowding index, nursing / pharmacy staff counts, per-day resource
  reset.
- **Out of scope**: staff *identities* (in
  [`clinosim/modules/staff/`](../staff/README.md)), hospital-level
  organisation across sites (in
  [`clinosim/modules/healthcare_system/`](../healthcare_system/README.md)),
  device placement (in [`clinosim/modules/device/`](../device/README.md)),
  FHIR `Organization` / `Location` serialisation
  (in [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.facility import (
    HospitalState,               # dataclass with queue + capacity fields
    load_facility_config,        # @lru_cache YAML loader
    get_department,              # (encounter_type) -> Department
)
```

## Dependencies

- `clinosim.types.encounter` — `EncounterType`.
- `clinosim.types` for the facility-related dataclasses.
- `pyyaml` for the config loader.

## Constants and configuration

- `HospitalState` fields (all queue / crowding / staff counters) are
  read by the order module's hospital-state-aware result-timing model.
- Runtime configuration is loaded from
  `clinosim/config/hospital_operations.yaml`
  (or `hospital_small.yaml` / `hospital_large.yaml`); see
  [`clinosim/config/README.md`](../../config/README.md) for the
  YAML schema.
- Facility reference data (department codes, unit types) lives in
  `reference_data/*.yaml`.

## Directory contents

```
clinosim/modules/facility/
  __init__.py           public API
  hospital_state.py     HospitalState dataclass
  engine.py             config loader + department dispatch
  audit.py              per-module audit spec
  reference_data/       department / unit / room YAMLs
```

## Testing

```bash
pytest tests/unit -k facility -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
