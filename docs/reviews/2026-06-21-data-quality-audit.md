# CIF / FHIR Data Quality & Clinical Coherence Audit — 2026-06-21

Generated US (pop 40,000, seed 42) + JP (pop 5,000, `--jp-insurance`, seed 42),
CIF + FHIR R4. US export: 24,564 patients / ~5.7M resources. JP: 2,439 patients /
558k resources. Audit scripts in `/tmp/clinosim_audit/` (not committed).

## 1. FHIR R4 conformance — EXCELLENT (both locales)

| Check | US | JP |
|---|---|---|
| Duplicate `id` within type | **0** | **0** |
| Unresolved references | **0** | **0** |
| `display == code` codings | **0** | **0** |
| Language purity | **0 Japanese in US** (100% EN) | localized (504k/558k JP) |
| Numeric Obs: missing `referenceRange` | 248,916 / 2.15M (11.5%) | 35,477 / 272k (13%) |
| Numeric Obs: `referenceRange`+`interpretation` inconsistent | **0** | **0** |

The "missing referenceRange" Observations are **exactly 4 legitimately range-less
measurement types** in both locales: *Supplemental oxygen flow rate* (a therapy
dose) + *24h Fluid intake / Urine output / Fluid output totals* (I/O volumes).
These correctly omit a reference range. **No FHIR conformance defect.**

## 2. Clinical coherence — STRONG

### HbA1c / glycemic_control (new feature, PR #44) — verified on real output
- **DM HbA1c per-patient**: US median 7.3 (p25 6.2 / p75 9.0), JP median 7.0.
  US 45% <7%, 26% ≥9%; JP 49% <7%, 22% ≥9%. Matches real-world diabetic control.
- **Non-DM HbA1c**: median 5.2 (both locales) — correctly normal.
- **HbA1c ↔ Glucose coherence**: per-patient correlation **r = 0.51 (US) / 0.54 (JP)**
  — a poorly-controlled diabetic shows both high HbA1c and high glucose, as intended.
- Condition.stage HbA1c matches lab HbA1c within an encounter (mean |diff| 0.52);
  cross-encounter discordance is a symptom of Issue A below, not the HbA1c model.

### Disease → lab coherence (encounter diagnosis vs labs)
- **Acute MI (I21)**: Troponin median ~80 (normal <0.04), CK-MB ~41 (normal <5) — massive elevation, correct.
- **Sepsis (A41)**: Lactate 3.9–4.9, WBC ~12k, CRP ~150 — elevated, correct.
- **Pneumonia**: CRP ~152, WBC ~14.5k — elevated, correct.
- **CKD comorbidity (N18)**: Creatinine median 1.43 — elevated baseline, correct.
- **HF exacerbation (I50)**: BNP tail p75 507 / p90 1160 / max 5000, 16% ≥800
  (acute-exacerbation range per PR #28); comorbid/stable HF lower. Coherent.

### Vitals coherence
- Sepsis: max-temp 40.3 °C (fever), min-SpO2 86% (hypoxia). Pneumonia: max-temp 39.5 °C. Correct.

## 3. Issues found

### A. [HIGH, pre-existing] `activate_patient` is non-idempotent — patient history is unstable across encounters

**Evidence:** 55% (US, 6,143/11,248) and 71% (JP, 231/325) of diabetic patients
have **more than one distinct onset date for the same E11 chronic condition**
(one JP patient had 8 different diabetes onset dates). 18% have >1 distinct
Condition.stage HbA1c.

**Root cause:** `simulator/engine.py` calls `activate_patient(person, rng, demo)`
at **5 sites** (≈ L175 inpatient admission, L259 readmission, L299 post-discharge,
L335 calendar, L396 occupational), but `patient_cache` is consulted by only **two**
of them (L299, L335). A person who appears in multiple phases (admission +
outpatient follow-up + screening + readmission) is **re-activated each time**, and
`activate_patient` re-samples every derived attribute: chronic-condition onset
dates / severity / **stage (incl. HbA1c)**, the `PhysiologicalProfile` (renal /
cardiac / hepatic reserve → so even baseline creatinine etc. differ per admission),
and baseline vitals.

**Impact:** a patient's "stable" medical history is internally inconsistent across
their own encounters — an EHR-coherence defect that pre-dates and is broader than
the HbA1c work (HbA1c stage merely made it visible). Acute disease→lab coherence
within a single encounter is unaffected (onset is applied per encounter).

**Fix (follow-up, golden-changing):** route **all** activation sites through one
shared `patient_cache` keyed by `person_id`, so each person is activated exactly
once. Determinism note: this changes the RNG consumption pattern (fewer
activations) → golden output changes; it is the correct fix and should land as its
own PR with regenerated goldens. Watch memory for 24k cached `PatientProfile`s.

### B. [LOW / observational] Sepsis systolic BP

Sepsis min-SBP median ~118 mmHg — most A41 encounters are not hypotensive. Septic
**shock** (the hypotensive subset) may be under-represented; consider tying SBP
more strongly to `perfusion_status` for severe sepsis. Not a conformance issue.

## 4. Verdict

FHIR R4 output is **conformant and clean** in both locales; clinical coherence
(labs/vitals vs disease & comorbidity, and the new HbA1c↔glucose↔control axis) is
**strong**. The one substantive finding is the **pre-existing `activate_patient`
non-idempotency (Issue A)** — recommended as the next fix (own PR, golden-changing).
