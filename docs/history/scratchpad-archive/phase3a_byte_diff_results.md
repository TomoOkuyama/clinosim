# Phase 3a byte-diff results

**Date:** 2026-06-25
**Master:** 42657293 (PR #89 merged)
**Branch:** feat/phase3a-hai-lab-lift (commits eca5ce5d / 0e7827d0 / 55bbb2b5 / 3a8716a7)
**Cohort:** US p=2000 + JP p=2000, seed=42

## Summary

| Country | Files compared | IDENTICAL | same-count shift | count diff |
|---|---|---|---|---|
| US | 18 | **18** | 0 | 0 |
| JP | 19 | **19** | 0 | 0 |
| **Total** | **37** | **37** | **0** | **0** |

**ALL 37 NDJSON files byte-IDENTICAL.**

## Interpretation

This is the strongest possible byte-diff result — every byte of every
NDJSON file matches master. Three invariants confirmed:

1. **Main RNG untouched (AD-16 preserved):** moving device + hai from
   POST_RECORDS to POST_ENCOUNTER did NOT perturb the main simulation
   random stream. All Patient / Encounter / Condition / Medication* /
   Procedure / Imaging / Immunization / FamilyHistory / Coverage /
   Specimen / DiagnosticReport hashes match.

2. **Per-patient sub-seed determinism preserved:** device.ndjson +
   DeviceUseStatement.ndjson are byte-identical, confirming that the
   stage migration (POST_RECORDS -> POST_ENCOUNTER) does not change
   when or how the per-patient sub-seed
   (derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["device"],
   patient_id)) is consumed. The single-record enricher invocation
   produces the exact same RNG draws as the global-walk invocation,
   because each record already gets a fresh rng instance in both
   architectures.

3. **HAI lift is a Poisson rare-event at p=2000:**
   apply_hai_lab_lift was called for every encounter but produced
   zero observation modifications in this cohort. Observation.ndjson
   is byte-identical (US 194,900 lines + JP 180,224 lines — same hash
   as master). This matches the PR #89 acceptance:
   - US p=10000 -> ~4 HAI events (Poisson)
   - US p=2000  -> expected 0-1 HAI (Poisson rare-event)
   - JP p=5000  -> P(X=0) ~ 0.71, often 0 HAI
   - JP p=2000  -> expected 0 HAI

   The lift is exercised at p=10000 in the next step (3-axis DQR).

## Per-NDJSON detail

### US (18/18 IDENTICAL)

| NDJSON | sha256 (first 12) | lines |
|---|---|---|
| AllergyIntolerance.ndjson | fe0cc34c448d... | 190 |
| Condition.ndjson | 3d956150ab0b... | 30,157 |
| Device.ndjson | 403a64d071ee... | 25 |
| DeviceUseStatement.ndjson | dd7695d8dd3a... | 25 |
| DiagnosticReport.ndjson | ab3c3c88e288... | 2,644 |
| Encounter.ndjson | e42ed8fdc5b6... | 8,458 |
| FamilyMemberHistory.ndjson | 019429f74b85... | 3,665 |
| Immunization.ndjson | a74a4f4baf46... | 7,635 |
| Location.ndjson | 4034c5619ddd... | 60 |
| MedicationAdministration.ndjson | 583e72410586... | 37,771 |
| MedicationRequest.ndjson | ba09b148596c... | 4,966 |
| Observation.ndjson | c39e3d4a7641... | 194,900 |
| Organization.ndjson | 8c456ae340d3... | 8 |
| Patient.ndjson | eaa20a883ce8... | 1,312 |
| Practitioner.ndjson | f74eed6ed294... | 79 |
| PractitionerRole.ndjson | 68c35bc6007b... | 79 |
| Procedure.ndjson | 1540bf2dcc22... | 278 |
| Specimen.ndjson | 77c7009e8a76... | 35 |

### JP (19/19 IDENTICAL, +Coverage)

| NDJSON | sha256 (first 12) | lines |
|---|---|---|
| AllergyIntolerance.ndjson | b6351a8b0847... | 145 |
| Condition.ndjson | c0dc759252da... | 13,997 |
| Coverage.ndjson | 4b38733931b8... | 982 |
| Device.ndjson | 137f047a8385... | 2 |
| DeviceUseStatement.ndjson | 7848b884e507... | 2 |
| DiagnosticReport.ndjson | 7d9a9c10b416... | 2,442 |
| Encounter.ndjson | 5c7809607bed... | 6,321 |
| FamilyMemberHistory.ndjson | cb596316ed7a... | 2,746 |
| Immunization.ndjson | e282749e0d02... | 5,010 |
| Location.ndjson | a7edc3d2fd6f... | 60 |
| MedicationAdministration.ndjson | be27b576776c... | 38,697 |
| MedicationRequest.ndjson | e20217d11487... | 1,488 |
| Observation.ndjson | b56bd1d21be9... | 180,224 |
| Organization.ndjson | 80f2d43ca8c0... | 13 |
| Patient.ndjson | f88f3fa83040... | 982 |
| Practitioner.ndjson | 9cca8524abaf... | 81 |
| PractitionerRole.ndjson | eb0fd36d96cc... | 81 |
| Procedure.ndjson | a6220393905e... | 91 |
| Specimen.ndjson | f8e5771ff357... | 48 |

## Conclusion

**byte-diff PASS at strongest level (37/37 byte-IDENTICAL).**

The Phase 3a structural changes — POST_ENCOUNTER stage, device + hai
migration, apply_hai_lab_lift integration — preserve all existing
NDJSON output bit-for-bit at p=2000. The HAI lift mechanism is
implemented but doesn't fire in this small cohort due to Poisson
rare-event nature of CDC NHSN HAI baseline rates. The 3-axis DQR at
p=10000 (US) + p=5000 (JP) will exercise the lift and verify the
clinical relative-delta acceptance.
