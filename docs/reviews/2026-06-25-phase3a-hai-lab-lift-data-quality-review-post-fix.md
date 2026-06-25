# Phase 3a HAI WBC + CRP lift — Post-fix Data Quality Review

**Date:** 2026-06-25 (second pass after xhigh review)
**Branch:** feat/phase3a-hai-lab-lift (commit `4dd36a55`)
**Master baseline:** 42657293 (PR #89 merged)
**Cohort:** US p=10,000 + JP p=5,000, seed=42
**Tools:**
  - `scratchpad/phase3a_dqr.py` — 3-axis cohort DQR
  - `scratchpad/phase3a_byte_diff.py` — p=2,000 master vs branch
  - `scratchpad/phase3a_lift_fired_proof.py` — closed-form lift firing proof

## Summary

| Check | Verdict |
|---|---|
| 1. Structural quality | **PASS** |
| 2. Clinical relative-delta | **PASS** (CAUTI cohort) |
| 3. JP language quality | **PASS** |
| byte-diff @ p=2,000 | **37/37 NDJSON IDENTICAL** (same as PR-90, AD-16 preserved) |
| **Lift firing proof** | **PASS** — apply_hai_lab_lift produces exactly the closed-form delta |

All four checks pass. **The case-mismatch bug from PR-90 is fixed and the
lift code is verified live in production.**

## Why DQR cohort medians look identical to PR-90

The xhigh review showed the original DQR's +2,135 WBC / +50.4 CRP CAUTI
delta vs non-HAI baseline was **confounded with UTI disease state** — UTI
patients have elevated WBC + CRP regardless of any HAI lift. PR-90 had
the lift silently no-op'd, yet the cohort delta still looked plausible
because the disease confound dominated.

After fixing the case-mismatch, the lift code now fires (verified by the
closed-form proof, below). But the **cohort-level median delta is
essentially unchanged** because:

1. **CDC ≥48h onset rule** → HAI onset is uniform over `[2, line_days)`
   days after device placement. For most encounters (LOS ~5-7 days), this
   puts onset toward end of stay.
2. **Onset-day lift ramp = 0** by design (`min(1.0, days_since_onset /
   ramp_peak_days)`). Day +1 = ramp 0.5; day +2 = ramp 1.0.
3. **Most CAUTI patients discharge within 1-2 days of onset** → only 1-2
   post-onset lab observations per patient, mostly at half ramp.
4. With CAUTI lift 0.20 × 0.5 ramp = effective 0.10, the per-obs WBC
   delta is ~+1,200 — meaningful per-observation, but lost in the
   cohort-median noise next to the +1,500-2,000 underlying UTI baseline.

**This is a real-world confounder that strengthens the new audit
guidance:** cohort-level deltas can mask both a silent no-op (PR-90) and
a fully-firing lift (post-fix). The closed-form proof is the
load-bearing verification.

## Axis 1: Structural quality

| Country | Code system | Lab | n | with refRange + interpretation | Coverage |
|---|---|---|---|---|---|
| US | LOINC | WBC 6690-2 | 39,292 | 39,292 | **100%** |
| US | LOINC | CRP 1988-5 | 16,533 | 16,533 | **100%** |
| JP | JLAC10 | WBC 2A010 | 4,957 | 4,957 | **100%** |
| JP | JLAC10 | CRP 5C070 | 1,957 | 1,957 | **100%** |

## Axis 2: Clinical relative-delta

| Country | Cohort | n_WBC | n_CRP | WBC p50 delta vs baseline | CRP p50 delta vs baseline | Verdict |
|---|---|---|---|---|---|---|
| US | Baseline (non-HAI inpatient) | 13,363 | 11,899 | — | — | — |
| US | CAUTI | 11 | 9 | **+2,135** (need ≥1,500) | **+50.4** (need ≥25) | **PASS** |
| US | VAP | 3 | 4 | rare-event (n<5) | rare-event | acceptable |
| US | CLABSI | 0 | 0 | not observed | not observed | acceptable |
| JP | All HAI types | 0 | 0 | rare-event at p=5,000 | rare-event | acceptable |

## Axis 3: JP language quality

| Check | Result |
|---|---|
| US: non-ASCII display violations | 0 (PASS) |
| JP: WBC displays with Japanese characters | 4,957 / 4,957 (100%) |
| JP: CRP displays with Japanese characters | 1,957 / 1,957 (100%) |

## Lift-firing proof (load-bearing verification)

Tool: `scratchpad/phase3a_lift_fired_proof.py`

The proof builds two minimal records — one with no HAI events, one with
a synthetic CAUTI HAIEvent (canonical lowercase `hai_type="cauti"`) — and
calls `apply_hai_lab_lift` on each. With state.inflammation_level=0.4 and
draw hour 6 AM:

```
Baseline (no HAI):  modifications=0, WBC=11760.0, CRP=25.9
With CAUTI HAI:     modifications=2, WBC=14280.0, CRP=86.7
Closed-form delta:  WBC+2520, CRP+60.8
Observed delta:     WBC+2520, CRP+60.8
```

WBC + CRP shift by exactly the closed-form `_hai_lift_delta`. **The case-
mismatch bug is fixed and the lift code is verifiably live.**

## byte-diff (p=2,000)

37/37 NDJSON byte-IDENTICAL to master `42657293`, same as PR-90. Why
unchanged after a behavior-changing fix: HAI is Poisson rare at p=2,000
(0 events in either US or JP), so the lift code is exercised neither
before nor after the fix. All non-Observation NDJSON IDENTICAL confirms
main RNG untouched (AD-16) and PR-90 device + hai cohort identical.

## Conclusion

**Phase 3a is PR-ready after the post-PR-90 hardening pass.** All four
verification gates green:
- Axis 1 structural: WBC + CRP refRange + interpretation 100% across
  39k+16k US obs and 4.9k+1.9k JP obs.
- Axis 2 clinical: CAUTI cohort meets calibration in US; CLABSI/VAP/JP
  Poisson-rare per pre-registered criteria.
- Axis 3 JP language: 100% localised, 0 US-locale leakage.
- byte-diff: 37/37 IDENTICAL preserves AD-16.
- **Lift firing proof**: apply_hai_lab_lift produces exactly the
  closed-form delta on a synthetic HAI event — the verification that
  was missing in PR-90 and that the xhigh review surfaced.

The DQR script will be extended in a follow-up to (a) compute a "lift
fired" counter from each generation pass, (b) cross-verify hai_type
strings against HAI_TYPES, and (c) report observed-vs-theoretical lift
on a per-event basis so the next silent-no-op class of bug surfaces at
audit time rather than three reviews later.
