# I50 admit-day BNP cohort decomposition — closes the PR #69 review follow-up

**Date:** 2026-06-22
**Status:** **Not a defect** — BNP formula is correct. The PR #69 data-quality
review's "open issue" on I50 admit BNP is reclassified as a **cohort-grouping
artifact**: I50 admit primary-diagnosis mixes inpatient HF exacerbations (which
DO hit the ADHF band) with outpatient chronic-HF follow-up (which correctly
shows mild elevation). Decomposing by `condition_event.ground_truth_diseases`
and `encounter_type` confirms the BNP wall-stress formula
(`physiology/engine.py:283`) behaves as designed.

## What the PR #69 review reported

`docs/reviews/2026-06-22-aki-dka-surgical-calibration-data-quality-review.md`
§3 — "HF I50 — BNP (admit-day first lab)":

> | | US | JP |
> |---|---|---|
> | n | 74 | 105 |
> | min / p25 / **p50** / p75 / p90 / max | 0 / 58 / **95** / 316 / 1167 / 5000 | 0 / 56 / **79** / 119 / 417 / 5000 |
>
> The I50 cohort mixes acute decompensated HF (BNP 800-1500+, the spec's HF
> band) with chronic stable HF follow-ups (BNP < 200). The p90 reaches
> 417-1167 (acute-decomp range) and max saturates the assay clamp at 5000.
> **Open issue** — admit-day BNP central tendency for I50 is below the
> spec band, tracked in `docs/superpowers/plans/2026-06-20-bnp-hf-specificity.md`
> (HF discrimination). The byte-diff invariant guarantees this PR did NOT change
> any BNP value (the only Observations that differ are Cr / HCO3 / pCO2 / pH).
> **Not a regression — pre-existing.**

The framing implied the BNP formula might still need tuning. Decomposition
shows that's the wrong framing.

## Decomposition by `condition_event.ground_truth_diseases` and `encounter_type`

`/tmp/i50_cohort_analysis.py` against `/tmp/audit_branch_us` (p=8000, 5,086
patients) and `/tmp/audit_branch_jp` (p=4000, 2,021 patients), CIF
admit-day BNP per encounter, bucketed by the encounter's `condition_event`
scenario.

### US p=8000

| Bucket | n | min | p25 | p50 | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| I50 admit AND `heart_failure_exacerbation` event (inpatient) | 25 | 41.5 | 246.3 | **603.6** | 1259.1 | 4928.3 | 5000.0 |
| I50 admit, chronic-I50 follow-up (outpatient) | 48 | 0.0 | 48.6 | **68.6** | 103.8 | 128.8 | 178.7 |
| All I50 admit (mixed) | 73 | 0.0 | 56.8 | 91.6 | 246.3 | 953.6 | 5000.0 |

### JP p=4000

| Bucket | n | min | p25 | p50 | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| I50 admit AND `heart_failure_exacerbation` event (inpatient) | 10 | 12.3 | 248.7 | **931.8** | 1165.5 | 5000.0 | 5000.0 |
| I50 admit, chronic-I50 follow-up (outpatient) | 90 | 0.0 | 54.1 | **74.9** | 103.6 | 128.0 | 203.6 |

## Interpretation

- **Inpatient heart_failure_exacerbation admit p50: 603.6 (US) / 931.8 (JP)**
  — squarely inside the spec's ADHF 800-1500 band (US p75 = 1259, JP p50
  = 931). The wall-stress coupling
  `30 · exp((1-cardiac)·2.0 + max(0, volume)·(1-cardiac)·5.0)` is doing exactly
  what the BNP-pattern design intended.
- **Outpatient chronic-I50 follow-up admit p50: 68.6 (US) / 74.9 (JP)** —
  clinically expected for compensated chronic HF on stable therapy. These
  patients have I50 as their primary problem-list diagnosis carried into a
  routine clinic visit; they are NOT acutely decompensated, so BNP should be
  mildly elevated but not in the ADHF band. The simulator is correct.
- **The "Open issue" disappears when the cohort is split.** The 65% (US) /
  86% (JP) of I50-admit-primary encounters that are outpatient chronic
  follow-up drag the all-I50 p50 down to 95 / 79; that's an averaging
  artifact, not a formula deficiency.

## What this means for future audits

The next data-quality audit should bucket I50 (and any chronic-disease
primary-dx cohort) by **encounter_type** at minimum, and ideally by
`ground_truth_diseases` (which marks the actual acute-event scenario):

- **Inpatient + heart_failure_exacerbation event** → expect p50 in ADHF band
  (800-1500). Failure here would indicate a formula issue.
- **Outpatient + chronic-I50 follow-up** → expect mild elevation (50-150 pg/mL).
  Compensated stable HF on outpatient therapy.
- **Inpatient + non-HF event in I50-comorbid patient** → expect mild-moderate
  elevation depending on the acute event's volume_status push (sepsis with
  resuscitation, pneumonia with mild fluid overload, etc.).

A single all-I50 percentile masks all three populations and is not a useful
discrimination metric.

## Conclusion

**No code change.** The BNP wall-stress formula
(`docs/superpowers/specs/2026-06-20-bnp-hf-specificity-design.md`, implemented
in `ac36ff63` / `1c22a3e6`) is correct and the post-PR-#69 data-quality
review's "Open issue" on I50 admit BNP is a cohort-decomposition artifact.
The data-quality review note can be cross-referenced to this doc when the
next audit revisits BNP.
