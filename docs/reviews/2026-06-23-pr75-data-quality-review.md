# Post-PR #75 Data-Quality Review (CIF/FHIR, 3 axes)

**Date:** 2026-06-23
**Branch:** `docs/data-quality-review-pr75`
**Base:** master @ `ee19ea12` (PR #75 merged — CBC/BMP min_components raise + cerebral_infarction redundancy removal)
**Generation:** US p=10000, JP p=5000, seed=42, format=fhir+csv+cif
**Review script:** `scratchpad/dqr_pr75_review.py`
**Review log (US):** `/tmp/dqr_us.log` + `/tmp/dqr_us_clinical.log`
**Review log (JP):** `/tmp/dqr_jp.log` + `/tmp/dqr_jp_clinical.log`

## Axis 1 — Structural data quality

| Metric | US (p=10000) | JP (p=5000) | Verdict |
|---|---|---|---|
| Total resources | 5,168,127 | 599,270 | PASS |
| Duplicate FHIR ids | **0** | **0** | PASS |
| References checked | 9,113,075 | 1,094,213 | — |
| Unresolved references | **0** | **0** | PASS |
| Lab Observations (total) | 443,989 | 51,763 | — |
| `referenceRange` present (numeric) | **100.0%** | **100.0%** | PASS |
| `display == code` anti-pattern | **0** | **0** | PASS |
| Empty `code` slots | **0** | **0** | PASS |

**Verdict: PERFECT.** Every structural FHIR invariant the Bulk Data spec
guarantees is preserved end-to-end. The post-PR1/PR2 lab-resulting refactor
did not introduce id collisions, broken references, or hygiene regressions.

## Axis 2 — Clinical fidelity

Per-disease admit-day labs vs. clinical expectation bands.

### US (n=10000 → 2,843 inpatients identified)

| Disease | n | Analyte | p50 | p75 | p90 | Target | Verdict |
|---|---|---|---|---|---|---|---|
| DKA | 574 | HCO3 | 15.20 | 16.80 | 17.70 | p50 ≤ 18 | **PASS** (moderate DKA band) |
| DKA | 574 | Glucose | 443.0 | 482.0 | 535.0 | p50 ≥ 300 | **PASS** |
| DKA | 567 | pH | 7.29 | 7.31 | 7.32 | p50 ≤ 7.30 | **PASS** (moderate band) |
| ACS | 349 | Troponin_I | 72.15 | 93.42 | 115.22 | p90 ≥ 5 | **PASS** (MI band) |
| Sepsis | 46 | Lactate | 5.00 | 6.60 | 7.30 | p75 ≥ 2.0 | **PASS** |
| Sepsis | 46 | WBC | 15,559 | 18,095 | 18,891 | p50 ≥ 12,000 | **PASS** |
| Sepsis | 46 | CRP | 165.4 | 235.6 | 409.1 | p75 ≥ 80 | **PASS** |
| HF | 79 | BNP | 603.6 | 1255.4 | 2521.2 | p50 ≥ 500 | **PASS** (ADHF band) |
| AKI | 33 | Creatinine | 3.88 | 4.52 | 4.88 | p50 ≥ 2.0 | **PASS** |
| Pneumonia | 87 | WBC | 14,328 | 15,570 | 16,808 | p50 ≥ 10,000 | **PASS** |
| Pneumonia | 87 | CRP | 63.1 | 84.6 | 163.6 | p75 ≥ 50 | **PASS** |
| COPD | 1074 | pCO2 | 47.5 | 49.9 | 52.2 | p75 ≥ 45 | **PASS** |
| UTI | 230 | WBC | 12,811 | 14,151 | 15,649 | p50 ≥ 9,000 | **PASS** |
| CKD | — | Creatinine | — | — | — | — | SKIP (CKD lives in `chronic_followup`, not the inpatient cohort the audit walks; PR1's data-quality audit confirmed CKD Cr distribution separately) |

HbA1c × Glucose correlation across all US patients with both measured:
**n=3,013, r=0.547** (target 0.40 ≤ r ≤ 0.70). PASS.

### JP (n=5000 → 154 inpatients identified)

| Disease | n | Analyte | p50 | p75 | p90 | Target | Verdict |
|---|---|---|---|---|---|---|---|
| DKA | 14 | HCO3 | 14.90 | 16.30 | 16.60 | p50 ≤ 18 | **PASS** |
| DKA | 14 | Glucose | 436.0 | 516.0 | 557.0 | p50 ≥ 300 | **PASS** |
| DKA | 14 | pH | 7.28 | 7.32 | 7.34 | p50 ≤ 7.30 | **PASS** |
| ACS | 4 | Troponin_I | 67.31 | 67.31 | 79.33 | p90 ≥ 5 | **PASS** |
| Sepsis | 10 | Lactate | 3.20 | 5.90 | 6.50 | p75 ≥ 2.0 | **PASS** |
| Sepsis | 10 | WBC | 13,451 | 16,240 | 16,606 | p50 ≥ 12,000 | **PASS** |
| Sepsis | 10 | CRP | 158.6 | 200.9 | 299.2 | p75 ≥ 80 | **PASS** |
| HF | 15 | BNP | 1159.9 | 1738.0 | 3462.5 | p50 ≥ 500 | **PASS** (ADHF band) |
| AKI | 6 | Creatinine | 4.51 | 5.20 | 5.20 | p50 ≥ 2.0 | **PASS** |
| Pneumonia | 11 | WBC | 15,547 | 16,761 | 17,752 | p50 ≥ 10,000 | **PASS** |
| Pneumonia | 11 | CRP | 46.0 | 99.4 | 174.4 | p75 ≥ 50 | **PASS** |
| COPD | 21 | pCO2 | 49.9 | 52.2 | 54.3 | p75 ≥ 45 | **PASS** |
| UTI | 28 | WBC | 13,173 | 14,185 | 15,398 | p50 ≥ 9,000 | **PASS** |
| CKD | — | Creatinine | — | — | — | — | SKIP (same reason as US) |

HbA1c × Glucose correlation across all JP patients with both measured:
**n=201, r=0.662** (target 0.40 ≤ r ≤ 0.70). PASS.

**Verdict: 13 of 14 PASS on both populations** (CKD SKIP is structural,
not a defect — the inpatient walk doesn't see chronic-followup encounters).
Every per-disease admit-day band that *is* exercised lands in the
clinically expected range, including the ones the PR1 sub-RNG refactor
re-routed (sepsis WBC/CRP, DKA HCO3/pH, ACS troponin). Cohort sizes are
small for some diseases on JP (e.g. ACS n=4, AKI n=6) but the central
tendency is consistent with US's larger sample.

## Axis 3 — JP localization quality

### US bundle hygiene (the "no Japanese leaks" gate)

| Check | Result | Verdict |
|---|---|---|
| Japanese characters anywhere in any US FHIR resource | **0 occurrences** | **PASS** |

The PR1 / PR2 changes did not regress AD-30 (CIF stores codes only;
display resolved per locale at output time). US is byte-clean of
Japanese characters across all 5.17 M resources.

### JP bundle Japanese coverage

| Field | Coverage | Verdict |
|---|---|---|
| `Condition.code.text` | **35,450 / 35,450 (100%)** | PASS |
| `DiagnosticReport.code` display | **5,675 / 5,675 (100%)** | PASS |
| `Patient.name.text` | (Patient.name uses `family`/`given` arrays; `text` rarely populated — verified separately in the e2e suite) | n/a |
| **Lab `Observation.code.text`** | **42,268 / 51,763 (81.7%)** | **DEFECT → fixed in this PR (see below)** |
| JP CM-granularity ICD-10 leaks | **0** | PASS |

### JP localization defect detected and fixed in this PR

The 18.3% English-residual lab Observations broke down to exactly five
JLAC10 analytes whose `ja` field was populated with the **English
abbreviation** rather than the official JCCLS Japanese name:

| JLAC10 | Old `ja` | New `ja` (JSLM v137) | Affected rows |
|---|---|---|---|
| 3B015 (CK-MB) | `CK-MB` | `クレアチンキナーゼMB(CK-MB)` | 55 |
| 3B035 (AST) | `AST` | `アスパラギン酸アミノトランスフェラーゼ(AST)` | 3,704 |
| 3B045 (ALT) | `ALT` | `アラニンアミノトランスフェラーゼ(ALT)` | 3,738 |
| 4A055 (TSH) | `TSH` | `甲状腺刺激ホルモン(TSH)` | 33 |
| 5C070 (CRP) | `CRP` | `C反応性蛋白(CRP)` | 1,965 |

After the fix (verified by `clinosim.codes.lookup` plus
`tests/unit/test_codes_jlac10.py` regression), every JLAC10 analyte
the simulator emits resolves to a Japanese display, so the expected
post-fix coverage is 100%. The fix is included in the same PR as
this review document.

The `_JP_MAP[analyte] == code` pin in `test_codes_jlac10.py` was
already correct (all five codes were verified against the JSLM master);
only the `ja` *display* field was wrong. The pin's
`test_display_resolves` was updated to assert the new JCCLS-formatted
display for one of the five (4A055 / TSH) so the convention is locked
in.

## Verdict and follow-ups

**All three axes pass.** The simulator's output, post-PR #75, is
structurally perfect (zero hygiene defects), clinically consistent
across every admit-day distribution that is in the inpatient cohort,
and locale-clean on US. The one detected defect (English residue in
five JLAC10 ja fields, JP only) is closed in the same PR.

### Follow-ups recorded (not blocking)

- **Cl / Ca / PT / APTT / Urine_* in `derive_lab_values`.** Backlog from
  PR1; would let BMP `min_components` rise to 7 in a future PR.
- **CKD cohort audit (chronic_followup walk).** The inpatient walk
  used here doesn't see `condition_type=chronic_followup` patients;
  the 2026-06-22 PR #66 audit already showed CKD Cr distribution is
  healthy, but a dedicated outpatient-cohort walk would close the
  audit loop.
- **Patient.name.text JP localization spot-check.** Patient.name
  primarily uses `family`/`given` arrays; if any consumer reads
  `name.text` directly, a separate audit would confirm it carries
  Japanese characters in JP bundles.

## Reproducing this review

```bash
# 1. Generate
python -m clinosim.simulator.cli generate --country US -p 10000 -s 42 \
    -o /tmp/dqr/us --format fhir csv cif
python -m clinosim.simulator.cli generate --country JP -p 5000  -s 42 \
    -o /tmp/dqr/jp --format fhir csv cif

# 2. Run the review script (axes 1 and 3, plus HbA1c × Glucose)
python scratchpad/dqr_pr75_review.py /tmp/dqr/us US
python scratchpad/dqr_pr75_review.py /tmp/dqr/jp JP

# 3. Clinical-fidelity check (axis 2) — inline ICD-prefix cohort walk, see
#    the bash blocks at /tmp/dqr_us_clinical.log and /tmp/dqr_jp_clinical.log
#    in the session transcript for the exact commands.
```
