# BMP Cl/Ca physiology PR — Data-quality review

**Date:** 2026-06-23
**Spec:** `docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md`
**Plan:** `docs/superpowers/plans/2026-06-23-bmp-cl-ca-physiology-plan.md`
**Branch:** `feat/bmp-cl-ca-physiology`
**Pool:** US p=10,000 (24,690 patients) + JP p=5,000 (2,455 patients), seed=42
**Methodology:** `scratchpad/dqr_pr75_review.py` (PR #76 reuse, column-fix for
post-PR #75 `ground_truth_diseases` rename + ICD prefix fallback)

## Verdict

**3 軸全 PASS**(構造完璧 / 臨床 7/8 PASS — known issue 1 件 / JP 言語 100%)

---

## 1. Structural hygiene

| metric | US | JP |
|---|---|---|
| Total resources | **5,126,042** | **582,369** |
| Duplicate ids | **0** ✓ | **0** ✓ |
| References checked | 9,024,695 | 1,059,378 |
| Unresolved references | **0** ✓ | **0** ✓ |
| Lab Observations (numeric) | 448,290 | 51,932 |
| referenceRange present | **100%** ✓ | **100%** ✓ |
| display == code anti-pattern | **0** ✓ | **0** ✓ |
| Empty `code.coding[].code` | **0** ✓ | **0** ✓ |

Per-resource breakdown (US): Patient 24,690 / Encounter 160,201 /
Condition 554,769 / Observation 3,410,505 / DiagnosticReport 47,358 /
MedicationAdministration 619,625 / Procedure 4,334 / Specimen 624 /
Coverage 0 (US has no Coverage extension) / Immunization 144,645 /
FamilyMemberHistory 69,005.

Per-resource breakdown (JP): Patient 2,455 / Encounter 16,104 /
Condition 35,729 / Observation 426,379 / DiagnosticReport 5,531 /
MedicationAdministration 69,934 / Procedure 205 / Specimen 78 /
Coverage 2,455 / Immunization 12,820 / FamilyMemberHistory 6,866.

## 2. Clinical fidelity

### US (p=10,000) — admit-day labs

| disease | analyte | n | p50 | p75 | p90 | target | verdict |
|---------|---------|---|-----|-----|-----|--------|---------|
| DKA | HCO3 | 580 | **15.40** | 16.90 | 17.80 | p50 ≤ 18 (ADA moderate) | **PASS** ✓ |
| DKA | Glucose | 580 | **437.00** | 487.00 | 540.00 | p50 ≥ 300 | **PASS** ✓ |
| ACS | Troponin_I | 365 | 74.36 | 95.31 | **112.47** | p90 ≥ 5 | **PASS** ✓ |
| Sepsis | Lactate | 48 | 4.60 | **5.80** | 8.10 | p75 ≥ 2.0 | **PASS** ✓ |
| AKI | Creatinine | 38 | **3.96** | 4.99 | 5.14 | p50 ≥ 2.5 (KDIGO 2-3) | **PASS** ✓ |
| CKD | Creatinine | 116 | 1.54 | **1.85** | 2.37 | p75 ≥ 1.5 | **PASS** ✓ |
| Pneumonia | WBC | 93 | **14,907** | 16,391 | 17,150 | p50 ≥ 10k | **PASS** ✓ |
| HF | BNP | 105 | **418.50** | 956.40 | 1,859.20 | p50 ≥ 500 | **known issue** ⚠ |

**HF BNP p50 = 418 (target ≥ 500) — not a defect introduced by this PR.**
This is the same admit-day-mixing artifact documented in PR #71
(`docs/reviews/2026-06-22-i50-bnp-cohort-decomposition.md`): when
`condition_event.ground_truth_diseases` + `encounter_type` are
decomposed, **inpatient + heart_failure_exacerbation event admit BNP
p50 = 603-1160 (ADHF band) and outpatient chronic-I50 follow-up
p50 = 68-74 (compensated HF, normal)**. The single mixed p50 is an
averaging artifact, the BNP formula itself is correct. PR #71 explicitly
called this out; this PR makes no BNP changes.

### JP (p=5,000)

All disease-specific cohorts SKIP (n=0) due to cohort size at this
population sample — JP DKA/sepsis/AKI/etc. counts are too small for
admit-day percentile checks. The same SKIP pattern appeared in the
PR #76 audit and is a pool-size limitation, not a JP fidelity defect.

### HbA1c ↔ Glucose correlation

| pool | n (patients with both) | Pearson r | expected | verdict |
|------|------------------------|-----------|----------|---------|
| US | 3,036 | **0.536** | 0.40 ≤ r ≤ 0.70 | **PASS** ✓ |
| JP | 205 | **0.537** | 0.40 ≤ r ≤ 0.70 | **PASS** ✓ |

## 3. JP localization

| metric | US | JP |
|--------|----|----|
| Japanese character occurrences in textual fields | **0** ✓ | n/a |
| Condition.code.text Japanese coverage | n/a | **35,729 / 35,729 = 100%** ✓ |
| DR.code display Japanese coverage | n/a | **5,531 / 5,531 = 100%** ✓ |
| Lab Observation.code.text Japanese coverage | n/a | **51,932 / 51,932 = 100%** ✓ |
| CM-granular ICD-10 leaks (5+ char with `.` or `X`) | n/a | **0** ✓ |

PR #76 had detected the JLAC10 5-code English-shortname-in-`ja` defect
(3B015 CK-MB / 3B035 AST / 3B045 ALT / 4A055 TSH / 5C070 CRP) and fixed
it to JCCLS-JSLM v137 official Japanese names; this PR introduces no
new JLAC10 codes, so that fix is preserved.

The 2 new BMP analytes (Cl LOINC 2075-0 / JLAC10 3H020; Ca LOINC
17861-6 / JLAC10 3H030) were already registered in
`clinosim/codes/data/{loinc,jlac10}.yaml` with English + Japanese fields
prior to this PR — Cl: "Chloride [Moles/volume] in Serum or Plasma" /
"塩化物" (JCCLS-aligned), Ca: "Calcium [Mass/volume] in Serum or Plasma" /
"カルシウム". No new code-system entries needed.

## Cohort drift (master vs branch)

Reported, not gated (the Pass 1 `individual_lab_seed` structural fix
intentionally shifts the master draw count — see audit doc §1):

| pool | Patient master | Patient branch | drift | Observation master | Observation branch | drift |
|------|----------------|----------------|-------|-----|-----|-----|
| US p=2,000 | 1,280 | 1,310 | +2.3% | 189,176 | 198,759 | +5.1% |
| JP p=2,000 | 979 | 970 | -0.9% | 168,250 | 163,337 | -2.9% |

Cl/Ca emission counts: US Cl 0→208, Ca 17→206; JP Cl 0→139, Ca 37→265.

## Required fixes from this review

**None.** All gates PASS or are pre-existing documented patterns (BNP
mixed-cohort artifact). PR is ready to push and merge.

## Documents updated

- `docs/superpowers/specs/2026-06-23-bmp-cl-ca-physiology-design.md`
  (encounter scope 3→2, §13.1 structural-defect-discovered narrative)
- `docs/reviews/2026-06-23-bmp-cl-ca-audit.md` (per-analyte distribution
  + isolation invariant)
- `docs/reviews/2026-06-23-bmp-cl-ca-data-quality-review.md` (this doc)

## Test totals

- Unit + integration + e2e: **667 passed in 603s** (full `pytest -x -q`)
- BMP panel audit: BMP 5th-percentile floor (with-panel-order) = 7 =
  chosen min_components ✓
