# Evaluation rules

This page catalogs every check `clinosim eval` runs, its severity, its
scoring formula, and (for the clinical-coherence checks) the literature
source for the expected band. See [Evaluation](eval.md) for the CLI
usage.

## Axis-level rollup

For every axis:

- **Score** = 100 × Σ(check pass-weight × check weight) / Σ(check weight)
- **Check weight** = severity: CRITICAL = 3, MAJOR = 2, MINOR = 1
- **Pass-weight** = PASS 1.0, WARN 0.5, FAIL 0.0, N/A 0.0

**Overall score** = arithmetic mean of the three axis scores.
**Overall status** = worst of FAIL / WARN / PASS across axes.

---

## Structural axis (5 checks)

Reject cohorts that break FHIR R4 invariants regardless of content
quality.

| Name | Severity | Passes when |
|---|---|---|
| `resource_id_uniqueness` | CRITICAL | No duplicate `id` within one resourceType |
| `reference_integrity` | CRITICAL | Every internal `reference` (`Type/id`) resolves to an emitted resource |
| `required_fields_present` | MAJOR | Patient.identifier / Encounter.status / Condition.subject non-empty |
| `meta_profile_declared` | MAJOR (JP) | Every JP Core primary resourceType declares `meta.profile`; N/A for non-JP |
| `resource_type_consistency` | MINOR | Every NDJSON row's `resourceType` matches its filename |

---

## Clinical axis (7 checks)

**MVP** (P1-8) — 5 checks that guard schema-level physiological
plausibility:

| Name | Severity | Passes when |
|---|---|---|
| `lab_values_physiological_range` | MAJOR | LOINC-coded lab values fall inside gross physiological bounds (WBC 0–500, Hb 0–25, Cr 0–30, ...) |
| `age_condition_consistency` | MAJOR | No adult-only ICD codes (I10, I25, I48, I50, E11, N18, N40, F03) on pediatric patients (< 12 y) |
| `medication_date_sanity` | MAJOR | MedicationRequest.authoredOn ≥ Patient.birthDate |
| `encounter_temporal_ordering` | MAJOR | Encounter.period.start ≤ .end |
| `condition_encounter_link` | MINOR | When Condition.encounter is set, it resolves to an emitted Encounter |

**Coherence** (P1-9) — 2 checks that flag data that is
schema-valid but **clinically implausible** — the "sepsis without
lactate lift" family.

### `condition_lab_coherence` (MAJOR)

For each Condition matching one of the pairings below, find the same
patient's related lab drawn within **±7 days** of the Condition
onset. If the lab value is outside the expected band, count as a
violation. Aggregate across all pairings:

- Violation rate ≤ **5%** → PASS
- 5% – 25% → WARN
- > 25% → FAIL

Rates below 5% reflect natural biological variability and small window
mismatches. Rates above 25% indicate the physiology model has decoupled
from the diagnosis label.

| Pairing name | ICD prefix(es) | Lab (LOINC) | Expected band | Source |
|---|---|---|---|---|
| `sepsis_lactate` | A41.* | 2524-7 (venous lactate) | **≥ 2.0 mmol/L** | [Surviving Sepsis 2021](https://www.sccm.org/SurvivingSepsisCampaign/Guidelines/Adult-Patients) |
| `dka_hco3` | E10.10-11, E11.10-11 | 1963-8 (HCO₃) | **< 18 mEq/L** | [ADA DKA severity criteria](https://diabetesjournals.org/care/article/32/7/1335) |
| `acute_mi_troponin` | I21, I22 | 10839-9 (Troponin I) | **> 0.04 ng/mL** (99th %ile URL) | [Fourth Universal Definition of MI](https://www.jacc.org/doi/10.1016/j.jacc.2018.08.1038) |
| `ckd_stage_creatinine` | N18.3-N18.5 | 2160-0 (Cr) | **> 1.3 mg/dL** | [KDIGO 2012](https://kdigo.org/guidelines/ckd-evaluation-and-management/) |
| `t2dm_hba1c` | E11.9 (uncontrolled T2DM) | 4548-4 (HbA1c) | **≥ 6.5%** | [ADA diagnostic threshold](https://diabetesjournals.org/care/article/47/Supplement_1/S20/153954) |
| `bacterial_pneumonia_wbc` | J13, J14, J15 | 6690-2 (WBC) | **> 11.0 × 10⁹/L** | SIRS / infection response |
| `anemia_hgb` | D50–D64 (excluding D54–D61 uncommon) | 718-7 (Hb) | **< 12.0 g/dL** | [WHO anemia cutoffs](https://www.who.int/publications/i/item/9789240088542) |
| `chf_bnp` | I50.* | 30934-4 (BNP) | **> 100 pg/mL** | Framingham / [ACC-AHA HF guidelines](https://www.acc.org/latest-in-cardiology/ten-points-to-remember/2022/04/06/12/57/2022-aha-acc-hfsa-guideline-for-the-management-of-hf) |

To add a pairing: append to `_CONDITION_LAB_PAIRINGS` in
[`clinosim/eval/axes/clinical.py`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/eval/axes/clinical.py)
and cite the source here.

### `medication_lab_coherence_warfarin` (MAJOR)

When a patient carries a MedicationRequest for warfarin (RxNorm
`11289` OR YJ code prefix `3332001`), every PT-INR observation
(LOINC `6301-6`) drawn **on or after** the earliest warfarin
`authoredOn` must sit in **2.0–3.5**. Rates use the same
5% / 25% thresholds as the pairings above.

The band is broader than the 2.0–3.0 target of the AF stroke-prevention
indication because comorbidities (cirrhosis, DIC) legitimately shift
INR to the 3.0–3.5 side; the Warfarin PT-INR coupling in the physiology
engine (AD-57) is calibrated to match.

---

## Locale axis (5 checks)

Cohort-country is auto-detected from `Patient.address.country` or the
presence of a JP Core `meta.profile` on the first Patient. Override
with `--country US` / `--country JP`.

### JP cohorts

| Name | Severity |
|---|---|
| `japanese_displays_on_condition` | MAJOR |
| `jlac10_or_loinc_on_lab` | MAJOR |
| `yj_code_on_medications` | MAJOR |
| `jp_core_profile_declared` | MAJOR |
| `jp_name_order` | MINOR |

### US cohorts

| Name | Severity |
|---|---|
| `ascii_only_displays` | MAJOR |
| `rxnorm_present_on_medications` | MAJOR |
| `loinc_present_on_lab_observations` | MAJOR |
| `no_japanese_leakage` | CRITICAL |
| `us_practitioner_name_order` | MINOR |

---

## Adding a rule

1. Open the relevant axis file under
   [`clinosim/eval/axes/`](https://github.com/TomoOkuyama/clinosim/tree/master/clinosim/eval/axes/).
2. Add a `_check_<name>(cohort, country) -> EvalCheck` helper. Return
   an `EvalCheck` with `Outcome.PASS` / `WARN` / `FAIL` / `NA` and a
   `Severity`.
3. Append it to the axis's `run()` return list.
4. Add a unit test in
   [`tests/unit/test_eval_axes.py`](https://github.com/TomoOkuyama/clinosim/blob/master/tests/unit/test_eval_axes.py)
   that crafts a minimal mini-cohort triggering the FAIL outcome.
5. If the check consumes new clinical thresholds, cite the source in
   this file.
6. Update `CHANGELOG.md`.

Small, well-scoped additions review faster than a one-shot rewrite.
