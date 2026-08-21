# `clinosim.modules.device` — ICU device placement

## Purpose

POST_ENCOUNTER always-on AD-55 Module that places ICU devices
(central venous catheter, indwelling urinary catheter, mechanical
ventilator) on eligible inpatient / ICU / rehab-inpatient
encounters. Writes the result to `CIFPatientRecord.extensions["device"]`
so [`clinosim.modules.hai`](../hai/README.md) can consume line-days
downstream (Phase 2 HAI cascade — CDC NHSN baseline per-line-day
risk).

## Scope

- **In scope**: `place_devices_for_encounter` per-encounter
  evaluation (peak physiology state + altered-consciousness flag +
  YAML criteria → device set), `load_devices_config` YAML loader,
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
    place_devices_for_encounter,     # (record, encounter, rng) -> list[Device]
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
- Per-encounter RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — same
  encounter always samples the same device set; main patient RNG
  untouched (AD-16).

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`,
  `normalize_probabilities`.
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`.
- `clinosim.types.encounter` — `Device`, `Encounter`,
  `CIFPatientRecord`.
- `clinosim.types.clinical` — `PhysiologicalState` (peak state
  evaluation input).
- `numpy`, `yaml`.

## Constants and configuration

- [`reference_data/devices.yaml`](reference_data/devices.yaml) —
  device catalog. Each entry names indication criteria (physiology
  state thresholds, altered-consciousness gate, admission source
  filter) + placement probability + expected line-days
  distribution.
- Encounter-type gate: only fires on
  `INPATIENT_ENCOUNTER_TYPES = {"inpatient", "icu", "rehab_inpatient"}`
  (the same set the nursing module reads).

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
(`~L237-246`):

- `name="device"`, `stage=POST_ENCOUNTER`, `order=70`,
  `enabled=lambda c: True`.
- Runs BEFORE `hai` (order=80) so `extensions["device"]` is present
  when the HAI enricher reads line-days.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:241`](../../simulator/enrichers.py) | POST_ENCOUNTER order=70 registration. |
| HAI enricher | [`clinosim/modules/hai/engine.py`](../hai/engine.py) | Reads `extensions["device"]` line-days for CDC NHSN per-line-day HAI onset sampling (Phase 2). |
| FHIR `Device` builder | [`clinosim/modules/output/fhir_r4/`](../output/fhir_r4/) | Emits `Device` + `DeviceUseStatement` from `extensions["device"]`. |

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
