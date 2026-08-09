# `fhir_r4/encounters/` — encounter FHIR R4 builders

## Purpose

Emits FHIR R4 resources for the encounter itself and its
operational context: `Encounter`, `CareTeam`, `Location`,
`Organization`, `Endpoint`, and the custom `CareLevel` Observation
that carries JP-locale care-level data.

## Scope

- **In scope**: `Encounter` resource construction, `CareTeam`
  assembly from encounter practitioners, `Location` + `Organization`
  emission for the facility, `Endpoint` for imaging WADO base URLs,
  `CareLevel` custom Observation.
- **Out of scope**: encounter *simulation* itself (in
  [`clinosim.simulator/`](../../../../simulator/README.md)), the
  facility model (in [`clinosim.modules.facility/`](../../../facility/README.md)),
  practitioner identities (in [`clinosim.modules.staff/`](../../../staff/README.md)).

## Public API

Builders are dispatched through the parent facade
(`register_bundle_builder`), not called directly from outside.

## Dependencies

- `clinosim.types.encounter` — `Encounter`, `EncounterType`,
  `EncounterStatus`.
- Sibling `lib/` — shared helpers.

## Constants and configuration

- Encounter-status FHIR mappings live inside `encounter.py`.
- Care-level Observation coding uses the JP-locale care-level
  reference data from `clinosim.modules.care_level`.

## Directory contents

```
clinosim/modules/output/fhir_r4/encounters/
  __init__.py               subpackage facade
  encounter.py              Encounter resource builder
  care_team.py              CareTeam builder
  facility.py               Location + Organization emitter
  endpoint.py               Endpoint (WADO base URL) emitter
  care_level.py             CareLevel custom Observation
```

## Testing

```bash
pytest tests/unit -k encounters -q
pytest tests/integration -k encounter -q
```

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
