# Lab orders and results — specification

Status: **normative**. Every change that orders a lab test, derives or generates a lab value, flags a result, links a result to its order, or reads lab results for eval follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`lab-orders-and-results-spec.ja.md`](lab-orders-and-results-spec.ja.md).

Related specs, linked rather than restated:
- Lab codes (LOINC / JLAC10), lab names and aliases, display names: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) §3.9 / §4.1.
- Per-order random streams (specimen, noise): [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md) §3.
- Lab analytes and their constants (units, CV, limits, normals): [`configuration-and-reference-data-spec.md`](configuration-and-reference-data-spec.md).

## 1. Principles

1. **One true value per patient and moment.** The true (pre-noise) value of every analyte comes from one function of the patient's physiological state, conditions, medications and longitudinal history. Every encounter kind calls it, so the same patient is measured the same way in the ED, the clinic and the ward.
2. **One identity per test.** Every boundary turns a test name into its canonical lab name before it decides anything, so aliases and spellings never split one test into two.
3. **Every order has its result, every result its order.** A resulted lab order is completed by its result, an unresulted one is revoked at discharge, and a culture result reports the culture order it came from.
4. **The generator and the evaluator share their limits.** Eval checks the cohort against the same physiologic limits the generator clamps to.
5. **Every rule has a guard.** Each rule names the test that enforces it; a rule without one is listed in §6.

## 2. True values

| Rule | Canonical code | Guard |
|---|---|---|
| Every encounter kind takes true lab values from one function, with the patient's sex, age, diabetes and dyslipidemia (value sets), longitudinal HbA1c of the year and the scenario + medication flags: inpatient daily loop, ED, outpatient, unknown condition, medication monitoring. | `simulator/lab_pipeline.py::patient_true_labs` (over `physiology/engine.py::derive_lab_values`) | `tests/unit/test_lab_spec_guards.py::test_true_lab_values_only_through_patient_true_labs`, `tests/unit/modules/monitoring/test_monitoring_true_labs_2735.py` |
| An analyte physiology does not model falls back to its reference normal (`baseline_normals`). | `observation/engine.py::BASELINE_LAB_NORMALS` | `tests/unit/test_phosphate_magnesium_co2_2687.py` |
| Whether a patient is on warfarin is decided once and drives the INR value, its flag and its therapeutic range. | `observation/engine.py` (`medications_in_effect`, `therapeutic_range`), `physiology/engine.py::medication_flags_from_context` | `tests/unit/test_warfarin_status_2293.py` |
| Troponin I without an acute coronary syndrome stays normal for a healthy adult (the age-reduced reserve alone does not lift it); chronic elevation comes from heart failure, CKD stage 4-5 and very old age, and only the ACS flag gives MI-level values. | `physiology/engine.py::_add_cardiac_labs`, `physiology/_lab_derivation_thresholds.py` (`TROPONIN_*`) | `tests/unit/test_troponin_chronic_calibration_2903.py`, `tests/unit/test_blood_markers.py` |
| A child (under 18) is judged against the interval for their age, read from one table: the CIF flag, the FHIR referenceRange and its text, and the true value (creatinine, Hb / Hct, WBC and ALP centre on the interval for the age). Vital signs of a child use the age-band ranges of the same table for referenceRange, interpretation and text, and baseline vitals centre on the age-band median. A child's generated respiratory rate may rise to the age-band ceiling of the same table (`physiological_max`: 80 /min under 1 year, 60 to 5 years, 50 to 11 years) instead of the adult 45. NEWS2 is not scored under 16. | `observation/pediatric_ranges.py`, `observation/reference_data/pediatric_reference_ranges.yaml`, `physiology/engine.py::pediatric_lab_scale`, `physiology/engine.py::rr_clamp_max` | `tests/unit/test_pediatric_reference_ranges_2872.py`, `tests/unit/test_rr_clamp_by_age_2926.py` |
| A statin lowers the untreated LDL by its intensity (2018 ACC/AHA Table 3: low < 30 %, moderate 30-49 %, high ≥ 50 %), at a fixed per-patient position in the range (SHA-256 quantile of the patient id, no RNG draw); TC falls by the same mg/dL. The intensity comes from the statin and its dose, the same table in both countries. | `physiology/statin_response.py::statin_ldl_reduction` via `physiology/engine.py::medication_flags_from_context` (`statin_ldl_reduction`) and `_add_lipid_labs`; data `physiology/reference_data/statin_ldl_response.yaml` | `tests/unit/modules/test_statin_ldl_response_2917.py` |

## 3. Identity and panels

| Rule | Canonical code | Guard |
|---|---|---|
| Every boundary resolves a test name through the canonical lab name and the alias table: the simulator, FHIR ServiceRequest / Observation, the hospital-course extractor, health checkups, benchmarks. | `observation/engine.py::canonical_lab_name`, `observation/reference_data/lab_aliases.yaml` | `tests/unit/test_lab_identity_2299.py`, `tests/unit/test_checkup_canonical_labs_2300.py` |
| A dyslipidemia patient on a statin has the whole lipid panel (TC, LDL, HDL, TG), never a single analyte, at the renewal visit: at the first monitoring visit, 4 weeks or more after a statin change, else about 6-monthly (2018 ACC/AHA: 4-12 weeks after a change, then every 3-12 months). | `simulator/statin_monitoring.py` (`lipid_panel_due`, `lipid_panel_labs`); data `simulator/reference_data/statin_monitoring.yaml` | `tests/unit/simulator/test_statin_monitoring_2877.py` |
| Panels are defined once, and ordering groups tests into panels and stand-alone tests through one classifier. | `observation/reference_data/lab_panels.yaml`, `order/panel_grouping.py::classify_lab_specs` | `tests/unit/test_lab_bounds_panels_2332.py`, `tests/unit/test_lab_panel_registry.py` |

## 4. Results and their orders

| Rule | Canonical code | Guard |
|---|---|---|
| A culture result comes from a culture order: one result per draw of the stay's culture orders, and a profile culture that no protocol order placed is ordered at admission. FHIR links each culture result to its order(s) through one matcher. | `observation/microbiology.py` (`culture_draws`, `culture_results`), `fhir_r4/labs/microbiology.py::culture_orders_for` | `tests/unit/test_cultures_from_orders_2640.py` |
| A lab ServiceRequest is completed by its result (a DiagnosticReport or a culture), and revoked when its stay ends without one. | `fhir_r4/labs/service_request.py` | `tests/unit/test_lab_orders_resulted_or_cancelled_2661.py::test_an_unresulted_order_of_a_discharged_stay_is_revoked`, `tests/unit/output/test_fhir_microbiology_links_2585.py::test_the_orders_a_culture_reports_are_completed_and_the_others_are_not`, `tests/integration/test_servicerequest_snapshot.py` |
| A type-and-screen order is resulted by the blood group and antibody screen it reports. | `simulator/lab_pipeline.py::TYPE_AND_SCREEN`, `fhir_r4/labs/blood_type.py` | `tests/unit/output/test_type_and_screen_2587.py` |

## 5. Eval bounds

| Rule | Canonical code | Guard |
|---|---|---|
| Eval's physiological-range bounds for the units clinosim emits are the generator's `physiologic_limits`, mapped to LOINC through the US lab code mapping. `lab-plausibility-bounds.yaml` adds only other unit spellings, for third-party cohorts. | `eval/axes/clinical.py::_lab_bounds_from_yaml`, `observation/reference_data/lab_constants.yaml` | `tests/unit/test_lab_bounds_panels_2332.py` |

## 6. Gaps

| Gap | Where |
|---|---|
| The statin's LDL effect is in full from the first day; the 4-6 weeks to the full response are not modelled (the panels after a change are drawn 4 weeks or more later). | `physiology/statin_response.py` |
