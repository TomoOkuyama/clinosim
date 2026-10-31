# `fhir_r4/` — FHIR R4 output subsystem

## Purpose

Emits FHIR R4 Bulk-Data NDJSON from generated CIF (AD-31 —
one NDJSON per resource type + `manifest.json`, no per-encounter
Bundle wrapping). Owns the AD-56 `register_bundle_builder` /
`_BUNDLE_BUILDERS` plug-in surface, per-domain resource builders
(seven clinical-domain subpackages), shared FHIR fragment helpers
(`lib/`), and the post-processing pipeline (`post_process/`) that
finalises timestamps, JP-CLINS profiles, specimens, and bundle
stripping.

`convert_cif_to_fhir` is the top-level entry point every downstream
adapter calls (the built-in `FhirR4Adapter` in
[`../adapters_builtin.py`](../adapters_builtin.py) wraps it).

## Scope

- **In scope**: `_BUNDLE_BUILDERS` registry + `register_bundle_builder`
  + `available_builders`; `convert_cif_to_fhir` orchestrator
  (reads CIF via `CIFReader`, walks patients, calls every builder,
  applies post-processing, writes NDJSON per resource type + manifest);
  `_build_bundle` fan-out; `_fhir_id_is_spec_valid` guard;
  `_sort_ndjson_by_id_inplace` post-write sort; the seven clinical
  domain subpackages (`conditions/`, `demographics/`, `documents/`,
  `encounters/`, `labs/`, `medications/`, `procedures/`); the
  shared library (`lib/`); the post-processing pipeline
  (`post_process/`).
- **Out of scope**: CIF generation itself; adapter registry
  ([`../adapter.py`](../adapter.py)); CIF writer / reader
  ([`../cif_writer.py`](../cif_writer.py) +
  [`../cif_reader.py`](../cif_reader.py)); JSON serialisation
  (delegated to Python's `json` module).

## Public API

```python
from clinosim.modules.output.fhir_r4 import (
    convert_cif_to_fhir,             # (cif_dir, out_dir, country="US", narrative_version="current") -> None
    register_bundle_builder,         # (fn) — AD-56 plug-in registration
    available_builders,              # () -> list[str] of registered builder names
    _fhir_id_is_spec_valid,          # (rid) -> bool  (guard used by tests + builders)
)
from clinosim.modules.output.fhir_r4.lib.common import (
    BundleContext,                   # dataclass passed to every _bb_* builder
    entry,                           # (resource) -> Bundle entry dict
    survey_category,                 # () -> [{coding: [...]}] survey category CodeableConcept
    loinc_coding,                    # (code, lang) -> {system, code, display}
    build_ecs_institution_extension, # JP JP_Organization_eCS institution
    build_ecs_department_extension,
    attach_ecs_institutional_extensions,
)
```

Every `_bb_*` bundle-builder function implements the same signature:
`_bb_<resource>(ctx: BundleContext) -> list[dict]`. The default
registry holds 45 builders: 27 in the seven domain subpackages, 11 in
`lib/inline_bb.py` (Patient, Coverage, Encounter, Condition,
Occupation, vitals, MedicationRequest / discharge MedicationRequest,
MedicationAdministration, Procedure, Practitioner) and 7 newborn
builders in [`clinosim/modules/newborn/fhir_emit.py`](../../newborn/fhir_emit.py).
Domain-README files enumerate the per-family builders.

## Determinism

- FHIR emit is a pure serialisation over already-generated CIF; no
  RNG use, no seed offset in `ENRICHER_SEED_OFFSETS`.
- **Byte-identity contract** (AD-31 + AD-16): a given
  `(cif_dir, country, narrative_version)` tuple produces
  byte-identical NDJSON across runs.
- `_sort_ndjson_by_id_inplace` sorts each written NDJSON by resource
  id post-write so line order is deterministic regardless of
  traversal order.
- `_fhir_id_is_spec_valid` checks the FHIR spec 64-char id +
  `[A-Za-z0-9\-\.]` character class in the NDJSON writer of
  `convert_cif_to_fhir`; it is fail-soft (invalid ids are counted
  per resource type and logged as a warning, the write proceeds).

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang` (and other
  helpers in individual builders).
- `clinosim.modules.output.cif_reader` — `CIFReader` for structural
  + narrative-version-merged CIF load.
- `clinosim.codes` — code-system URI + display lookup.
- `clinosim.locale.loader` — locale-scoped code-mapping YAMLs.
- `clinosim.modules.newborn.fhir_emit` — the seven `_bb_newborn_*`
  builders in the registry.
- `clinosim.simulator.log` — export progress events.
- Every domain subpackage imports `lib.common.BundleContext` +
  shared fragment helpers. `lib/common.py` itself has no domain
  imports, but `lib/inline_bb.py` imports builder helpers from the
  domain subpackages (and `lib/ed_reattribution.py` from
  `encounters/`), so `lib/` as a whole is not a leaf.
- `heapq`, `json`, `os`, `re`, `tempfile`, `uuid` — standard library
  (serialisation + the external-merge NDJSON sort).

## Constants and configuration

- **Bundle-builder registry** — `_BUNDLE_BUILDERS: list[Callable]`
  in `builder.py` (re-exported by `__init__.py`). List order is
  emission order. Every `_bb_*` builder used by `_build_bundle` is
  imported at module top and listed; an import-time assert enforces
  the `_bb_` prefix. `register_bundle_builder` appends a new builder
  without editing the file (AD-56), rejects names without the `_bb_`
  prefix (`ValueError`) and de-duplicates by function name.
- **FHIR resource-id shape**: each builder owns its id scheme (e.g.
  `allergy-{patient_id}-{nn}`, `loc-ward-{ward}`, `sr-…`, `doc-…`;
  `lib/ids.py` derives opaque ids); the ID prefix constants are owned
  by their respective modules
  (`DOC_REFERENCE_ID_PREFIX` etc. in
  [`clinosim.modules.document`](../../document/README.md);
  `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` etc. in the
  `labs/service_request.py` file).
- **`BundleContext`** (`lib/common.py`): the read-only context
  passed to every `_bb_*` builder. Fields: `record`, `country`,
  `roster_map`, `hospital_config`, `patient_data`, `patient_id`,
  `is_readmission`, `prior_encounter_id`, `primary_dx_code`,
  `admit_dx_code`, `admit_dx_system`, `primary_enc_id`,
  `patient_sex`, `encounter_resource_index`, `snapshot_date`,
  `emitted_mr_ids`.
- **JP-CLINS extensions** (`lib/common.py`):
  `build_ecs_institution_extension`,
  `build_ecs_department_extension`,
  `attach_ecs_institutional_extensions` — the eCS (electronic
  Clinical Statement) institution / department extensions the
  JP-CLINS Composition profile requires.
- **Post-processing pipeline** ([`post_process/`](post_process/README.md)) —
  bundle-level pipeline (PR3, folds Issue #556): timestamp
  normalisation, JP-CLINS profile URIs, specimen synthesis, strip
  passes.

## Directory contents

```
clinosim/modules/output/fhir_r4/
  __init__.py                        thin re-export facade (public + back-compat private names)
  builder.py                         convert_cif_to_fhir + _BUNDLE_BUILDERS registry + _build_bundle + snapshot / death reconciliation + NDJSON sort
  lib/                               shared FHIR fragment helpers (common / localization / reference_data / inline_bb / generator_metadata / ids / ed_reattribution)
  demographics/                      Patient / Practitioner / FamilyMemberHistory / smoking + alcohol Observation
  encounters/                        Encounter / CareTeam / CareLevel / Location + Organization (facility) / Endpoint
  medications/                       MedicationRequest + MedicationAdministration
  labs/                              Observation (lab + vitals) / DiagnosticReport / ServiceRequest / microbiology / ImagingStudy / blood_type / anthropometrics / stage_scale_observations / _reference_ranges / coding_package + coding_strategy
  procedures/                        Procedure / Immunization / Device + DeviceUseStatement / nursing (survey Observation) / oxygen_therapy / procedure_name_snomed (.py + .yaml)
  conditions/                        Condition / AllergyIntolerance / ClinicalImpression / HAI Condition / CodeStatus (custom Observation) / primary_ref
  documents/                         Composition / DocumentReference / DocumentReference (checkup / eCheckup) / imaging_report / referral_orgs / jp_clins/ (per-document JP-CLINS section builders)
  post_process/                      bundle-level pipeline (datetime normalise / profile / specimen / strip / populate)
```

## FHIR resource → domain mapping (canonical table)

| FHIR resource | Domain module |
|---|---|
| Patient | `demographics/patient.py` (registry entry `_bb_patient` in `lib/inline_bb.py`) |
| Coverage | `lib/inline_bb.py` (`_bb_coverage`) |
| Observation (occupation) | `lib/inline_bb.py` (`_bb_occupation`) |
| Practitioner + PractitionerRole | `demographics/practitioner.py` |
| FamilyMemberHistory | `demographics/family_history.py` |
| Observation (smoking / alcohol / social) | `demographics/smoking_alcohol.py` |
| Encounter | `encounters/encounter.py` |
| CareTeam | `encounters/care_team.py` |
| CareLevel (custom `jp-care-level` Observation) | `encounters/care_level.py` |
| Location + Organization | `encounters/facility.py` |
| Endpoint | `encounters/endpoint.py` |
| MedicationRequest + MedicationAdministration | `medications/medications.py` (registry entries in `lib/inline_bb.py`) |
| Observation (lab + vitals) | `labs/observations.py` (`_bb_vitals` registry entry in `lib/inline_bb.py`) |
| Observation (height / weight / BMI / head circumference) | `labs/anthropometrics.py` |
| Observation (chronic-disease stage scale) | `labs/stage_scale_observations.py` |
| Newborn Apgar / bilirubin / CCHD Observation; metabolic-screen ServiceRequest / Specimen / Observation / DiagnosticReport | [`clinosim/modules/newborn/fhir_emit.py`](../../newborn/fhir_emit.py) |
| DiagnosticReport | `labs/diagnostic_report.py` |
| ServiceRequest | `labs/service_request.py` |
| Observation (microbiology) | `labs/microbiology.py` |
| ImagingStudy | `labs/imaging_study.py` |
| Observation (ABO + RhD) | `labs/blood_type.py` |
| — (JP-CLINS lab code loader) | `labs/coding_package.py` |
| — (JP-CLINS lab code dispatch) | `labs/coding_strategy.py` |
| Procedure | `procedures/procedures.py` (registry entry `_bb_procedures` in `lib/inline_bb.py`) |
| Procedure (oxygen-therapy session) | `procedures/oxygen_therapy.py` |
| Immunization | `procedures/immunization.py` |
| Device + DeviceUseStatement | `procedures/device.py` |
| Observation (nursing flowsheet) | `procedures/nursing.py` |
| Condition (primary + secondary + chronic) | `conditions/conditions.py` |
| AllergyIntolerance | `conditions/allergy_intolerance.py` |
| ClinicalImpression | `conditions/clinical_impression.py` |
| Condition (HAI) | `conditions/hai.py` |
| CodeStatus (custom Observation) | `conditions/code_status.py` |
| Composition | `documents/composition.py` |
| DocumentReference | `documents/documents.py` |
| DocumentReference (checkup / eCheckup) | `documents/document_reference_checkup.py` |
| Composition (imaging report) | `documents/imaging_report.py` |

## Enricher wiring

Not applicable — this is a serialisation layer, not an enricher. It
is not registered with `register_builtin_enrichers` and has no seed
offset in `ENRICHER_SEED_OFFSETS`.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Built-in FHIR adapter | [`../adapters_builtin.py`](../adapters_builtin.py) (`FhirR4Adapter.convert`) | Wraps `convert_cif_to_fhir` for the AD-58 registry. |
| Backwards-compat shim | [`../fhir_r4_adapter.py`](../fhir_r4_adapter.py) | Re-exports the whole public surface for pre-migration callers (Issue #555 PR1). |
| Downstream tools | (external) | NDJSON + manifest.json per Bulk Data Access spec — HAPI FHIR, InferNo, etc. |

## Testing

```bash
pytest tests/unit -k "fhir or output" -q
pytest tests/integration -k "fhir or export or servicerequest_chain or document_chain or hai_susceptibility" -q
```

Each domain subpackage has its own README + tests; audit runs
(`clinosim audit run`) exercise the AD-60 module audit plug-ins
(hai / antibiotic / order / imaging / document / triage), several of
which cross-verify FHIR emission contracts.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
