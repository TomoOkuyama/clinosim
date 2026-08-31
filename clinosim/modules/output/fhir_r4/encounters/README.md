# `fhir_r4/encounters/` — Encounter + CareTeam + CareLevel + facility + Endpoint builders

## Purpose

Emits every FHIR R4 resource in the encounter + operational-context
family: `Encounter`, `CareTeam` (attending physician + primary nurse
— 2-name scope per AGENTS.md AD-64), `Endpoint` (DICOM WADO base
URL per imaging study), `Location` + `Organization` for the
facility (loaded as a facility Bundle at CIF write time), and the
custom JP `CareLevel` (要介護度) social-history `Observation`.

## Scope

- **In scope**: `_build_encounter` (root Encounter builder); `_bb_care_teams`
  + `_build_care_team` + `CARE_TEAM_ID_PREFIX = "careteam-"` +
  `_CARE_TEAM_CATEGORY_EN` / `_JA` — 2-name scope contract
  (participant[0] = attending, participant[1] = nurse only when
  `primary_nurse_id` is non-empty; participant[] never `[]`);
  `_bb_endpoints` + `_build_endpoint` + `DICOM_WADO_RS_CONNECTION_TYPE
  = "dicom-wado-rs"` + `_DEFAULT_WADO_BASE_URL`;
  `_build_facility_bundle` (Location + Organization Bundle written
  once per cohort at export time); `_bb_care_level` +
  `_CARE_LEVEL_LOINC = "80391-6"` (extracted from `_fhir_sdoh.py` by
  PR2 G2 — social-history Observation with JP `jp-care-level`
  valueCodeableConcept).
- **Out of scope**: encounter *simulation*
  ([`clinosim.simulator`](../../../../simulator/)); the facility
  operational-state model
  ([`clinosim.modules.facility`](../../../facility/README.md)); the
  staff roster + `assign_staff` dispatch
  ([`clinosim.modules.staff`](../../../staff/README.md)); the
  imaging chain that produces the `ImagingStudy` referenced by
  `Endpoint` ([`clinosim.modules.imaging`](../../../imaging/README.md));
  the 要介護度 assignment
  ([`clinosim.modules.care_level`](../../../care_level/README.md)).

### Perinatal + oncology encounter shapes (v0.5 → v0.6.0)

`_build_encounter` now handles the extra encounter shapes from the
longitudinal service lines (see
[`../../encounter/README.md`](../../encounter/README.md) §
"Longitudinal service-line encounter shapes"):

- **Newborn-side link** — when the CIF encounter carries
  `admit_source = "born"` (new `AdmitSource.BORN` value in
  [`clinosim/types/encounter.py`](../../../../types/encounter.py)),
  `Encounter.hospitalization.admitSource` maps that via
  `_build_hosp_concept("hl7-admit-source", ...)` and the sibling
  `admit_source_encounter_id` becomes the newborn's `Encounter.partOf`
  → mother's delivery encounter. Same `admit_source_encounter_id`
  slot is reused for the historical ED→inpatient linkage (CY7-05).
- **Delivery encounter (mother side)** — a standard inpatient
  Encounter with `type` reflecting the OB visit reason (from
  `perinatal.yaml::encounter.visit_reason`) and no special
  builder-side handling beyond the standard admission dx `O80` /
  discharge dx `Z37.0` routing.
- **Chemo / radiation encounters** — outpatient Encounters
  emitted from `chemo_visit` / radiation LifeEvents. No new
  builder needed; the accompanying MedicationRequest +
  MedicationAdministration + Procedure resources come from the
  sibling `medications/` and `procedures/` builders.

## Public API

Every builder is registered with the parent facade
(`_BUNDLE_BUILDERS` in [`../__init__.py`](../__init__.py)). Direct
imports for cross-family consumers:

```python
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.output.fhir_r4.encounters.care_team import (
    _bb_care_teams,
    _build_care_team,
    CARE_TEAM_ID_PREFIX,                 # "careteam-"
)
from clinosim.modules.output.fhir_r4.encounters.endpoint import (
    _bb_endpoints,
    _build_endpoint,
    DICOM_WADO_RS_CONNECTION_TYPE,       # "dicom-wado-rs"
)
from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle
from clinosim.modules.output.fhir_r4.encounters.care_level import _bb_care_level
```

## Determinism

Not applicable — pure builders over CIF. No RNG; parent facade sorts
NDJSON by id.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`,
  `get_attr_or_key`.
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`,
  `_coding_with_display`, `_social_category`, `loinc_coding`,
  `attach_ecs_institutional_extensions`.
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `primary_condition_ref` for `Encounter.reasonReference` +
  `Encounter.diagnosis[].condition`.
- `clinosim.modules.output.fhir_r4.demographics.smoking_alcohol` —
  `_sdoh_effective_datetime` (care_level reuses the SDOH anchor).
- `clinosim.codes` — LOINC + SNOMED display lookup.
- `clinosim.types.encounter` — `Encounter`, `EncounterStatus`,
  `EncounterType`, `TriageData`.

## Constants and configuration

- **`CARE_TEAM_ID_PREFIX = "careteam-"`** — imported by
  [`../../../document/audit.py`](../../../document/audit.py) into
  the 49-check `lift_firing_proof`.
- **CareTeam 2-name scope** (AGENTS.md AD-64): participant[0] is
  ALWAYS emitted (uses `"UNKNOWN"` placeholder when
  `attending_physician_id` is empty); participant[1] (nurse) is
  emitted ONLY when `primary_nurse_id` is non-empty. This keeps
  `participant[]` non-empty per FHIR R4 cardinality even in the
  attending-only case.
- **`_CARE_LEVEL_LOINC = "80391-6"`** — LOINC observation code for
  the JP 要介護度 social-history Observation
  (`text = "要介護度"` on JP; `"Long-term care need level"` on US).
- **`DICOM_WADO_RS_CONNECTION_TYPE = "dicom-wado-rs"`** —
  `Endpoint.connectionType.code`. `_DEFAULT_WADO_BASE_URL`
  (`https://wado.clinosim.example/dicomweb`) is the placeholder
  base URL emitted when the encounter does not carry a facility-
  specific PACS.
- **Facility Bundle**: `_build_facility_bundle` composes one
  Location + Organization Bundle from `hospital_config` at
  cohort-export time (written to `_facility.json` per AD-31
  master-bundle convention).

## Directory contents

```
clinosim/modules/output/fhir_r4/encounters/
  __init__.py                    empty (builders imported by parent __init__)
  encounter.py                   _build_encounter root builder
  care_team.py                   _bb_care_teams + _build_care_team + CARE_TEAM_ID_PREFIX
  care_level.py                  _bb_care_level (custom Observation, JP 要介護度)
  endpoint.py                    _bb_endpoints + _build_endpoint + DICOM_WADO_RS_CONNECTION_TYPE
  facility.py                    _build_facility_bundle (Location + Organization master Bundle)
```

## Testing

```bash
pytest tests/unit -k "encounter or care_team or care_level or endpoint or facility" -q
pytest tests/unit -k fhir_care_level -q
pytest tests/integration -k "encounter or hai" -q
```

The `document` AD-60 audit plug-in
([`../../../document/audit.py`](../../../document/audit.py))
cross-verifies `CARE_TEAM_ID_PREFIX` + CareTeam emit invariants
(2-name scope + participant[] non-empty).

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
