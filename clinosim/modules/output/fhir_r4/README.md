# `fhir_r4/` — FHIR R4 output subsystem

Layout: shared library + 7 clinical-domain builder subpackages + post-processing.

- `lib/` — shared helpers (`common`, `localization`, `reference_data`, `inline_bb`, `generator_metadata`, `ids`).
- `demographics/`, `encounters/`, `medications/`, `labs/`, `procedures/`, `conditions/`, `documents/` — resource builders grouped by clinical domain.
- `post_process/` — bundle-level pipeline (PR3, folds Issue #556).

The subpackage's `__init__.py` is the public facade (`register_bundle_builder`, `available_builders`, `convert_cif_to_fhir`, ...). A thin shim at `../fhir_r4_adapter.py` re-exports the same surface for backward compatibility.

## FHIR resource → domain mapping

| FHIR resource | Domain module |
|---|---|
| Patient | `demographics/patient.py` |
| Practitioner | `demographics/practitioner.py` |
| FamilyMemberHistory | `demographics/family_history.py` |
| Observation (smoking / alcohol / social) | `demographics/smoking_alcohol.py` |
| Encounter | `encounters/encounter.py` |
| CareTeam | `encounters/care_team.py` |
| CareLevel (custom Observation) | `encounters/care_level.py` |
| Location + Organization | `encounters/facility.py` |
| Endpoint | `encounters/endpoint.py` |
| MedicationRequest, MedicationAdministration | `medications/medications.py` |
| Observation (lab + vitals) | `labs/observations.py` |
| DiagnosticReport | `labs/diagnostic_report.py` |
| ServiceRequest | `labs/service_request.py` |
| Observation (microbiology) | `labs/microbiology.py` |
| ImagingStudy | `labs/imaging_study.py` |
| — (JP-CLINS lab code loader) | `labs/coding_package.py` |
| — (JP-CLINS lab code dispatch) | `labs/coding_strategy.py` |
| Procedure | `procedures/procedures.py` |
| Immunization | `procedures/immunization.py` |
| Device, DeviceUseStatement | `procedures/device.py` |
| Observation (nursing flowsheet) | `procedures/nursing.py` |
| Condition | `conditions/conditions.py` |
| AllergyIntolerance | `conditions/allergy_intolerance.py` |
| ClinicalImpression | `conditions/clinical_impression.py` |
| Condition (HAI) | `conditions/hai.py` |
| CodeStatus (custom Observation) | `conditions/code_status.py` |
| Composition | `documents/composition.py` |
| DocumentReference | `documents/documents.py` |
| DocumentReference (checkup / eCheckup) | `documents/document_reference_checkup.py` |

For post-processing (bundle finalization, JP-CLINS profile application, timestamp normalization, specimen synthesis), see `post_process/` (PR3, folds Issue #556).
