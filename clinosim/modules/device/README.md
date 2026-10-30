# `clinosim.modules.device` — ICU device placement

## Purpose

POST_ENCOUNTER always-on AD-55 Module that places ICU devices
(central venous catheter, indwelling urinary catheter, mechanical
ventilator) on the inpatient encounters of patients who transferred to
the ICU. Writes the result to `CIFPatientRecord.extensions["device"]`
so [`clinosim.modules.hai`](../hai/README.md) can consume line-days
downstream (Phase 2 HAI cascade — CDC NHSN baseline per-line-day
risk).

## Scope

- **In scope**: `place_devices_for_encounter` per-encounter
  evaluation (worst physiology state of the stay + altered
  consciousness (GCS < 13) + intubation procedure + YAML criteria →
  device set; placement / removal dates = the encounter's admission /
  discharge dates), `load_devices_config` YAML loader,
  the POST_ENCOUNTER `enrich_device` enricher.
- **Out of scope**: HAI event sampling from device line-days
  ([`clinosim.modules.hai`](../hai/README.md)), device antibiotic
  regimen ([`clinosim.modules.antibiotic`](../antibiotic/README.md)),
  FHIR `Device` / `DeviceUseStatement` emission
  ([`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.device import (
    load_devices_config,             # () -> dict (@lru_cache)
    place_devices_for_encounter,     # (record, encounter, rng, devices_config) -> list[DeviceRecord]
)
from clinosim.modules.device.enricher import enrich_device
```

Internal helpers (in `engine.py`): `_evaluate_indications`,
`_indications_met`, `_altered_consciousness_for_encounter`,
`_peak_state_for_encounter`.

## Determinism

- Sub-seed offset `0x4445` (`"DE"`, PR-A) — registered in
  [`clinosim/seeding.py`](../../seeding.py) via
  `ENRICHER_SEED_OFFSETS["device"]`.
- The enricher builds a per-patient RNG
  (`derive_sub_seed(master_seed, offset, patient_id)`) and passes it
  to `place_devices_for_encounter`, but placement currently draws
  nothing from it: the device set is a deterministic function of the
  record. The main patient RNG is untouched (AD-16).

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`,
  `get_or_create_container`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.device` — `DeviceRecord`.
- `clinosim.types.encounter` — `Encounter`, `EncounterType`.
- `clinosim.types.output` — `CIFPatientRecord`.
- `clinosim.types.clinical` — `PhysiologicalState` (peak state
  evaluation input).
- `numpy`, `yaml`.

## Constants and configuration

- [`reference_data/devices.yaml`](reference_data/devices.yaml) —
  device catalog (`cvc`, `indwelling_catheter`,
  `mechanical_ventilator`). Each entry carries `snomed_code`,
  `snomed_display_en` / `_ja`, and `placement_criteria` as a list of
  `any: [token, ...]` clauses (a device is placed when any token of
  any clause is met). Current criteria: CVC ←
  `severity_moderate_plus`; urinary catheter ←
  `severity_moderate_plus` or `altered_consciousness`; ventilator ←
  `intubated`. There is no placement probability or line-day
  distribution.
- Indication tokens (`_evaluate_indications`):
  `severity_moderate_plus` (always true once the gate passes),
  `altered_consciousness` (any encounter vital with GCS < 13),
  `hypoxia` (worst perfusion < 0.4 or oxygenation impairment ≥ 0.6),
  `intubated` (an `intubation` procedure on the encounter),
  `high_respiratory_demand` (respiratory fraction > 0.7). `hypoxia`
  and `high_respiratory_demand` are computed but no yaml criterion
  uses them today.
- Gate: only fires when `record.icu_transferred` is true and the
  encounter's type is `EncounterType.INPATIENT`.

## Directory contents

```
clinosim/modules/device/
  __init__.py                        re-exports load_devices_config + place_devices_for_encounter
  engine.py                          indication evaluation + device placement
  enricher.py                        POST_ENCOUNTER enricher
  reference_data/
    devices.yaml                     device catalog + indication criteria
```

The module has **no `audit.py`** — verification is via the tests
below.

## Enricher wiring

Registered in
[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`~L310-320`):

- `name="device"`, `stage=POST_ENCOUNTER`, `order=70`,
  `enabled=lambda c: True`.
- Runs BEFORE `hai` (order=80) so `extensions["device"]` is present
  when the HAI enricher reads line-days.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:316`](../../simulator/enrichers.py) | POST_ENCOUNTER order=70 registration. |
| HAI enricher | [`clinosim/modules/hai/enricher.py`](../hai/enricher.py) | Reads `extensions["device"]` line-days for CDC NHSN per-line-day HAI onset sampling (Phase 2). |
| FHIR `Device` builder | [`clinosim/modules/output/fhir_r4/procedures/device.py`](../output/fhir_r4/procedures/device.py) | Emits one `Device` + one `DeviceUseStatement` per `extensions["device"]` entry (opaque ids derived from `DeviceRecord.device_id`). |

## Testing

```bash
pytest tests/unit -k "device_engine or device_enricher" -q
```

Individual files:

- [`tests/unit/test_device_engine.py`](../../../tests/unit/test_device_engine.py)
  — indication evaluation.
- [`tests/unit/test_device_enricher.py`](../../../tests/unit/test_device_enricher.py)
  — enricher determinism + encounter-type gating.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
