# `fhir_r4/procedures/` — procedure and device FHIR R4 builders

## Purpose

Emits FHIR R4 resources for surgical / therapeutic procedures, and
for ICU devices (CVC / catheter / ventilator). Emits `Procedure`,
`Device`, and `DeviceUseStatement`.

## Scope

- **In scope**: `Procedure` resource (CPT for US, JJ1017 K-code for
  JP), `Device`, `DeviceUseStatement`.
- **Out of scope**: procedure / device *generation* (in
  [`clinosim.modules.procedure/`](../../../procedure/README.md) and
  [`clinosim.modules.device/`](../../../device/README.md)), FHIR
  `ImagingStudy` for radiology procedures (that lives in the
  sibling [`labs/`](../labs/README.md) directory).

## Public API

Builders are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside.

## Dependencies

- `clinosim.types.procedure` — `SurgicalProcedure`,
  `BedsideProcedure`, `TherapySession`.
- `clinosim.types.device` — `DeviceRecord`.
- `clinosim.codes.data.{cpt,jj1017,snomed}` — coding lookups.
- Sibling `lib/` — shared helpers.

## Constants and configuration

- Procedure code system precedence:
  - US: CPT (Current Procedural Terminology), ICD-10-PCS.
  - JP: JJ1017 K-code (診療報酬点数表 K分類 from 厚生労働省).
- Per policy §4, JJ1017 spec quotations may be retained inline in
  Japanese with English gloss.
- Device SNOMED CT codes are the authoritative-verified set (see
  [`clinosim.modules.device/`](../../../device/README.md)).

## Directory contents

```
clinosim/modules/output/fhir_r4/procedures/
  __init__.py               subpackage facade
  procedure.py              Procedure builder (surgical + bedside + therapy)
  device.py                 Device + DeviceUseStatement builder
```

## Testing

```bash
pytest tests/unit -k procedures -q
pytest tests/integration -k procedure -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
