# Phase 3a HAI WBC + CRP lift — 3-axis Data Quality Review

**Date:** 2026-06-25
**Branch:** feat/phase3a-hai-lab-lift
**Master baseline:** 42657293 (PR #89 merged)
**Cohort:** US p=10,000 + JP p=5,000, seed=42
**Tools:** scratchpad/phase3a_dqr.py + scratchpad/phase3a_byte_diff.py

## Summary

| Axis | Verdict |
|---|---|
| 1. Structural quality | **PASS** |
| 2. Clinical relative-delta | **PASS** (CAUTI cohort; CLABSI / VAP / JP — Poisson rare-event) |
| 3. JP language quality | **PASS** |
| byte-diff (p=2000) | **37/37 NDJSON IDENTICAL** |

All four checks pass. Phase 3a is ship-ready.

## Axis 1: Structural quality

### WBC + CRP refRange + interpretation 100%

| Country | Code system | Lab | n | with refRange + interpretation | Coverage |
|---|---|---|---|---|---|
| US | LOINC | WBC 6690-2 | 39,292 | 39,292 | **100%** |
| US | LOINC | CRP 1988-5 | 16,533 | 16,533 | **100%** |
| JP | JLAC10 | WBC 2A010 | 4,957 | 4,957 | **100%** |
| JP | JLAC10 | CRP 5C070 | 1,957 | 1,957 | **100%** |

(Note — earlier DQR draft used JLAC10 `2A020` for WBC which is incorrect;
the authoritative JLAC10 code is `2A010` per `locale/jp/code_mapping_lab.yaml`
and JSLM v137 master. Fixed in the script.)

### Code-system integrity

- LOINC 6690-2 (WBC) + 1988-5 (CRP): NLM Clinical Tables verified
- JLAC10 2A010 (WBC) + 5C070 (CRP): JSLM v137 official master verified
- No display = code violations
- No reference integrity errors

## Axis 2: Clinical relative-delta

Baseline = inpatient (`class=IMP`) encounters with NO HAI event.
HAI cohort = inpatient encounters with at least one matching HAI Condition.

### US p=10,000

| Cohort | n_WBC | WBC p50 | n_CRP | CRP p50 | WBC delta | CRP delta | Acceptance | Verdict |
|---|---|---|---|---|---|---|---|---|
| Baseline (non-HAI inpatient) | 13,363 | 12,029 | 11,899 | 23.6 mg/L | — | — | — | — |
| CAUTI | 11 | 14,164 | 9 | 74.0 | **+2,135** | **+50.4** | WBC ≥1,500 / CRP ≥25 | **PASS** |
| VAP | 3 | (rare) | 4 | (rare) | — | — | Poisson rare-event (n<5) | acceptable |
| CLABSI | 0 | — | 0 | — | — | — | Poisson rare-event (n=0) | acceptable |

The CAUTI cohort comfortably exceeds the calibration threshold for both
analytes — confirming the forward-delta lift mechanism is working
end-to-end (HAI event sample → `apply_hai_lab_lift` walks → `obs.value`
gets the formula-derived delta added). CLABSI + VAP are Poisson rare at
p=10,000 (CDC NHSN baseline 0.0010-0.0015 per device-day, only a small
fraction of inpatients get ICU devices, and only a fraction of those
contract HAI within the encounter window).

### JP p=5,000

| Cohort | n_WBC | n_CRP | Notes |
|---|---|---|---|
| Baseline (non-HAI inpatient) | 2,044 (p50 11,126) | 1,719 (p50 15.2 mg/L) | — |
| All HAI types | 0 | 0 | Poisson rare-event at p=5,000 |

JP cohort produced **zero HAI events** at p=5,000 — matching the PR #89
baseline expectation (`P(X=0) ≈ 0.71` for JP at this cohort size).
Acceptable rare-event outcome; the structural + JP language verification
is independent of HAI presence.

### Calibration reference

From spec §7.2 + §5 (baseline `state.inflammation_level = 0.4`,
typical inpatient):
- CLABSI/VAP lift 0.35 → effective_infl 0.75 → WBC +4,200 / CRP +143
- CAUTI lift 0.20 → effective_infl 0.60 → WBC +2,400 / CRP +61

Observed US CAUTI cohort (mid-ramp + multi-day median):
- WBC +2,135 (vs theoretical +2,400 full lift) — consistent with mix of
  day-1 (ramp 0.5) and day-2+ (full ramp) observations
- CRP +50.4 (vs theoretical +61 full lift) — same explanation

## Axis 3: JP language quality

| Country | Check | Result |
|---|---|---|
| US | non-ASCII display violations | **0** (PASS) |
| JP | WBC displays with non-ASCII (= Japanese) | **4,957 / 4,957** (PASS) |
| JP | CRP displays with non-ASCII (= Japanese) | **1,957 / 1,957** (PASS) |

JP WBC display: `白血球数` (JLAC10 2A010 official JSLM)
JP CRP display: `C反応性蛋白` (JLAC10 5C070 official JSLM)
US: zero locale leakage (no Japanese characters in US output)

## byte-diff (p=2000)

See `scratchpad/phase3a_byte_diff_results.md` for the full per-NDJSON
breakdown. Headline:

- **37/37 NDJSON byte-IDENTICAL** vs master 42657293
- US 18/18 + JP 19/19
- HAI is Poisson rare-event at p=2,000 → 0 events → `apply_hai_lab_lift`
  no-ops → Observation.ndjson identical to master
- Main RNG untouched (AD-16) + device + hai per-patient sub-seed
  determinism preserved (PR #88/#89 outputs unchanged)

## Architectural verification

- **POST_ENCOUNTER stage migration** preserved per-patient sub-seed
  determinism for device + hai (Device.ndjson + DeviceUseStatement.ndjson
  byte-identical at p=2,000).
- **Forward-delta lift** is exact (no reverse engineering of noise from
  observed values) and preserves original circadian / measurement noise
  on the lifted observations.
- **3-helper merge primitive** (`hai_flags_from_record`) kept as an
  unused but tested primitive for Phase 3b reuse (e.g. antibiotic decay,
  `antibiotic_flags_from_record` sibling).

## Conclusion

**Phase 3a is PR-ready.** All 3 DQR axes PASS; byte-diff confirms
zero regression on existing output. The forward-delta lift mechanism
fires correctly when HAI events are present (US CAUTI cohort
demonstrates the WBC + CRP delta meeting calibration). The CDC NHSN
rare-event distribution naturally limits HAI cohort size — even at
US p=10,000 the per-HAI-type cohort is single-digit to low-double
digit, but the forward formula is unit-tested separately (Tasks 1+2,
23 unit tests) to guarantee correctness independent of cohort size.

Phase 3b backlog (deferred):
- antibiotic empirical → narrow + susceptibility S/I/R
- WBC + CRP decay phase coupled with antibiotic-day count

Phase 3c backlog (deferred):
- HAI → outcome_benchmarks mortality coupling
- Lactate / Plt / Temperature / SBP sepsis cascade using same
  forward-delta pattern
