# PR-A device byte-diff supplement results

**Date**: 2026-06-24
**Master baseline**: `89969152` (current master HEAD, PR #87 merge)
**Branch HEAD**: `feat/device-module-pra` (post-Task 9 lint cleanup + chore)
**Cohort**: US p=2000 seed=42, JP p=2000 seed=42
**Format**: fhir-r4 (Bulk Data NDJSON)

## Purpose

PR-A is a **new feature** PR. The goal gate is 3-axis DQR (Task 11),
not byte-diff. This supplement run confirms the secondary invariant —
**main RNG stream untouched** — by verifying every pre-existing NDJSON
file is byte-identical between master and branch. New `Device.ndjson`
+ `DeviceUseStatement.ndjson` files are intentional additions.

## Result: **OVERALL PASS**

`python scratchpad/device_byte_diff/compare.py`:

```
[us] 16 pre-existing NDJSON:
  AllergyIntolerance.ndjson                IDENTICAL
  Condition.ndjson                         IDENTICAL
  DiagnosticReport.ndjson                  IDENTICAL
  Encounter.ndjson                         IDENTICAL
  FamilyMemberHistory.ndjson               IDENTICAL
  Immunization.ndjson                      IDENTICAL
  Location.ndjson                          IDENTICAL
  MedicationAdministration.ndjson          IDENTICAL
  MedicationRequest.ndjson                 IDENTICAL
  Observation.ndjson                       IDENTICAL
  Organization.ndjson                      IDENTICAL
  Patient.ndjson                           IDENTICAL
  Practitioner.ndjson                      IDENTICAL
  PractitionerRole.ndjson                  IDENTICAL
  Procedure.ndjson                         IDENTICAL
  Specimen.ndjson                          IDENTICAL
[us] new files: ['Device.ndjson', 'DeviceUseStatement.ndjson']

[jp] 17 pre-existing NDJSON:
  AllergyIntolerance.ndjson                IDENTICAL
  Condition.ndjson                         IDENTICAL
  Coverage.ndjson                          IDENTICAL
  DiagnosticReport.ndjson                  IDENTICAL
  Encounter.ndjson                         IDENTICAL
  FamilyMemberHistory.ndjson               IDENTICAL
  Immunization.ndjson                      IDENTICAL
  Location.ndjson                          IDENTICAL
  MedicationAdministration.ndjson          IDENTICAL
  MedicationRequest.ndjson                 IDENTICAL
  Observation.ndjson                       IDENTICAL
  Organization.ndjson                      IDENTICAL
  Patient.ndjson                           IDENTICAL
  Practitioner.ndjson                      IDENTICAL
  PractitionerRole.ndjson                  IDENTICAL
  Procedure.ndjson                         IDENTICAL
  Specimen.ndjson                          IDENTICAL
[jp] new files: ['Device.ndjson', 'DeviceUseStatement.ndjson']

OVERALL: PASS
```

## Per-country totals

| Country | Pre-existing NDJSON IDENTICAL | New NDJSON added | Device count |
|---|---|---|---|
| US p=2000 | 16/16 | Device + DeviceUseStatement | 25 |
| JP p=2000 | 17/17 (incl. Coverage) | Device + DeviceUseStatement | 2 |

## Interpretation

- **Pre-existing NDJSON**: 33/33 byte-identical. The device enricher's
  independent sub-seed (`ENRICHER_SEED_OFFSETS["device"] = 0x4445`) and
  patient-id-scoped derive_sub_seed do not perturb the main RNG stream.
  Conforms to AD-16 + AD-56 contract.
- **New NDJSON**: Device + DeviceUseStatement intentionally added.
  Phase 2 PR-B will read these via `extensions["device"]` and emit
  HAI Condition + Observation resources.
- **JP device count (2) much lower than US (25)**: JP cohort at p=2000
  has fewer ICU-bound presentations in the calibrated catchment;
  expected behavior given the existing patient mix. 3-axis DQR (Task 11)
  uses larger cohorts (US p=10000 / JP p=5000) for robust clinical
  validation.

## Conclusion

PR-A does not regress any pre-existing FHIR output. The new feature
adds two intentional resource types via the AD-56 builder registry.
The byte-diff supplement passes the no-regression invariant; the
goal-achievement gate (3-axis DQR) is Task 11.
