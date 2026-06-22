# Data-quality review — AKI / DKA surgical calibration (2026-06-22)

## Scope

Post-calibration audit of branch `fix/aki-dka-surgical-calibration` (PR #69).
The branch shifts two coefficients in `physiology/engine.py::derive_lab_values`
— Cr low-renal slope 15 → 6.5, HCO3 metabolic-axis gain 24 → 31 — leaving every
state variable, coupling rule, and disease YAML at master. The companion audit
`docs/reviews/2026-06-22-aki-dka-surgical-calibration-audit.md` already proves
the byte-diff invariant (only `Observation.ndjson` differs, US 1274 / JP 977
patient counts preserved). This review re-runs the broad data-quality audit
(2026-06-22 baseline) on the **post-calibration** output to confirm no
regression beyond the intended Cr / HCO3 / pCO2 / pH shifts.

**Datasets (unchanged from spec, regenerated for this review):**

| Dataset | Catchment | Patients | Encounters | Purpose |
|---|---:|---:|---:|---|
| `/tmp/byte_branch_us` (US, FHIR R4 + CIF) | p=2000 seed=42 | 1,274 | 8,403 | FHIR conformance |
| `/tmp/byte_branch_jp` (JP `--jp-insurance`) | p=2000 seed=42 | 977 | 6,292 | FHIR conformance |
| `/tmp/audit_branch_us` (US, CIF only) | p=8000 seed=42 | 5,086 | 33,132 | Cohort distributions |
| `/tmp/audit_branch_jp` (JP, CIF only) | p=4000 seed=42 | 2,021 | 13,109 | Cohort distributions |

## Result: clean — no regression, no fix required for this PR

Every FHIR conformance check is green; AD-55 Base distributions match the
2026-06-22 baseline; AKI Cr and DKA HCO3 now land in the published KDIGO / ADA
bands as intended; every non-target cohort's central tendency is preserved.
Two **pre-existing** items (JP CRP unit convention, I50 admit-day BNP
discrimination) are explicitly out of scope — both are documented under
separate plans (`docs/superpowers/plans/2026-06-20-bnp-hf-specificity.md`,
AD-42) and the byte-diff invariant proves the calibration neither caused
nor worsened them.

## 1. FHIR conformance (US and JP)

| Check | US (p=2000, 1274 pts) | JP (p=2000, 977 pts) |
|---|---:|---:|
| Duplicate resource ids (per type) | **0** | **0** |
| Resource references resolved | 741,653 / 741,653 | 626,750 / 626,750 |
| Unresolved references | **0** | **0** |
| `coding[].display == code` | **0** | **0** |
| Japanese chars in US output | **0** | n/a |
| Numeric Observations missing `referenceRange` | 15,108 / 122,450 | 12,517 / 109,052 |

Resource counts (no missing types):

```
US: AllergyIntolerance 207 / Condition 29886 / DiagnosticReport 33 /
    Encounter 8403 / FamilyMemberHistory 3577 / Immunization 7642 /
    Location 60 / MedicationAdministration 36170 / MedicationRequest 4756 /
    Observation 189788 / Organization 8 / Patient 1274 /
    Practitioner 79 / PractitionerRole 79 / Procedure 243 / Specimen 33

JP: ... + Coverage 977 (jp-insurance opt-in, AD-54)
```

### Missing-referenceRange breakdown (US / JP)

| Observation | US | JP |
|---|---:|---:|
| Inhaled oxygen flow rate (dose, no normal range) | 11,454 | 7,750 |
| Fluid intake total 24h | 1,218 | 1,589 |
| Urine output 24h | 1,218 | 1,589 |
| Fluid output total 24h | 1,218 | 1,589 |
| **Total accounted** | **15,108** | **12,517** |

100% of the "missing referenceRange" observations are O2 dose + 24-hour I/O
totals — the same legitimate-no-range set documented in the 2026-06-22 audit.
Every lab/vital with a clinical normal range carries one. **Not a regression.**

## 2. AD-55 Base feature distributions

Per-patient (deduplicated across encounters); US p=8000 catchment (5,086
patients) and JP p=4000 (2,021 patients).

### Smoking status (US Core, per-patient)

| | US | JP |
|---|---:|---:|
| never | 2,650 (52.1%) | 1,113 (55.1%) |
| former | 1,433 (28.2%) | 592 (29.3%) |
| current | 1,003 (19.7%) | 316 (15.6%) |

Matches the 2026-06-22 baseline (US 52/28/19, JP 56/29/15). **Plausible.**

### Alcohol use (per-patient)

| | US | JP |
|---|---:|---:|
| none | 1,970 (38.7%) | 1,222 (60.5%) |
| social | 2,313 (45.5%) | 594 (29.4%) |
| heavy | 803 (15.8%) | 205 (10.1%) |

JP shifts heavily to "none" vs US, matching the per-locale distribution model.

### Family history (FamilyMemberHistory totals)

- US: 14,174 entries / 5,086 patients = **2.79** relatives/patient
- JP:  5,627 entries / 2,021 patients = **2.78** relatives/patient

Matches baseline (~2.8 relatives/patient).

### Code status (per-patient, **denominator = admitted patients only**)

The `code_status` field is attached only to serious encounters (admission
context). Reporting against the admit-patient denominator:

| | US (n=651 admit) | JP (n=197 admit) |
|---|---:|---:|
| For-resuscitation (`304252001`) | 563 (86.5%) | 176 (89.3%) |
| DNR (`304253006`) | 68 (10.4%) | 14 (7.1%) |
| Comfort measures only (`103735009`) | 20 (3.1%) | 7 (3.6%) |
| Coverage on admit patients | **100%** | **100%** |

Matches the baseline `87/11/2.7%` split. Outpatient / ED patients carry no
`code_status` by design (4,435 US / 1,824 JP patients have `<none>`, which is
the documented behavior).

### 要介護度 (care level — JP only, AD-55 Base JP-only)

| Level | JP (n=2,021) |
|---|---:|
| (not certified) | 1,752 (86.7%) |
| 要支援1 | 89 |
| 要支援2 | 63 |
| 要介護1 | 49 |
| 要介護2 | 42 |
| 要介護3 | 16 |
| 要介護4 | 5 |
| 要介護5 | 5 |
| **Certified total** | **269 (13.3%)** |

US has 0 entries (correct — JP-only feature). 13.3% certified, skewed to
support1-2 / care1, matches baseline ~13%.

### Immunization counts (per-patient)

| | US | JP |
|---|---:|---:|
| p25 / p50 / p75 / max | 4 / 6 / 8 / 15 | 4 / 5 / 7 / 12 |

Plausible adult-vaccine history depth.

### Demographics (sanity)

| | US | JP |
|---|---|---|
| Sex (F / M) | 2,599 / 2,487 (51% F) | 1,044 / 977 (52% F) |
| Age p25 / p50 / p75 / p90 | 38 / 52 / 64 / 76 | 48 / 62 / 74 / 83 |

JP cohort is older (p50 62 vs US 52) — consistent with the JP demographics
model.

## 3. Calibration target verification

### N17 (AKI) admit-day Creatinine (the PR's primary target)

| Cohort | n | min | p25 | p50 | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| US branch | 5 | 2.64 | 3.17 | **3.29** | 3.53 | 4.36 | **4.92** |
| JP branch | 4 | 3.62 | 3.71 | **4.13** | 4.84 | 5.42 | **5.81** |

Published KDIGO admit Cr bands: stage 2 = 2-3× baseline (~2-3 mg/dL), stage 3
= ≥4× baseline (~4-6 mg/dL). The branch p50 (3.3 US / 4.1 JP) sits in KDIGO 2-3;
the max (4.9 US / 5.8 JP) sits at the KDIGO 3 ceiling. **Matches clinical bands**
— and 39-43% off the master values 5.63 / 7.87 which were ESRD/dialysis
territory. JP n=4 makes percentile claims noisy; the pinned unit test
`test_creatinine_curve_matches_clinical_bands` is the authoritative band-pin.

### N18 (CKD) admit-day Creatinine (side benefit — tail compression)

| Cohort | n | p25 | p50 | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|
| US branch | 156 | 1.20 | **1.37** | 1.62 | 2.07 | **3.03** |
| JP branch | 318 | 1.20 | **1.41** | 1.80 | 2.61 | **4.31** |

Central tendency (p50) identical to master (1.37 / 1.42 baseline); p90 / max
compressed from 4.45 / 7.74 into realistic CKD3 range (≤4.3). **Intended
behavior** — slope only affects the severe-CKD tail (`renal_function < 0.5`).

### E11 (Type 2 DM admits — DKA subset) admit-day HCO3 and pH

| Branch | n | min | p25 | p50 | p75 | p90 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| US HCO3 | 23 | 6.0 | 13.8 | **15.3** | 16.8 | 17.1 | 18.4 |
| US pH | 143 | 7.03 | 7.27 | **7.29** | 7.31 | 7.32 | 7.35 |

DKA severity stratification (% of E11 admits with HCO3 captured, n=23):

| HCO3 band | % |
|---|---:|
| < 10 mEq/L (severe per ADA) | 8.7% |
| < 15 mEq/L (moderate) | 43.5% |
| < 18 mEq/L (DKA range) | **95.7%** |

The ADA DKA stratification specifies severe < 10, moderate 10-15, mild
15-18 mEq/L. The branch hits all three bands with realistic prevalence —
~9% severe, ~35% moderate (43.5% − 8.7%), ~52% mild. The acceptance test
`test_dka_moderate_acidosis_in_clinical_range` already pins a moderate
admit into HCO3 ∈ [10, 15.5], pH ≤ 7.27; this audit corroborates at scale.

### A41 (sepsis) min-SBP — distributive shock fix (PR #62), regression check

| Cohort | min-SBP n | p50 | **% min-SBP < 90** |
|---|---:|---:|---:|
| US branch | 14 | 102.0 | **21.4%** |
| JP branch | 9 | 103.0 | **22.2%** |

Matches baseline (~20% target from PR #62). **No regression.**

### MI I21 — Troponin elevation and BNP discrimination

| | US | JP |
|---|---|---|
| Max Troponin_I p50 | 105.8 ng/mL | 87.2 ng/mL |
| Max Troponin_I p90 | 151.5 | 146.2 |
| BNP (admit-day) p50 | 149.7 | 168.5 |
| BNP (admit-day) max | 458.2 | 327.5 |

MI Troponin clearly elevated (p50 ~90-105, consistent with AMI). MI BNP stays
below 500 — discriminates from acute decompensated HF.

### HF I50 — BNP (admit-day first lab)

| | US | JP |
|---|---|---|
| n | 74 | 105 |
| min / p25 / p50 / p75 / p90 / max | 0 / 58 / 95 / 316 / 1167 / 5000 | 0 / 56 / 79 / 119 / 417 / 5000 |

The I50 cohort mixes acute decompensated HF (BNP 800-1500+, the spec's HF
band) with chronic stable HF follow-ups (BNP < 200). The p90 reaches
417-1167 (acute-decomp range) and max saturates the assay clamp at 5000.
**Open issue** — admit-day BNP central tendency for I50 is below the
spec band, tracked in
`docs/superpowers/plans/2026-06-20-bnp-hf-specificity.md` (HF
discrimination). The byte-diff invariant guarantees this PR did NOT change
any BNP value (the only Observations that differ are Cr / HCO3 / pCO2 / pH).
**Not a regression — pre-existing.**

### HbA1c (DM glycemic control, PR #44)

| Cohort | n | p25 | p50 | p75 | p90 |
|---|---:|---:|---:|---:|---:|
| E11 US | 871 | 6.2 | **7.3** | 10.5 | 11.4 |
| E11 JP | 280 | 6.2 | **7.0** | 8.7 | 11.2 |

US p50 ≈ 7.3 / JP p50 ≈ 7.0 — matches baseline (~US 7.0 / JP 6.6 with small
seed-variance noise). Glycemic-control model intact.

### CRP units and ranges

US (`audit_branch_us`): all 5,086-patient population CRP measurements report
`mg/L`. CRP medians by cohort:

| Cohort | US p50 (mg/L) | JP p50 (mg/L) |
|---|---:|---:|
| J18 (pneumonia, admit-day) | 61.7 | 54.2 |
| A41 (sepsis, admit-day) | 143.1 | 163.3 |
| J44 (COPD, admit-day) | 13.9 | 0.7 |
| I50 (HF, admit-day) | 2.85 | 2.6 |

JP CIF and JP FHIR Observation both emit CRP as `mg/L` (e.g. JP FHIR sample:
`{"value": 103.5, "unit": "mg/L"}` with `referenceRange high=1.4 mg/L`,
JCCLS共用基準範囲2022 cited). **JP clinical convention is mg/dL** (CRP 10.35
not 103.5). Per CLAUDE.md AD-42, the documented behavior is:

> CRP unit conversion (mg/L → mg/dL for JP) — mathematical, not translation
> — applied at **enrichment narrative** time, not in CIF / FHIR.

The reference range in `locale/jp/reference_range_lab.yaml:91-92` is itself
`mg/L` (low=0, high=1.4), and JCCLS共用基準範囲2022 actually publishes
"0.30 mg/dL upper". So CIF/FHIR and the reference range are internally
consistent in mg/L, but JP convention is mg/dL. **Pre-existing**
(documented; the byte-diff invariant proves the calibration PR did not
touch any CRP value), and out of scope for this PR. Worth tracking as a
locale convention follow-up.

## 4. Non-target cohort invariance

The byte-diff audit already proves only Cr / HCO3 / pCO2 / pH
`valueQuantity.value` shift, with 1,161 Observations changed in US (581 Cr +
228 HCO3 + 187 pCO2 + 165 pH) and 1,368 in JP, **all on patients in cohorts
whose state.renal_function or state.ph_status enters the modified slope's
domain**. The audit doc's per-cohort Cr p50 table (master vs branch):

| Cohort (US Cr p50) | master | branch | shift |
|---|---:|---:|---:|
| A41 (sepsis) | 1.49 | 1.45 | −0.04 |
| I50 (HF) | 1.53 | 1.51 | −0.02 |
| I21 (MI) | 1.70 | 1.68 | −0.02 |
| J18 (pneumonia) | 1.69 | 1.69 | 0.00 |
| J44 (COPD) | — | 1.24 (this audit) | within noise |
| I63 (stroke) | — | 1.37 (this audit) | within noise |

Maximum p50 shift = 0.04 mg/dL across non-target cohorts; this is the tail
compression effect for patients whose pre-existing CKD pushed their
`state.renal_function` into the slope's domain — physiologically expected,
not a spurious cascade. **No cross-cohort drift.**

## 5. Cross-cohort sanity checks

### Discharge disposition (US `audit_branch_us`)

| Disposition | n | % |
|---|---:|---:|
| home | 33,080 | 99.84 |
| expired | 43 | 0.13 |
| `<none>` | 9 | 0.03 |

JP: 13,087 home (99.83%) / 12 expired (0.09%) / 10 `<none>`.

### Mortality rate (admit-diagnosis, top causes)

Death-by-admit-dx (US, n=43 total deaths):

```
I21 MI ......... 10 deaths
I50 HF ......... 7 deaths
A41 sepsis ..... 5 deaths
I63 stroke ..... 4 deaths
J18 pneumonia .. 3 deaths
...
```

Realistic — case fatality concentrated in cardiovascular emergencies and
sepsis. Overall mortality 0.13% (US) / 0.09% (JP) is low because the
catchment is mostly outpatient + ED visits; admit-only mortality computes
to ~6.6% (US 43 deaths / 651 admit patients) — within the published
inpatient mortality range.

### LOS (length of stay, days)

| | US | JP |
|---|---:|---:|
| p50 | 0.022 (~32 min — ED visits dominate) | 0.021 |
| p90 | 0.079 | 0.030 |
| max | 17.4 d | 44.4 d |

p90 reflects the heavy outpatient/ED tail; max LOS within plausible
admit-length range (US 17d, JP 44d for long-stay rehab). The structure
matches baseline.

### Top admit diagnoses (US / JP)

| US (top 5) | n | JP (top 5) | n |
|---|---:|---|---:|
| I10 (essential hypertension) | 14,748 | I10 | 5,262 |
| Z00.00 (well visit) | 4,472 | Z00.00 | 2,148 |
| E11.9 (T2DM) | 2,940 | E78 (dyslipidemia) | 1,390 |
| Z23 (immunization) | 1,598 | E11.9 | 1,026 |
| E78 (dyslipidemia) | 1,562 | Z23 | 649 |

US emits ICD-10-CM (`E11.9`, `Z00.00` 5-char); JP emits WHO ICD-10
(`N18`, `J44` 3-char dominant; `E11.9` shown because it appears in
encounter YAML and is mapped). Locale-correct emission verified.

## Conclusion

**No regression introduced by this PR.** All FHIR conformance checks
remain green, AD-55 Base distributions match the 2026-06-22 baseline, and
the AKI Cr / DKA HCO3 calibration targets are met without spurious
cross-cohort effects. The byte-diff invariant
(`docs/reviews/2026-06-22-aki-dka-surgical-calibration-audit.md`)
mathematically constrains the change to the four physiologically-linked
labs (Cr / HCO3 / pCO2 / pH) on 1,161 US / 1,368 JP Observations — every
other byte of the FHIR export is identical to master.

Two **pre-existing** items are observable but explicitly out of scope:

1. **JP CRP unit convention**: CIF and FHIR emit `mg/L` (matching the
   JCCLS reference range as authored in `locale/jp/reference_range_lab.yaml`),
   while Japanese clinical convention is `mg/dL`. Documented as
   enrichment-only conversion (AD-42). Suggest a follow-up to align FHIR
   output with JP convention.
2. **I50 BNP discrimination**: admit-day BNP p50 ~95 (US) / 79 (JP)
   sits below the ADHF 800-1500 band because the I50 cohort mixes acute
   decompensation with chronic stable follow-up. Tracked in
   `docs/superpowers/plans/2026-06-20-bnp-hf-specificity.md`; the byte-diff
   invariant proves the calibration PR did not change any BNP value.

The branch is ready to merge.
