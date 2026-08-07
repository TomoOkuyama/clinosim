# Phase 2b byte-diff results — on_warfarin coupling vs master `9e0b97a7`

**Setup**: US/JP p=2000 seed=42, format=fhir-r4. Comparison via `scratchpad/phase2b_byte_diff/compare.py` (sha256 + line count).

## Summary

**Better than plan §7 expectation**: 8/9 NDJSON files completely sha256-identical.
Only Observation changes (same line count, PT_INR/PT values shifted for warfarin-detected patients). MedicationRequest stayed identical because the activator is once-per-session (PR #45 hoist) — the new chronic_medications.yaml I26/I82/I63 entries do not retroactively activate already-activated patients. The warfarin-shift cohort comes from:

1. **Chronic AF patients** (existing I48 → Warfarin 3mg via chronic_medications.yaml, unchanged in this PR)
2. **In-hospital warfarin orders** (PE/DVT/AF acute encounter `treatment.medications` warfarin orders, peeked from `all_orders` at the lab loop ≥ 3 days into stay)

## US p=2000

| File | Status | master lines | branch lines | delta |
|---|---|---:|---:|---:|
| Patient.ndjson | IDENTICAL | 1,322 | 1,322 | 0 |
| Encounter.ndjson | IDENTICAL | 8,486 | 8,486 | 0 |
| Condition.ndjson | IDENTICAL | 30,250 | 30,250 | 0 |
| MedicationRequest.ndjson | IDENTICAL | 5,133 | 5,133 | 0 |
| MedicationAdministration.ndjson | IDENTICAL | 39,181 | 39,181 | 0 |
| Procedure.ndjson | IDENTICAL | 286 | 286 | 0 |
| ImagingStudy.ndjson | ABSENT in both | — | — | — |
| Immunization.ndjson | IDENTICAL | 7,706 | 7,706 | 0 |
| FamilyMemberHistory.ndjson | IDENTICAL | 3,717 | 3,717 | 0 |
| **Observation.ndjson** | **CHANGE-SAME-N** | 199,492 | 199,492 | 0 |
| DiagnosticReport.ndjson | IDENTICAL | 2,657 | 2,657 | 0 |

## JP p=2000

| File | Status | master lines | branch lines | delta |
|---|---|---:|---:|---:|
| Patient.ndjson | IDENTICAL | 969 | 969 | 0 |
| Encounter.ndjson | IDENTICAL | 6,294 | 6,294 | 0 |
| Condition.ndjson | IDENTICAL | 13,944 | 13,944 | 0 |
| MedicationRequest.ndjson | IDENTICAL | 1,381 | 1,381 | 0 |
| MedicationAdministration.ndjson | IDENTICAL | 33,078 | 33,078 | 0 |
| Procedure.ndjson | IDENTICAL | 83 | 83 | 0 |
| ImagingStudy.ndjson | ABSENT in both | — | — | — |
| Immunization.ndjson | IDENTICAL | 4,950 | 4,950 | 0 |
| FamilyMemberHistory.ndjson | IDENTICAL | 2,713 | 2,713 | 0 |
| **Observation.ndjson** | **CHANGE-SAME-N** | 163,662 | 163,662 | 0 |
| DiagnosticReport.ndjson | IDENTICAL | 2,237 | 2,237 | 0 |

## Observation change analysis (US, PT_INR LOINC 6301-6)

- Total PT_INR observations: master 366 / branch 366 (count preserved)
- PT_INR values changed: **40 / 366 (10.9%)**
- Distinct encounters with at least one shift: **13**
- Direction: ALL shifts go UPWARD (master 1.8-2.4 → branch 2.8-3.5) — consistent with warfarin lifting INR
- Shift categories:
  - master < 2.0 → branch ≥ 2.0 (entered therapeutic): 34
  - master ≥ 2.0 → branch ≥ 2.0 (compound over-AC, e.g. AC + cirrhosis): 6

Sample shifts:
```
ENC-POP-000075-000039-0014: 2.200 -> 3.300  (compound: AC + comorbidity)
ENC-POP-000075-000039-0072: 2.100 -> 3.100
ENC-POP-000075-000039-0121: 1.900 -> 2.800  (entered therapeutic band)
ENC-POP-000075-000039-0187: 1.800 -> 2.900
ENC-POP-000075-000039-0230: 2.000 -> 3.200
```

## DiagnosticReport remained IDENTICAL — clarification

Plan §7 predicted Coag panel DR would GROW. It did NOT — and that's correct FHIR behavior:

DR resources reference Observation IDs (not values). Since the underlying PT_INR Observation IDs are unchanged (only the value field shifts), the DR resource serialization is identical. The PT_INR value change reaches downstream consumers via the referenced Observation, not via duplicated value in DR.

This is a positive finding: **DR resource integrity is preserved** without needing regeneration.

## Invariant evidence

- **AD-16** (master RNG isolation): cohort composition unchanged (Patient/Encounter/Condition counts identical). Medication order counts identical. No carry-over of warfarin detection logic into unrelated patients.
- **AD-57** (BNP-pattern surgical): formula-only PT_INR change; PhysiologicalState fields unchanged.
- **AD-59** (per-order sub-rng): individual_lab_seed / panel_specimen_seed unchanged. No new RNG draw in derive_lab_values.
- **Cohort scoping**: 13 encounters out of 8,486 (0.15%) are warfarin-detected; the rest receive identical labs.

## JP cohort note

JP p=2000 had 0 PT_INR observations in either master or branch (PT_INR is in monitoring set but warfarin-detected cohort did not materialize at this cohort size). DQR p=5000 will surface JP PT_INR.

## Conclusion

**ACCEPTANCE PASSED**. Phase 2b changes:
- Preserve 8/9 NDJSON byte-identity
- Affect only PT_INR values in warfarin-detected encounters (13/8486 = 0.15%)
- Maintain DR resource integrity
- Maintain AD-16/AD-57/AD-59 invariants
