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
    build_ucum_quantity,             # (value, unit) -> {value, unit, system, code}
    survey_category,                 # () -> [{coding: [...]}] survey category CodeableConcept
    loinc_coding,                    # (code, lang) -> {system, code, display}
    build_ecs_institution_extension, # JP JP_Organization_eCS institution
    build_ecs_department_extension,
    attach_ecs_institutional_extensions,
)
```

Every `_bb_*` bundle-builder function (~30 across the seven
domain subpackages) implements the same signature:
`_bb_<resource>(ctx: BundleContext) -> list[dict]`. Domain-README
files enumerate the per-family builders.

## Determinism

- FHIR emit is a pure serialisation over already-generated CIF; no
  RNG use, no seed offset in `ENRICHER_SEED_OFFSETS`.
- **Byte-identity contract** (AD-31 + AD-16): a given
  `(cif_dir, country, narrative_version)` tuple produces
  byte-identical NDJSON across runs.
- `_sort_ndjson_by_id_inplace` sorts each written NDJSON by resource
  id post-write so line order is deterministic regardless of
  traversal order.
- `_fhir_id_is_spec_valid` enforces the FHIR spec 64-char id +
  `[A-Za-z0-9\-\.]` character class at every emission site.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `is_us`, `resolve_lang`.
- `clinosim.modules.output.cif_reader` — `CIFReader` for structural
  + narrative-version-merged CIF load.
- `clinosim.codes` — code-system URI + display lookup.
- `clinosim.locale.loader` — locale-scoped code-mapping YAMLs.
- Every domain subpackage imports `lib.common.BundleContext` +
  shared fragment helpers (no cycle — `lib/` depends only on
  `clinosim.codes` + `clinosim.locale`).
- `json`, `os`, `re`, `uuid` — standard library serialisation.

## Constants and configuration

- **Bundle-builder registry** — `_BUNDLE_BUILDERS: list[Callable]`
  in `__init__.py`. Every `_bb_*` builder used by
  `_build_bundle` is imported at module top and appended.
  `register_bundle_builder` appends a new builder without editing
  the file (AD-56).
- **FHIR resource-id shape**: every builder produces
  `{resource_type_lower}-{encounter_id or patient_id}-{seq}`; the
  ID prefix constants are owned by their respective modules
  (`DOC_REFERENCE_ID_PREFIX` etc. in
  [`clinosim.modules.document`](../../document/README.md);
  `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` etc. in the
  `labs/service_request.py` file).
- **`BundleContext`** (`lib/common.py`): the read-only context
  passed to every `_bb_*` builder. Fields include `record`,
  `country`, `patient_id`, `primary_enc_id`, plus resolved
  language + code-mapping caches so builders do not repeat
  locale lookups.
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
  __init__.py                        convert_cif_to_fhir + registry + _bb_* wiring (581 LOC)
  lib/                               shared FHIR fragment helpers (common / localization / reference_data / inline_bb / generator_metadata / ids / ed_reattribution)
  demographics/                      Patient / Practitioner / FamilyMemberHistory / smoking + alcohol Observation
  encounters/                        Encounter / CareTeam / CareLevel / Location + Organization (facility) / Endpoint
  medications/                       MedicationRequest + MedicationAdministration
  labs/                              Observation (lab + vitals) / DiagnosticReport / ServiceRequest / microbiology / ImagingStudy / blood_type / coding_package + coding_strategy
  procedures/                        Procedure / Immunization / Device + DeviceUseStatement / nursing (survey Observation)
  conditions/                        Condition / AllergyIntolerance / ClinicalImpression / HAI Condition / CodeStatus (custom Observation)
  documents/                         Composition / DocumentReference / DocumentReference (checkup / eCheckup)
  post_process/                      bundle-level pipeline (datetime normalise / profile / specimen / strip / populate)
```

## FHIR resource → domain mapping (canonical table)

| FHIR resource | Domain module |
|---|---|
| Patient | `demographics/patient.py` |
| Practitioner + PractitionerRole | `demographics/practitioner.py` |
| FamilyMemberHistory | `demographics/family_history.py` |
| Observation (smoking / alcohol / social) | `demographics/smoking_alcohol.py` |
| Encounter | `encounters/encounter.py` |
| CareTeam | `encounters/care_team.py` |
| CareLevel (custom `jp-care-level` Observation) | `encounters/care_level.py` |
| Location + Organization | `encounters/facility.py` |
| Endpoint | `encounters/endpoint.py` |
| MedicationRequest + MedicationAdministration | `medications/medications.py` |
| Observation (lab + vitals) | `labs/observations.py` |
| DiagnosticReport | `labs/diagnostic_report.py` |
| ServiceRequest | `labs/service_request.py` |
| Observation (microbiology) | `labs/microbiology.py` |
| ImagingStudy | `labs/imaging_study.py` |
| Observation (ABO + RhD) | `labs/blood_type.py` |
| — (JP-CLINS lab code loader) | `labs/coding_package.py` |
| — (JP-CLINS lab code dispatch) | `labs/coding_strategy.py` |
| Procedure | `procedures/procedures.py` |
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
(`clinosim audit run`) exercise the five AD-60 plug-ins (hai /
antibiotic / order / imaging / document) that cross-verify FHIR
emission contracts.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
