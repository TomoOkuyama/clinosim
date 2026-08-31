# `fhir_r4/procedures/` — Procedure + Immunization + Device + nursing FHIR R4 builders

## Purpose

Emits every FHIR R4 resource in the "procedure & device" family:
`Procedure` (surgery + bedside + rehab), `Immunization`
(vaccine administration record), `Device` + `DeviceUseStatement`
(ICU devices — CVC / catheter / ventilator), the nursing survey
`Observation` (NEWS2 / GCS / Braden / Morse flowsheet), and the
oxygen-therapy `Procedure` (Issue #796 — derived from vitals
`on_supplemental_oxygen` flag with a `performedPeriod`).

`Immunization` lives here rather than under
[`../conditions/`](../conditions/README.md) because FHIR files
Immunization under the Procedure family; the naming preserves the
FHIR resource-family taxonomy.

## Scope

- **In scope**: `_build_procedure` (root Procedure builder — surgery
  / bedside / rehab dispatch, CPT for US + JJ1017 K-code for JP);
  `_bb_immunizations` (adult vaccine history from
  `CIFPatientRecord.immunizations`);
  `_bb_device` + `_bb_device_use` (from `extensions["device"]`);
  `_bb_nursing_observations` (NEWS2 / GCS / Braden / Morse survey
  Observation cluster — this is the FHIR emit side; the compute
  functions live in
  [`../../../observation/nursing.py`](../../../observation/nursing.py));
  `_bb_oxygen_therapy` (Issue #796 — reads the per-therapy
  `on_supplemental_oxygen` flag off vitals to synthesise a
  `Procedure` with `performedPeriod` for continuous oxygen therapy;
  single-timestamp events dwell for `_SINGLE_TIMESTAMP_DWELL =
  timedelta(minutes=15)` around the flagged sample);
  `_SNOMED_OXYGEN_THERAPY = "57485005"`.
- **Out of scope**: procedure / device / immunization / nursing
  **generation**
  ([`clinosim.modules.procedure`](../../../procedure/README.md)、
  [`clinosim.modules.device`](../../../device/README.md)、
  [`clinosim.modules.immunization`](../../../immunization/README.md)、
  [`clinosim.modules.observation`](../../../observation/README.md)
  for nursing scores and the vitals flag);
  `ImagingStudy` (that lives under
  [`../labs/imaging_study.py`](../labs/imaging_study.py) despite
  imaging being clinically procedural).

### Longitudinal service-line Procedure emission (v0.5 → v0.6.0)

Two additional Procedure code sets reach FHIR through the standard
`_build_procedure` path (no new resource-type builder needed) —
the sibling
[`clinosim.modules.procedure`](../../../procedure/README.md) module
constructs `ProcedureRecord` for both, and the FHIR post-process
pipeline picks up the code + display without further wiring:

- **Delivery Procedure** — JP `K894` (経腟分娩, MHLW 診療報酬点数表
  K-code) / US CPT `59400` (routine obstetric care incl. vaginal
  delivery). Attached to mother-side delivery encounters emitted
  by [`clinosim/simulator/perinatal.py`](../../../../simulator/perinatal.py).
- **Radiation-therapy Procedure** — modality / dose / site come
  from the disease-YAML radiation block; the code + display are
  emitted by the standard Procedure builder, distinguished only
  by the code system.

## Public API

Every builder is registered with the parent facade
(`_BUNDLE_BUILDERS` in [`../__init__.py`](../__init__.py)). Direct
imports for cross-family consumers:

```python
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure
from clinosim.modules.output.fhir_r4.procedures.immunization import _bb_immunizations
from clinosim.modules.output.fhir_r4.procedures.device import _bb_device, _bb_device_use
from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations
from clinosim.modules.output.fhir_r4.procedures.oxygen_therapy import (
    _bb_oxygen_therapy,
    _SINGLE_TIMESTAMP_DWELL,             # timedelta(minutes=15)
    _SNOMED_OXYGEN_THERAPY,              # "57485005"
)
```

## Determinism

Not applicable — pure builders over CIF procedures / immunizations /
`extensions["device"]` / vitals + nursing observations.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`.
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`,
  `_coding_with_display`, `loinc_coding`, `survey_category`,
  `to_fhir_datetime`, `attach_ecs_institutional_extensions`.
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `primary_condition_ref` for `Procedure.reasonReference`.
- `clinosim.codes` — CPT / JJ1017 K-code / CVX / SNOMED display
  lookup.
- `clinosim.types.encounter` — `ProcedureRecord`, `RehabSession`,
  `Device`, `ImmunizationRecord`.
- `datetime`, `timedelta` — standard library (used by
  `_SINGLE_TIMESTAMP_DWELL` in oxygen_therapy).

## Constants and configuration

- **Procedure code dispatch** — US emits CPT
  (`http://www.ama-assn.org/go/cpt`); JP emits JJ1017 K-code via
  the JP-CLINS Procedure profile.
- **Oxygen therapy** (`oxygen_therapy.py`, Issue #796):
  - `_SNOMED_OXYGEN_THERAPY = "57485005"` — SNOMED CT code for
    oxygen administration.
  - `_SINGLE_TIMESTAMP_DWELL = timedelta(minutes=15)` — dwell
    window around a single-timestamp `on_supplemental_oxygen`
    vitals sample when building `Procedure.performedPeriod`.
  - Reads the per-therapy flag from vitals rather than a
    dedicated Order (per the [`session-derived procedure period`](../../../../..)
    pattern documented in memory: no Order.end_datetime → derive
    from vitals).
- **Immunization emit** — CVX system + lot number written from
  `ImmunizationRecord.lot_number`; SHA-256-based lot generation
  lives in [`../../../immunization/engine.py`](../../../immunization/engine.py)
  (P1-7 fix — Python builtin `hash()` is salted per interpreter).
- **Device emit** — reads `extensions["device"]` (populated by
  [`../../../device/enricher.py`](../../../device/enricher.py) at
  POST_ENCOUNTER order=70). `DeviceUseStatement.timingPeriod` is
  derived from the per-device line-days count.
- **Nursing survey Observation** — emits under
  `Observation.category = "survey"` for NEWS2 / GCS / Braden /
  Morse. Per AGENTS.md AD-64 nursing_flowsheets vs
  nursing_assignment disambiguation, this is the emit side of the
  POST_RECORDS `enrich_nursing` enricher (order=20).

## Directory contents

```
clinosim/modules/output/fhir_r4/procedures/
  __init__.py                        empty (builders imported by parent __init__)
  procedures.py                      _build_procedure (surgery + bedside + rehab)
  immunization.py                    _bb_immunizations (CVX + lot number)
  device.py                          _bb_device + _bb_device_use (from extensions["device"])
  nursing.py                         _bb_nursing_observations (NEWS2 / GCS / Braden / Morse survey Observation)
  oxygen_therapy.py                  _bb_oxygen_therapy + _SINGLE_TIMESTAMP_DWELL + _SNOMED_OXYGEN_THERAPY (Issue #796)
```

## Testing

```bash
pytest tests/unit -k "fhir_procedure or fhir_immunization or fhir_device or fhir_nursing or oxygen_therapy" -q
pytest tests/integration -k "procedure or hai" -q
```

Cross-verification: the `hai` AD-60 audit
([`../../../hai/audit.py`](../../../hai/audit.py)) exercises
`_bb_device` + `_bb_device_use` through its `lift_firing_proof`
because the HAI cascade consumes `extensions["device"]` line-days.
The Issue #796 oxygen-therapy contract is guarded by
[`tests/unit/output/test_fhir_oxygen_therapy_procedure.py`](../../../../../tests/unit/output/test_fhir_oxygen_therapy_procedure.py).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
