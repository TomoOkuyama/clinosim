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
  device set; placement = the earliest insertion procedure or catheter
  order, else the ICU transfer day; removal = the day the device's
  indication ended, else the discharge date, see
  [`simulator/device_removal.py`](../../simulator/device_removal.py);
  a urinary / central venous catheter placed by an insertion procedure
  or order of a stay with no ICU device of that type also gets a
  `DeviceRecord` with `origin="insertion"`, which carries no HAI
  sampling), `load_devices_config` YAML loader,
  the POST_ENCOUNTER `enrich_device` enricher.
- **Out of scope**: HAI event sampling from device line-days
  ([`clinosim.modules.hai`](../hai/README.md)), device antibiotic
  regimen ([`clinosim.modules.antibiotic`](../antibiotic/README.md)),
  FHIR `Device` / `DeviceUseStatement` emission
  ([`clinosim.modules.output`](../output/README.md)).

## Public API

```python
from clinosim.modules.device import (
    load_devices_config,             # () -> dict (@lru_cache, Pydantic-validated)
    place_devices_for_encounter,     # (record, encounter, devices_config) -> list[DeviceRecord]
)
from clinosim.modules.device.enricher import enrich_device
```

Internal helpers (in `engine.py`): `_evaluate_indications`,
`_indications_met`, `_altered_consciousness_for_encounter`,
`_peak_state_for_encounter`.

## Determinism

- Placement is deterministic and draws no RNG: the device set is a
  pure function of the record. The enricher builds no RNG, so the
  main patient RNG is untouched (AD-16).
- Sub-seed offset `0x4445` (`"DE"`, PR-A) stays reserved in
  [`clinosim/seeding.py`](../../seeding.py) as
  `ENRICHER_SEED_OFFSETS["device"]` (#2208) but is not consumed.

## Dependencies

- `clinosim.modules._shared` — `get_attr_or_key`,
  `get_or_create_container`.
- `clinosim.codes` — `code_exists` (SNOMED codes in `devices.yaml`
  must be registered).
- `clinosim.datafiles` — `load_data_yaml`.
- `clinosim.types.device` — `DeviceRecord`.
- `clinosim.types.encounter` — `Encounter`, `EncounterType`.
- `clinosim.types.output` — `CIFPatientRecord`.
- `clinosim.types.clinical` — `PhysiologicalState` (peak state
  evaluation input).
- `pydantic` — `devices.yaml` schema validation.

## Constants and configuration

The `noninvasive_ventilator` entry (Issue #3705) has no placement criterion: it is not an ICU device but is placed on the date of the stay's first reading that carries the NIV device and removed on the first day after the last such reading (`simulator/device_removal.py::noninvasive_ventilation_dates`).

The `home_cpap` entry (Issue #3837) is a home device: `place_home_devices` gives every patient whose chronic conditions include an `home_for_conditions` prefix (`G47.3`, obstructive sleep apnea; the follow-up lists CPAP therapy as the ongoing treatment) a `DeviceRecord` with `origin="home"`, placed at the date of the first recorded CPAP therapy procedure (`therapy_procedure_types`), else at the condition onset, with no removal date. It carries no infection sampling (`origin != icu_stay`). Draws no RNG.

- [`reference_data/devices.yaml`](reference_data/devices.yaml) —
  device catalog (`cvc`, `indwelling_catheter`,
  `mechanical_ventilator`, `noninvasive_ventilator`). Each entry carries `snomed_code`,
  and `placement_criteria` as a list of
  `any: [token, ...]` clauses (a device is placed when any token of
  any clause is met). Current criteria: CVC ←
  `severity_moderate_plus`; urinary catheter ←
  `severity_moderate_plus` or `altered_consciousness`; ventilator ←
  `intubated`. There is no placement probability or line-day
  distribution. `load_devices_config` validates the file against the
  Pydantic model `_DevicesConfig` in `engine.py` (unknown keys,
  unregistered SNOMED codes and criterion tokens outside
  `INDICATION_TOKENS` fail at load time).
- Indication tokens (`_evaluate_indications`):
  `severity_moderate_plus` (always true once the gate passes),
  `altered_consciousness` (any encounter vital with GCS < 13),
  `hypoxia` (worst perfusion < 0.4 or oxygenation impairment ≥ 0.6),
  `intubated` (an `intubation` procedure on the encounter),
  `high_respiratory_demand` (respiratory fraction > 0.7). `hypoxia`
  and `high_respiratory_demand` are computed but no yaml criterion
  uses them today (`high_respiratory_demand` is not in
  `INDICATION_TOKENS`, so the schema rejects it in `devices.yaml`).
- Gate: ICU devices only when `record.icu_transferred` is true and the
  encounter's type is `EncounterType.INPATIENT`; catheters of an
  insertion procedure / order on any inpatient encounter.
- [`simulator/reference_data/device_removal.yaml`](../../simulator/reference_data/device_removal.yaml)
  — per device type the placing events and the indications that end
  the device (post-operative: the day after the last operation;
  strict intake / output or haemodynamic monitoring: after a minimum
  dwell), each only once the patient needs no ICU-level care. Sources:
  CDC / HICPAC CAUTI guideline (2009) and intravascular catheter
  guideline (2011); the day counts are model choices (Issue #3516).

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
(`register_builtin_enrichers`):

- `name="device"`, `stage=POST_ENCOUNTER`, `order=70`,
  `enabled=lambda c: True`.
- Runs BEFORE `hai` (order=80) so `extensions["device"]` is present
  when the HAI enricher reads line-days.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) `register_builtin_enrichers` | POST_ENCOUNTER order=70 registration. |
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
