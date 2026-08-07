# PR1 (AD-55 Foundation Refactor G1) byte-diff results

**Setup**: US/JP p=2000 seed=42, format=fhir-r4 vs master `dcb47ccc`.

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

- **AD-16** master RNG stream unaffected — all sub-seed numerical values preserved through the central registry (`ENRICHER_SEED_OFFSETS`)
- **AD-59** per-order sub-rng unaffected — `panel_specimen_seed` / `individual_lab_seed` unchanged
- **All 7 module sub-seed offsets numerically identical** — registry values match pre-refactor module-local constants (cross-verified by `test_seeding.py::test_formula_is_pinned` continuing to pass with the precomputed literals 914786652 / 914785364 / 2694613518)
- **`_get` → `get_attr_or_key` alias** behaves identically (call sites untouched via `as _get`)
- **`care_level.load_rates(country: str = "JP")`** behaves identically for the only existing caller path (JP-gated, country defaults to "JP" so existing zero-arg call equivalent)

## Acceptance

**ACCEPTED**. PR1 G1 structural DRY refactor preserves byte-identical output across all 11 NDJSON files for both US and JP at p=2000 seed=42. The mechanical refactor is byte-safe and ready for merge.
