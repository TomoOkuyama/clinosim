# `clinosim.modules.device` — ICU device placement (CVC / catheter / ventilator)

## Purpose

Opt-in Module (AD-55) that generates central venous catheter (CVC),
indwelling urinary catheter, and mechanical ventilator placement events
for ICU patients, and emits them as FHIR `Device` + `DeviceUseStatement`
downstream. Establishes the cross-module dependency point used by
Phase 2 [`clinosim.modules.hai`](../hai/README.md) for CLABSI / CAUTI /
VAP incidence.

## Scope

- **In scope**: post-records enrichment that walks each
  `CIFPatientRecord`, decides which of the three ICU device types to
  place based on `record.icu_transferred == True` and the physiology
  state + altered-consciousness indication tokens, and writes typed
  `DeviceRecord` instances to `extensions["device"]`.
- **Out of scope**: peripheral IV lines (excluded — nearly ubiquitous
  and HAI-irrelevant), device sub-types (PICC / Foley / pressure-
  support modes are collapsed into their generic SNOMED codes), per-
  day LOS-mid evolution (Phase 1 places at admission, removes at
  discharge), vasopressor / GCS<9 conditional criteria (Phase 2-3
  follow-up), FHIR emission (in [`clinosim/modules/output/`](../output/README.md)).

## Public API

```python
from clinosim.modules.device import (
    load_devices_config,             # @lru_cache YAML loader
    place_devices_for_encounter,     # (record, encounter, rng, config) -> list[DeviceRecord]
    enrich_device,                   # AD-56 post_records enricher entry
)
```

## Data types

| Type | Location | Key fields | Purpose |
|---|---|---|---|
| `DeviceRecord` | `clinosim/types/device.py` (`@dataclass`) | `device_id`, `encounter_id`, `device_type`, `snomed_code`, `placement_date`, `removal_date`, `placement_indication` | Item of `extensions["device"]`; input to the FHIR `Device` + `DeviceUseStatement` builder. |

## Indication tokens (evaluated in `engine.py`)

| Token | Source | Consumed by |
|---|---|---|
| `severity_moderate_plus` | `record.icu_transferred AND encounter.encounter_type == INPATIENT` | CVC + indwelling catheter |
| `altered_consciousness` | `vital_signs[i].gcs_score < 13` (encounter-scope walk) | indwelling catheter |
| `hypoxia` | `state.perfusion_status < 0.4` (Phase 1 SpO2 proxy) | ventilator |
| `high_respiratory_demand` | `state.respiratory_fraction > 0.7` | ventilator |

Placement decision walks the `any:` clauses of
`reference_data/devices.yaml.placement_criteria` and checks intersection
with the met-set (`_indications_met`). `all:` / `not:` clauses are
YAGNI-deferred.

## Dependencies

- `clinosim.types.device` — `DeviceRecord`.
- `clinosim.types.clinical` — `PhysiologicalState`.
- `clinosim.types.encounter` — `Encounter`, `EncounterType`,
  `VitalSignRecord`.
- `clinosim.types.output` — `CIFPatientRecord`.
- `clinosim.codes` (via FHIR builder) — SNOMED CT display lookup.
- `clinosim.simulator.helpers` (formerly `seeding`) —
  `ENRICHER_SEED_OFFSETS["device"] = 0x4445`, `derive_sub_seed`.
- `clinosim.modules._shared` — `get_attr_or_key` (dict / dataclass
  dual access).

## Constants and configuration

- `ENRICHER_SEED_OFFSETS["device"] = 0x4445` (`"DE"`) — sub-seed offset.
- SNOMED CT authoritative codes for the three device types (all
  verified against `tx.fhir.org` `$expand`):
  - `52124006` — Central venous catheter (中心静脈カテーテル)
  - `23973005` — Indwelling urinary catheter (膀胱留置カテーテル)
  - `706172005` — Ventilator (人工呼吸器)

  The spec's provisional `467021000` was replaced with the authoritative
  `23973005` after `tx.fhir.org` verification (same class of prevention
  as the PR #80 LOINC `2B010` fabrication incident).

## Directory contents

```
clinosim/modules/device/
  __init__.py           public API: load_devices_config, place_devices_for_encounter
  engine.py             core pure functions (indication + placement)
  enricher.py           AD-56 post_records enricher (enrich_device)
  audit.py              per-module audit spec
  reference_data/
    devices.yaml        SNOMED codes + placement_criteria
```

## Testing

```bash
pytest tests/unit -k device -q
pytest tests/integration -k device -q
```

## Related

- [DESIGN.md](../../../DESIGN.md) AD-55 (Base vs Module) / AD-56
  (enricher registry) / AD-57 (BNP-pattern surgical).
- [`docs/CONTRIBUTING-modules.md`](../../../docs/CONTRIBUTING-modules.md)
  — module authoring + PR verification guide.
- Downstream: [`clinosim/modules/hai/`](../hai/README.md) consumes
  `extensions["device"]` to sample HAI incidence.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
