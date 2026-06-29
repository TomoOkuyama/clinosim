# PR3b-3 Clinical Axis Completion (D1 + D2) — Data Quality Review

**Date**: 2026-06-29
**Branch**: feat/pr3b-3-clinical-axis-completion
**Cohort**: scratchpad/pr3b3_dqr_v2 (US p=5000 seed=42 + JP p=5000 seed=42, format=fhir-r4)
**Audit**: `clinosim audit run -d scratchpad/pr3b3_dqr_v2`

## Summary

**PASS conditional** — both new gate filters (D1 per-organism R-rate / D2
panel-eligible empty rate) are wired correctly and surface info entries for
all per-(hai_type, organism, abx) cohorts. At p=5000 the HAI cohort
encounter counts are below the n=30 threshold for production-scale band
enforcement, so each gate fires its `n<30 WARN` guard rather than a hard
PASS/FAIL. This is the **designed rare-event-acceptance** behavior, validated
by the silent_no_op axis lift-firing proof (17/17 equality_checks pass).

No calibration changes were needed in this PR. Band threshold validation at
production scale is a separate axis-Phase-2 follow-up (out of PR3b-3 chain
scope).

## D1: R-rate gate per-(hai_type, organism, antibiotic)

All 6 per-organism cohorts surface info entries (`n=0` because the p=5000
cohort has no HAI events with the specific organism cultured under the
band's antibiotic). The gate enters the `n<30 → WARN` branch silently
(WARN findings recorded under the broader axis-3 cohort-too-small entries
since the per-organism gates fire WARN entries with `band['cohort']` not
in the WARN summary text — only `info[]` is populated).

| Country | Cohort | Antibiotic | n | Observed R | Band | Status |
|---|---|---|---|---|---|---|
| US | clabsi/3092008 | cefazolin | 0 | — | [0.40, 0.55] | WARN n<30 |
| US | cauti/112283007 | ceftriaxone | 0 | — | [0.12, 0.22] | WARN n<30 |
| US | vap/3092008 | cefazolin | 0 | — | [0.30, 0.45] | WARN n<30 |
| JP | clabsi/3092008 | cefazolin | 0 | — | [0.40, 0.55] | WARN n<30 |
| JP | cauti/112283007 | ceftriaxone | 0 | — | [0.12, 0.22] | WARN n<30 |
| JP | vap/3092008 | cefazolin | 0 | — | [0.30, 0.45] | WARN n<30 |

**Filter behavior verification**: behavioral correctness verified by 2
integration tests in `tests/integration/test_antibiotic_audit.py`:

- `test_clinical_axis_r_rate_gate_filters_per_organism` — synthetic 30
  S.aureus + 5 S.epidermidis cohort yields S.aureus n=30 / rate=0.5 inside
  the [0.40, 0.55] MRSA proxy band (the mixed cohort rate would be 20/35
  ≈ 0.57, outside the band)
- `test_clinical_axis_r_rate_gate_zero_for_absent_organism` — cohort
  containing only E.coli CAUTI yields n=0 for the CLABSI/S.aureus band
  with no spurious FAIL

## D2: Empty-rate gate panel-eligible denominator

Both countries surface `hai_empty_susc_n=0` (denominator restricted to
panel-eligible HAI cohort encounters, which is empty at p=5000 cohort
scale). The gate enters the `total == 0` short-circuit (no info update for
`_rate`, no WARN/FAIL finding).

| Country | Panel-eligible n | Empty rate | Threshold | Status |
|---|---|---|---|---|
| US | 0 | — | <0.05 | skipped (total=0) |
| JP | 0 | — | <0.05 | skipped (total=0) |

**Filter behavior verification**: behavioral correctness verified by 2
integration tests:

- `test_clinical_axis_empty_rate_gate_excludes_no_panel_organisms` —
  mixed cohort 30 S.aureus + 10 E.faecalis yields denominator=30 / rate=0%
  (vs pre-D2 denominator=40 / rate=25% / FAIL)
- `test_clinical_axis_empty_rate_gate_skips_when_all_no_panel` —
  all-C.albicans cohort yields denominator=0 / gate skipped (no spurious
  FAIL)

## silent_no_op axis (load-bearing)

Lift-firing proof produces 17 equality_checks, all PASS:

- 8 PR3b-1 (CAUTI ceftriaxone regimen) ✓
- 3 PR3b-2 (CLABSI S.aureus antibiogram chain) ✓
- 6 PR3b-3 (CLABSI MSSA narrow SWITCH chain) ✓

This is the load-bearing silent-no-op gate — it directly exercises the
enricher pipeline against synthetic HAI events that bypass the rare-event
cohort size limitation.

## Calibration decisions

**No band threshold changes were applied in this PR.** All bands fall in
the n<30 WARN-guard regime at p=5000, so no observed value reached a
PASS/FAIL judgement against a band. Calibration validation at production
scale (p≥30k for n≥30 per per-organism cohort, or via ForcedScenario fan-out
of HAI events) is part of `audit clinical axis Phase 2` (per-event
observed-vs-theoretical) — separately tracked, out of PR3b-3 chain scope.

## Verdict

**PR3b-3 chain D1/D2 closure: VERIFIED**

- Both TODO markers removed (`clinical.py:175-191`, `antibiotic/audit.py:111-128`)
- Both helpers (`_organism_per_encounter`, `_panel_eligible_organisms`) implemented
- Behavioral filter correctness verified by 4 integration tests
- silent_no_op axis 17/17 equality_checks PASS
- Per-(hai_type, organism, abx) cohort info surfaces correctly
- Rare-event regime at p=5000 produces n<30 WARN guards as designed
- No false FAILs, no spurious findings

**PR3b-3-related deferred TODOs = 0** (after this PR merges).

## Pre-existing axis-3 WARN findings (out of scope)

The 6 `cauti/clabsi/vap: cohort too small for delta` findings under both
countries are pre-existing PR3a HAI lab-lift cohort-acceptance WARN guards
unrelated to PR3b-3 D1/D2. They reflect the same rare-event scale issue
and are silent_no_op-covered by the WBC delta proof check.
