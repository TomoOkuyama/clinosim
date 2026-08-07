# PR-B hai byte-diff supplement results

**Date**: 2026-06-24
**Master baseline**: `3093fa71` (PR #88 merge)
**Branch HEAD**: `feat/hai-module-prb` (post-Task 9 lint + LOINC dedup)
**Cohort**: US p=2000 seed=42, JP p=2000 seed=42

## Result: OVERALL PASS — all 37 NDJSON IDENTICAL

`python scratchpad/hai_byte_diff/compare.py` reports US 18 + JP 19 = 37
NDJSON files all IDENTICAL between master and branch. At p=2000 seed=42,
the HAI sampling produces 0 onsets in this cohort lottery (Poisson rare
event), so even HAI-affected files (Condition / Specimen / Observation /
DR) match.

## Implementation note

Initial byte-diff: DR + Observation showed DIFFER on a single line.
Root cause: PR-B Task 1 introduced 3 LOINC entries (`600-7` / `630-4`
/ `624-7`) that collided with existing PR3 microbiology entries
(`600-7` / `630-4` / `619-7`). Last-wins YAML overwrote canonical
displays. Fix: removed PR-B's duplicate `loinc.yaml` entries and
updated `hai_specimens.yaml` VAP entry to use existing `619-7`
"Bacteria identified in Sputum by Culture" instead of the spec's
tentative `624-7`. Re-run after fix → all 37 NDJSON IDENTICAL.

## Interpretation

- Pre-existing NDJSON byte-identical → hai enricher's independent
  sub-seed (`ENRICHER_SEED_OFFSETS["hai"] = 0x4841`) + per-patient
  derive_sub_seed do not perturb main RNG (AD-16 / AD-56)
- HAI Condition / culture chain: 0 instances at p=2000 (CDC NHSN
  baseline × ~7 line-days × ~6% ICU rate ≈ 0.4 HAIs/type — Poisson
  allows 0)
- 3-axis DQR (Task 11) uses p=10000 US + p=5000 JP for robust validation

## Conclusion

PR-B does not regress pre-existing FHIR output. Larger cohorts in
Task 11 DQR will produce HAI Conditions. Goal gate is Task 11 3-axis
DQR; byte-diff is the no-regression supplement.
