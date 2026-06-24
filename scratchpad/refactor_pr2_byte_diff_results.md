# PR2 (AD-55 Foundation Refactor G2 SDOH Integrity) byte-diff results

**Setup**: US/JP p=2000 seed=42, format=fhir-r4 vs master `36ac9afd`.

## Result: ALL 11 NDJSON IDENTICAL ✓

Pure mechanical refactor preserved byte-identical output as required.

### US (p=2000)

| File | Status | master lines |
|---|---|---:|
| Patient.ndjson | IDENTICAL | 1,322 |
| Encounter.ndjson | IDENTICAL | 8,486 |
| Condition.ndjson | IDENTICAL | 30,250 |
| MedicationRequest.ndjson | IDENTICAL | 5,133 |
| MedicationAdministration.ndjson | IDENTICAL | 39,181 |
| Procedure.ndjson | IDENTICAL | 286 |
| ImagingStudy.ndjson | ABSENT both | — |
| Immunization.ndjson | IDENTICAL | 7,706 |
| FamilyMemberHistory.ndjson | IDENTICAL | 3,717 |
| **Observation.ndjson** | **IDENTICAL** | **199,492** |
| DiagnosticReport.ndjson | IDENTICAL | 2,657 |

### JP (p=2000)

| File | Status | master lines |
|---|---|---:|
| Patient.ndjson | IDENTICAL | 969 |
| Encounter.ndjson | IDENTICAL | 6,294 |
| Condition.ndjson | IDENTICAL | 13,944 |
| MedicationRequest.ndjson | IDENTICAL | 1,381 |
| MedicationAdministration.ndjson | IDENTICAL | 33,078 |
| Procedure.ndjson | IDENTICAL | 83 |
| ImagingStudy.ndjson | ABSENT both | — |
| Immunization.ndjson | IDENTICAL | 4,950 |
| FamilyMemberHistory.ndjson | IDENTICAL | 2,713 |
| **Observation.ndjson** | **IDENTICAL** | **163,662** |
| DiagnosticReport.ndjson | IDENTICAL | 2,237 |

## What this confirms

Critically, **Observation.ndjson is byte-identical despite the SDOH builder rewrite** — confirms:

- 6 SNOMED enum→code mappings in YAML (loaded via `load_social_history()`) produce numerically identical output to pre-PR2 hardcoded Python dicts
- `_social_category()` + `_value()` promoted to `_fhir_common.py` produce bit-identical fragments to former `_fhir_sdoh.py` local versions
- `_BUNDLE_BUILDERS` registration order preserved → no reordering of Observation serialization (smoking / alcohol / care_level in same order)
- LOINC display lookup (`code_lookup("loinc", "72166-2", "en")`) and SNOMED display lookup unchanged
- i18n text strings ("喫煙状況" / "Tobacco smoking status" / "飲酒歴" / "History of alcohol use" / "要介護度" / "Long-term care need level") preserved as Python literals in new builder files
- Same `id` patterns (`smoking-{patient_id}`, `alcohol-{patient_id}`, `carelevel-{patient_id}`) and `subject` references

## Acceptance

**ACCEPTED**. PR2 G2 SDOH integrity refactor preserves byte-identical output across all 11 NDJSON files for both US and JP at p=2000 seed=42. The split + YAML migration + helper promotion is byte-safe and ready for merge.
