# AKI Cr / DKA HCO3 surgical calibration — audit (2026-06-22)

## Summary

PR `fix/aki-dka-surgical-calibration` reduces AKI admit Creatinine and DKA admit
HCO3 lab values into the published KDIGO / ADA clinical bands by adjusting two
single coefficients inside `derive_lab_values()`, leaving state, coupling rules,
and disease YAMLs at master. The byte-diff invariant ("only `Observation.ndjson`
differs") holds at US `p=2000` and JP `p=2000` (`--jp-insurance`), `seed=42`; the
patient cohort is preserved exactly (US 1274/1274, JP 977/977). A larger-scale
percentile audit (US `p=8000`, JP `p=4000`) confirms the affected cohorts shift
into clinical bands while non-affected cohorts are unchanged in central tendency.

## Surgical coefficient changes

- Cr low-renal slope: **15 → 6.5** (`derive_lab_values` renal branch). With
  base_cr = 0.9 (male), `state.renal_function = 0.0` now maps to Cr ≈ 5.05 mg/dL
  (KDIGO 3 mid-high), not 9.3 (ESRD).
- HCO3 metabolic-axis gain: **24 → 31** (`derive_lab_values` blood-gas section).
  Pure metabolic axis, `state.ph_status = -0.35` (DKA moderate per master YAML)
  now maps to HCO3 ≈ 13.15 mEq/L (ADA moderate band 10-15), not 15.6.

`state.renal_function` and `state.ph_status` are unchanged from master, so
`clinical_course/engine.py::evaluate_complications` reads identical state and
consumes identical RNG draws. This is the BNP-pattern (#28) / sepsis SBP (#62)
surgical approach — the prior WIP on `fix/aki-cr-dka-acidosis-calibration`
(eda694c2), which mutated AKI/DKA YAML `initial_state_impact`, was discarded
because byte-diff showed it cascaded through master-RNG-shared clinical course
(1509 non-AKI/DKA patient Observations shifted, patient count drifted 1274 →
1299).

## Byte-diff invariant (gold criterion)

```
byte-diff snapshot 8b31b31b test(physiology): DKA moderate admit HCO3 lands in ADA moderate band

=== US ===
  AllergyIntolerance.ndjson                same
  Condition.ndjson                         same
  DiagnosticReport.ndjson                  same
  Encounter.ndjson                         same
  FamilyMemberHistory.ndjson               same
  Immunization.ndjson                      same
  Location.ndjson                          same
  MedicationAdministration.ndjson          same
  MedicationRequest.ndjson                 same
  Observation.ndjson                       DIFFERS (expected for Observation)
  Organization.ndjson                      same
  Patient.ndjson                           same
  Practitioner.ndjson                      same
  PractitionerRole.ndjson                  same
  Procedure.ndjson                         same
  Specimen.ndjson                          same
=== JP ===
  AllergyIntolerance.ndjson                same
  Condition.ndjson                         same
  Coverage.ndjson                          same
  DiagnosticReport.ndjson                  same
  Encounter.ndjson                         same
  FamilyMemberHistory.ndjson               same
  Immunization.ndjson                      same
  Location.ndjson                          same
  MedicationAdministration.ndjson          same
  MedicationRequest.ndjson                 same
  Observation.ndjson                       DIFFERS (expected for Observation)
  Organization.ndjson                      same
  Patient.ndjson                           same
  Practitioner.ndjson                      same
  PractitionerRole.ndjson                  same
  Procedure.ndjson                         same
  Specimen.ndjson                          same

Patient counts:
  /tmp/byte_master_us:     1274 patients
  /tmp/byte_branch_us:     1274 patients
  /tmp/byte_master_jp:      977 patients
  /tmp/byte_branch_jp:      977 patients

Observation value-change distribution (LOINC/JLAC10):
  US: 1161 Observations differ
    2160-0  581    (Creatinine, LOINC)
    1963-8  228    (HCO3, LOINC)
    2019-8  187    (pCO2, LOINC — Henderson-Hasselbalch downstream)
    2744-1  165    (pH, LOINC — Henderson-Hasselbalch downstream)
  JP: 1368 Observations differ
    3C015   929    (Creatinine, JLAC10)
    3G125   151    (HCO3, JLAC10)
    3H055   150    (pCO2, JLAC10)
    3H050   138    (pH, JLAC10)
```

Every `Observation.ndjson` difference is a numerical `valueQuantity.value` shift
on Cr / HCO3 / pCO2 / pH — no resource id changes, no structural drift. pCO2 and
pH co-shift because Henderson-Hasselbalch + Winter's compensation run in the
same `derive_lab_values` block.

## Admit-day percentile audit (US p=8000, JP p=4000)

`/tmp/audit_calibration.txt` — full output. Key cohorts:

### N17 (AKI) — primary target

| cohort | n | min | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|---|
| US master | 5 | 4.30 | 5.41 | **5.63** | 6.30 | 9.07 | 9.07 |
| US branch | 5 | 2.64 | 3.17 | **3.29** | 3.53 | 4.92 | 4.92 |
| JP master | 4 | 6.37 | 6.56 | **7.87** | 10.70 | 10.70 | 10.70 |
| JP branch | 4 | 3.62 | 3.74 | **4.51** | 5.81 | 5.81 | 5.81 |

AKI admit Cr p50 moves from ESRD/dialysis territory (5.6 / 7.9) into the KDIGO 2-3
band (3.3 / 4.5). Maxima drop from 9.07 / 10.70 to 4.92 / 5.81 — published KDIGO
3 admit Cr is typically 4-6 mg/dL.

### N18 (CKD) — side benefit (state unchanged, tail compresses)

| cohort | n | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|
| US master | 156 | 1.20 | 1.37 | 1.68 | 2.72 | 4.45 |
| US branch | 156 | 1.20 | 1.37 | 1.63 | **2.09** | **3.03** |
| JP master | 318 | 1.20 | 1.42 | 2.03 | 3.69 | 7.74 |
| JP branch | 318 | 1.20 | 1.41 | 1.81 | **2.62** | **4.31** |

Central tendency unchanged (p50 stable), upper tail compressed into realistic
CKD3 range (~3-4 mg/dL). The slope change only affects encounters where
`state.renal_function < 0.5`, which is the severe-CKD tail.

### E11 (Type 2 diabetes admits) — DKA subset target, mixed-cohort behavior

| cohort | n | min | p25 | p50 | p75 | p90 | max |
|---|---|---|---|---|---|---|---|
| US master HCO3 | 141 | 9.4 | 15.7 | **17.2** | 18.5 | 19.4 | 21.5 |
| US branch HCO3 | 141 | **5.4** | **13.3** | 15.3 | 16.7 | 17.9 | 20.2 |
| US master pH | 131 | 7.18 | 7.30 | 7.31 | 7.33 | 7.34 | 7.36 |
| US branch pH | 131 | **7.03** | 7.27 | 7.29 | 7.31 | 7.33 | 7.35 |

The E11 cohort mixes DKA admits (ph_status = -0.35 metabolic) with type 2 DM
admits for unrelated complaints (no ph perturbation). The branch's HCO3 / pH
distribution shows correct severity stratification: HCO3 min 5.4 / pH min 7.03
correspond to severe DKA in the master ph_status mapping (-0.60); HCO3 p25 13.3
matches moderate DKA (ph_status -0.35). The acceptance test
`test_dka_moderate_acidosis_in_clinical_range` independently verifies that a
moderate-severity DKA admit lands in HCO3 ∈ [10, 15.5], pH ≤ 7.27.

### A41 (sepsis), I50 (HF), I21 (MI), J18 (pneumonia) — non-target cohorts

| cohort (Cr p50) | master | branch |
|---|---|---|
| A41 US | 1.49 | 1.45 |
| I50 US | 1.53 | 1.51 |
| I21 US | 1.70 | 1.68 |
| J18 US | 1.69 | 1.69 |

Central tendency unchanged in every non-target cohort, with at most a 0.04 mg/dL
p50 shift attributable to tail compression in patients whose renal coupling
dropped into the slope's domain. No spurious cross-cohort effects.

## Why no cascade

Spec: `docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md`.

`state.renal_function` and `state.ph_status` derive from `apply_disease_onset`
(disease YAML) and `apply_coupling_rules`, neither of which is touched. After
admission `clinical_course/engine.py::evaluate_complications` reads `state`,
draws from the encounter RNG, and may trigger complications that themselves draw
from the same RNG; because state is byte-identical to master, the draws are
identical and the patient cohort is preserved. The Cr / HCO3 / pCO2 / pH that
`derive_lab_values` renders into Observations are the only thing that changes.

## Follow-ups

- **K / BUN distributions**: not retuned here. State-driven downstream labs
  (e.g. `state.renal_function < 0.3` → hyperkalemia coupling) inherit the same
  state; current K p99 audit acceptable on inspection but not formally retuned.
  Track at next audit.
- **DKA severe pH floor**: branch min pH 7.03 (US) / 7.05 (JP) — within
  published severe DKA range (6.9-7.1). Henderson-Hasselbalch + Winter's
  compensation in `derive_lab_values` already protects against unphysiological
  values; no clamp added.
- **JP N17 sample size**: n=4 across p=4000 — N17 is a low-incidence direct
  admit. Distribution-shape claims rely more on the pure unit-test pin
  (`test_creatinine_curve_matches_clinical_bands`) than on this audit's p50.
