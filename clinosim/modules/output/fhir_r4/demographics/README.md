# `fhir_r4/demographics/` — Patient / Practitioner / FamilyMemberHistory / Social-history builders

## Purpose

Emits every FHIR R4 resource in the demographics + social-history
family: `Patient` (with JP Core Coverage + payor Organization +
occupation Observation + inline AllergyIntolerance),
`Practitioner` + `PractitionerRole`, `FamilyMemberHistory`, and the
smoking / alcohol social-history `Observation`s. The
[`../conditions/`](../conditions/README.md) `AllergyIntolerance`
builder handles the standalone allergy path; the inline
`_build_allergy_intolerance` in `patient.py` is a legacy Patient-embed
kept for one release cycle.

## Scope

- **In scope**: `_build_patient` (Patient with birthDate / sex /
  address / telecom / marital + language + coverage + occupation +
  inline allergy) + Coverage / payor Organization construction +
  occupation Observation + inline allergy;
  `_build_practitioner` + `_build_practitioner_role`;
  `_bb_family_history` + `_resolve_family_history_code` +
  `_build_relationship_codeable`; `_bb_smoking_status` +
  `_bb_alcohol_use` + `_obs` + `_sdoh_effective_datetime` +
  `_sdoh_performer_ref`.
- **Out of scope**: patient / practitioner / family-history / SDOH
  *generation* (in
  [`clinosim.modules.population`](../../../population/README.md),
  [`clinosim.modules.identity`](../../../identity/README.md),
  [`clinosim.modules.staff`](../../../staff/README.md),
  [`clinosim.modules.family_history`](../../../family_history/README.md),
  [`clinosim.modules.sdoh`](../../../sdoh/README.md)); JP insurance
  numbering (that lives in `identity` module).

### Newborn Patient (v0.5 → v0.6.0)

Perinatal-delivery LifeEvents produce a paired newborn
`PatientProfile` in the CIF (see
[`../../patient/README.md`](../../patient/README.md) —
`id = "<mother_id>-BABY"`, `birthDate` = delivery date, household
inherited). No new Patient builder is needed — the existing
`_build_patient` picks the newborn up from the CIF like any other
patient. The mother-newborn linkage is expressed on the newborn's
Encounter (`Encounter.partOf` → mother's delivery encounter),
handled by the sibling
[`../encounters/`](../encounters/README.md) builder rather than
here.

## Public API

Every builder is registered with the parent facade
(`_BUNDLE_BUILDERS` in [`../__init__.py`](../__init__.py)).
Direct-import surface:

```python
from clinosim.modules.output.fhir_r4.demographics.patient import (
    _build_patient,                     # (patient_dict, country) -> Patient dict
    _build_coverage_resources,          # (patient_dict, country) -> [Coverage, payor Organization, ...]
    _build_occupation_observation,      # -> occupation Observation
    _build_allergy_intolerance,         # legacy Patient-embed (see conditions/ for the standalone path)
)
from clinosim.modules.output.fhir_r4.demographics.practitioner import (
    _build_practitioner,                # (staff_id, roster_map, country) -> Practitioner dict
    _build_practitioner_role,           # (staff_id, roster_map, country) -> PractitionerRole dict
)
from clinosim.modules.output.fhir_r4.demographics.family_history import (
    _bb_family_history,                 # bundle-builder (ctx: BundleContext) -> [FamilyMemberHistory, ...]
    _resolve_family_history_code,       # (code, country) -> resolved ICD/JP code
    _build_relationship_codeable,       # (rel, display_map, lang) -> CodeableConcept
)
from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (
    _bb_smoking_status,                 # bundle-builder
    _bb_alcohol_use,                    # bundle-builder
    _sdoh_effective_datetime,           # (ctx) -> ISO datetime str (SDOH anchor)
    _sdoh_performer_ref,                # (ctx) -> Practitioner reference str
)
```

## Determinism

Not applicable — every builder is pure over the input CIF. `_identity_cfg`
is `@lru_cache` so repeated per-country lookups are free; the parent
facade sorts NDJSON by id post-write.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `is_us`, `resolve_lang`.
- `clinosim.modules.output.fhir_r4.lib.common` — `_coding_with_display`,
  `_social_category`, `build_address`, `build_telecom`, `to_fhir_date`,
  `BundleContext`, plus fragment helpers.
- `clinosim.modules.output.fhir_r4.lib.localization` — JP display
  localisation.
- `clinosim.modules.output.fhir_r4.lib.reference_data` — Practitioner
  qualification / role reference-data lookups.
- `clinosim.codes` — `get_system_uri`, `lookup` for LOINC / SNOMED /
  ICD / JP-Core / HL7 v3-RoleCode.
- `clinosim.locale.loader` — `load_identity_config` for JP payor +
  coverage constants.

## Constants and configuration

- **Patient identifiers** — JP payor / coverage constants come from
  [`clinosim/locale/jp/identity.yaml`](../../../../locale/jp/identity.yaml)
  via `load_identity_config`; the `_identity_cfg` cache keeps that
  lookup free.
- **Marital / language / coverage displays** — inline in `patient.py`
  (per-country display maps for the two enumerable resources that
  do not fit the standard `clinosim.codes` lookup pattern).
- **JP Core profile URIs** — attached via `attach_ecs_institutional_extensions`
  and the JP Core Coverage profile URI (jpfhir.jp).
- **Family-history relationship coding** — HL7 v3-RoleCode (see the
  Issue #369 v23 regression rule documented in the
  [`family_history` module README](../../../family_history/README.md)
  — per-code JA displays are load-bearing).
- **Social-history SDOH anchor**: `_sdoh_effective_datetime`
  standardises the `effectiveDateTime` for smoking / alcohol / care-level
  by deriving it from the earliest encounter admission (matches
  `_fhir_care_level.py` C2-10 pattern).

## Directory contents

```
clinosim/modules/output/fhir_r4/demographics/
  __init__.py                    empty (builders imported by parent __init__)
  patient.py                     _build_patient + Coverage + payor Org + occupation + inline allergy (~600 LOC)
  practitioner.py                _build_practitioner + _build_practitioner_role
  family_history.py              _bb_family_history + _resolve_family_history_code + _build_relationship_codeable
  smoking_alcohol.py             _bb_smoking_status + _bb_alcohol_use + _sdoh_effective_datetime + _sdoh_performer_ref
```

## Testing

```bash
pytest tests/unit -k "patient or practitioner or family_history_relationship or smoking or alcohol" -q
```

Individual test files: `test_fhir_family_history_*.py`,
`test_fhir_family_history_relationship.py` (Issue #369 guard),
`test_fhir_sdoh.py` (integration), and patient / coverage tests
under `tests/unit/output/`.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
