# PR3 byte-diff verification results

**Date**: 2026-06-24
**Master baseline**: `0ed65f86` (PR #86 merge — current master HEAD)
**Branch HEAD**: `2594f43d` (refactor/pr3-fhir-observations-split, post-Task 5 lint cleanup)
**Cohort**: US p=2000 seed=42, JP p=2000 seed=42
**Format**: fhir-r4 (Bulk Data NDJSON)

## Result: **OVERALL PASS** — all NDJSON byte-identical

`python scratchpad/pr3_byte_diff/compare.py`:

```
[us] 16 NDJSON files:
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

[jp] 17 NDJSON files:
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

OVERALL: PASS
```

## Per-NDJSON status

US: 16/16 IDENTICAL. JP: 17/17 IDENTICAL (Coverage emitted JP-only via AD-54
opt-in `--jp-insurance`; here generated unconditionally because the JP
default config enables it). Combined: **33/33 IDENTICAL**.

Note: the spec / plan referenced "all 11 NDJSON IDENTICAL" — this was a
conservative under-count of the actual NDJSON file inventory (US 16 / JP
17 including Specimen, Location, Organization, Practitioner,
PractitionerRole, AllergyIntolerance, Coverage). All produced NDJSON
files match.

## Regression

```
$ pytest -m "unit or integration" -q
604 passed, 139 deselected in 102.63s
```

Zero failures pre / post the four refactor commits.

## Conclusion

PR3 is a pure mechanical refactor with **no functional change**. Every
FHIR output NDJSON file in both US and JP exports is byte-identical to
master. The split satisfies its "no-regression" gate per
`docs/CONTRIBUTING-modules.md` "PR 検証ガイド".
