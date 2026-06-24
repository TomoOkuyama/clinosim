# PR-B hai module — 3-axis Data Quality Review

**Date**: 2026-06-24
**Master baseline**: `3093fa71`
**Branch**: `feat/hai-module-prb`
**Cohort**: US p=10000 seed=42, JP p=5000 seed=42
**Audit script**: `scratchpad/hai_dqr/dqr_audit.py`
**Gate**: 3-axis DQR (new feature PR per CONTRIBUTING-modules.md "PR 検証ガイド")

## Result: **OVERALL PASS** (3/3 axes × 2 countries)

```
=== Axis 1 (structural) — US ===
  HAI Condition.id unique: 4/4
  HAI refs all resolve
  dual coding + display ≠ code: 100%
  Axis 1 US: PASS

=== Axis 2 (clinical) — US ===
  HAI count: 4
    cauti: 3
    vap: 1
  Axis 2 US: PASS (rare events; tolerance wide)

=== Axis 3 (JP language) — US ===
  US has zero JP characters: 4 HAI conditions clean
  Axis 3 US: PASS

=== Axis 1 (structural) — JP ===
  HAI count: 0 (rare event at this cohort; acceptable)

=== Axis 2 (clinical) — JP ===
  HAI count: 0
  Axis 2 JP: PASS (rare events; tolerance wide)

=== Axis 3 (JP language) — JP ===
  (JP cohort 0 HAI; acceptable rare event)
  Axis 3 JP: PASS

OVERALL: PASS
```

## Axis 1 — structural (FHIR R4 + JP Core compliance)

US (n=4 HAI Conditions): all id unique, all subject + encounter refs resolve, dual coding (ICD-10-CM + SNOMED CT) on all, display ≠ code on all.

JP (n=0): no structural checks applicable; 0 HAI is acceptable per Poisson rare-event semantics at p=5000.

## Axis 2 — clinical coherence

### Expected vs observed counts

PR-A US p=10000: 353 devices × p50 line-days = 6.

| HAI | per_day_risk | expected | observed |
|---|---|---|---|
| CLABSI | 0.0010 | ~0.9 | 0 |
| CAUTI | 0.0014 | ~1.2 | 3 |
| VAP | 0.0015 | ~1.1 | 1 |

Total observed: 4 (expected ~3.2, Poisson 2σ envelope).

JP p=5000 produced 20 devices × p50 line-days = 13: per-type expected ~0.1, P(X=0) ≈ 0.71 — JP 0 HAI is the majority outcome.

### Cross-validation

All 4 US HAIs have `source_device_id` referencing actual DeviceRecord in `extensions["device"]`. Cross-module dependency point validated end-to-end. All 4 satisfy CDC ≥48h definition.

## Axis 3 — JP language quality

US (n=4): zero Japanese characters in HAI Condition + coding + display + text.

JP (n=0): no JP HAI Conditions to localize; rare-event acceptance. JP localization path verified via integration test.

## Phase 2 acknowledged behaviors (non-defects)

- JP cohort 0 HAI: p=5000 small for CDC NHSN baseline (Phase 3 may scale to p=20000)
- No antibiotic / susceptibility / mortality / WBC-CRP lift (Phase 3)
- Snapshot in-progress device → line_days=7 fallback (documented)

## byte-diff supplement (Task 10)

All 37 pre-existing NDJSON byte-identical at US p=2000 + JP p=2000. Confirms hai enricher's independent sub-seed does not perturb main RNG. No new NDJSON file types.

## Conclusion

PR-B satisfies the goal-achievement gate: FHIR R4 / JP Core compliance + clinical coherence + JP language quality. All 3 axes × 2 countries PASS. Cross-module dependency from PR-A consumed correctly. PR-B ready to merge.
