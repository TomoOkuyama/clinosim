# Changelog

All notable changes to **clinosim** are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Versioning policy (from v0.4.0 onward)

Version numbering is scoped to the **CIF ↔ narrative-CIF consistency
contract**, since narrative CIF is generated from structured CIF via the
`narrate` pipeline and downstream consumers key on both together.

- **MINOR bump (`0.n` → `0.(n+1)`)** — the change **breaks CIF ↔
  narrative-CIF consistency**. An existing narrative CIF is no longer
  valid against the new structured CIF (schema drift, field
  add/remove/rename, semantic value change, RNG cascade). A fresh
  `narrate` run is required to restore consistency.
- **PATCH bump (`0.n.x` → `0.n.(x+1)`)** — the change **preserves CIF ↔
  narrative-CIF consistency**. Structured CIF is byte-unchanged (or
  changes only in fields that the narrative CIF does not surface), so
  the existing narrative CIF still holds. FHIR-emit-only changes,
  opaque-id migrations, bug fixes that leave CIF intact, downstream
  format changes.
- **MAJOR bump** — reserved for incompatible API changes at the Python
  module boundary (import path removals, function signature breaks).
  CIF/FHIR schema changes without API breaks stay at MINOR.

Determinism guarantee: for a given `(seed, hospital_config, country,
start, end, population)` tuple, the structured CIF must be byte-identical
across PATCH-only releases within the same MINOR line. MINOR releases
may change structured CIF but must document the drift here.

Historical note: releases before v0.4.0 used a simpler "CIF or FHIR
byte-output change ⇒ MINOR" rule and are not retroactively renumbered.
The initial v0.5.0 tag (2026-08-27, Issue #854 Bucket A+B closeout) was
cut before this policy was formally documented and has been renumbered
to v0.4.1 to align with the new policy — the Bucket A+B changes are
FHIR-emit-only, so CIF↔narrative-CIF consistency is preserved.

## [Unreleased]

### Fixed

- **Prednisone + Prednisolone dual emit on US corticosteroid encounters**
  (Issue #1323). US COPD exacerbation encounters carried both drugs
  (Prednisone = prodrug of Prednisolone, same active moiety) on
  186/286 (65 %) encounters because the disease-YAML
  ``supportive.steroid`` block had a single locale-blind ``detail``
  string ("Prednisolone 40mg PO daily x5 days") while the
  locale-aware ``drugs.discharge_oral`` block emitted the US-form
  Prednisone separately.

  Fix: added an optional ``locale_detail: {jp: "...", us: "..."}``
  map on ``supportive[]`` items and an equivalent ``locale_name`` on
  encounter-YAML ``treatment[]`` items. Old entries with only the
  bare ``detail`` / ``name`` keep working unchanged. Applied to
  ``copd_exacerbation.yaml`` supportive steroid entry and
  ``encounter/asthma_attack_mild.yaml`` treatment steroid entry.

  Verification (p=500 s=356):
    US: 17/17 Prednisone-only (was 65 % dup on the p=10k baseline)
    JP: 18/18 Prednisolone-only (unchanged — JA behaviour preserved)

  FHIR-emit-only change on the discharge path but CIF-affecting on
  the admission-supportive path (US patients now emit
  ``Prednisone`` instead of ``Prednisolone`` as the supportive
  medication order display_name); classified MINOR under the
  CIF-narrative consistency policy.


- **JP MedicationAdministration.medicationCodeableConcept.text emits
  Japanese for chemo drugs** (Issue #1310). PR #1303 catalogued
  Gemcitabine / Irinotecan / Nab-paclitaxel / Temozolomide / BCG with
  Japanese displays on the HOT7 and RxNorm codings, but
  ``clinosim/locale/shared/drug_names_ja.yaml`` — the SoT consumed by
  ``_localize_drug_name`` for the top-level ``.text`` field — had no
  entries for the five new drugs, so JP consumers reading
  ``.text`` first saw the English name. Added entries for
  Gemcitabine / Irinotecan / Nab-paclitaxel (both hyphenated and
  underscored variants) / Temozolomide / BCG (including the
  ``BCG intravesical`` disease-YAML alias). p=200 s=356 JP verify:
  Temozolomide now emits as ``テモゾロミド`` on both
  MedicationRequest and MedicationAdministration. FHIR-emit-only
  change: CIF byte-unchanged; PATCH.
- **Depression Condition emits bare F32 / F33 (non-billable ICD-10-CM)**
  (Issue #1309, US-only). ``F32`` and ``F33`` are ICD-10-CM category
  headers; billable leaves are ``F32.0-F32.9`` and ``F33.0-F33.9``. The
  sim's current mood-cohort modeling has no severity subtyping, so the
  clinically-appropriate leaf is ``.9`` "unspecified". Added
  ``F32 → F32.9`` and ``F33 → F33.9`` to
  ``clinosim/locale/us/code_mapping_diagnosis.yaml`` and the
  corresponding ``F32.9`` / ``F33.9`` displays to
  ``clinosim/codes/data/icd-10-cm.yaml``. p=10k s=356 baseline: 484
  bare F32 + 128 bare F33 → 0 after fix; all become F32.9 / F33.9 with
  the same cohort volume. JP-side counterpart (#1320) tracked
  separately (requires broader WHO ICD-10 leaf additions to
  ``icd-10.yaml``).

- **Non-daily MedicationRequest.dosageInstruction.timing.repeat coverage**
  (Issue #1348). The prior derivation table recognised only daily / q6h
  / q4h / q3h / q2h / qhs, so ``weekly`` (Alendronate),
  ``nightly`` (Mirtazapine), ``every_3_days`` / ``every_other_day``,
  ``monthly``, and chemo per-cycle ``q3weeks`` labels fell through to
  the plain-text branch with no structured ``timing.repeat`` emit —
  Alendronate 99.8 %, Mirtazapine 100 %, Trastuzumab / Oxaliplatin
  IV cycles all lacked cadence.

  Fix: introduced ``resolve_timing_repeat`` in
  ``clinosim/modules/output/fhir_r4/lib/common.py`` — one shared
  lookup table (``_FREQ_LABEL_TIMING``) keyed on frequency label,
  returning ``(frequency, period, periodUnit)`` with UCUM units
  ``h``/``d``/``wk``/``mo``. Cover new labels: ``nightly``, ``qam``,
  ``qpm``, ``q1h``, ``every_other_day``, ``qod``, ``every_3_days``,
  ``weekly``/``qweek``/``1x/week``, ``monthly``/``qmonth``,
  ``q3weeks``/``q3wks``/``every 3 weeks``, ``q4wks``. A trailing
  ``PRN`` suffix on any cadence (``q6h PRN``) now emits BOTH the
  fixed ``timing.repeat`` AND ``asNeededBoolean=true`` — FHIR-valid
  "up to every 6 hours as needed" semantics.

  ``_build_discharge_medication_request`` (medications.py) was
  duplicating a smaller frequency lookup and is now routed through
  the same helper, so discharge / outpatient-renewal MRs pick up the
  weekly / per-cycle cadence coverage without a separate second edit.

  Verification (p=200 s=356 US sim + FHIR export):
    Alendronate  30/30 with `timing.repeat` (was 3/30)
    Mirtazapine   1/1  with `timing.repeat` (was 0/1)
    Trastuzumab   8/8  with `timing.repeat` (was 0/8)
    Oxaliplatin  12/12 with `timing.repeat`
    Salbutamol   83/83 with `asNeededBoolean=true` (correct PRN)
    Overall US p=200: 91.6 % (was 87.4 % on the p=10k baseline)

  Remaining gap: Insulin sliding-scale MRs (~0.6 % of the pool)
  arrive at the emitter with no ``frequency`` field set at all — the
  upstream chronic-med sampler / disease-YAML author has not authored
  cadence for sliding-scale prescriptions. Separate PR.

  FHIR-emit-only change: CIF is byte-unchanged; classified PATCH
  under the CIF-narrative consistency policy.

### Added

- **CAD (I25.x) secondary-prevention statin chronic med**
  (Issue #1338). Class-I evidence in ACC/AHA 2018, ESC 2019, and JAS
  2022 secondary-prevention guidelines. The prior sim modelled statin
  ONLY under E78 (dyslipidemia chronic block), so 39 % of CAD
  patients without an E78 chronic diagnosis carried zero statin.
  Added ``Atorvastatin 40 mg PO daily`` (high-intensity, first-line
  per guidelines) with ``probability: 0.90`` (matches real-world
  adherence 85-90 %, with headroom for statin-intolerance
  exclusions) to the I25 medications block in
  ``clinosim/locale/shared/chronic_medications.yaml``.

  Chronic-med dedup handles the I25+E78 collision (drug_name-keyed).
  Verification (p=500 s=356 US): CAD patients with statin: 11/14
  (78.6 %) — was ~61 % baseline. RNG cascade: one added
  ``rng.random()`` draw per I25 patient (chronic-med sampler);
  classified MINOR under the CIF-narrative consistency policy for
  the affected cohort.
- **US Core Patient extensions** — us-core-race, us-core-ethnicity,
  us-core-birthsex (Issue #1344). Every US Patient resource previously
  emitted with no extensions at all, so 100 % of the cohort failed US
  Core AllPatients profile conformance. Adds three
  Extension builders in ``clinosim/modules/output/fhir_r4/demographics/
  patient.py`` and wires them into ``_build_patient`` behind an
  ``is_jp(country)`` guard — US emit only; JP behaviour unchanged.

  Race and ethnicity source ``PatientProfile.race`` /
  ``PatientProfile.ethnicity`` (already sampled by
  ``patient.activator`` from US ``demographics.yaml``
  ``race_distribution`` / ``ethnicity_distribution``), translated to
  the OMB code+display pairs on the CDC race+ethnicity CodeSystem
  (``urn:oid:2.16.840.1.113883.6.238``). Birthsex maps
  ``PatientProfile.sex`` → ``M`` / ``F`` on the us-core-birthsex slot.
  Unknown / unmapped slugs are omitted rather than fabricated
  (feedback_empty_vs_wrong_assertion) — newborn / pediatric records
  where the race sampler has not fired still get birthsex but no
  race / ethnicity.

  Verification (p=200 s=356 US): 123/125 adults carry race +
  ethnicity, 125/125 carry birthsex. Adult race distribution
  approximates US Census 2020 (White 56 %, Black 13 %, Asian 6 %,
  Native American 2 %, Other 22 % — the "Other" over-share is a
  yaml-tuning follow-up); Hispanic ethnicity 18.4 % matches Census
  18.7 %. FHIR-emit-only change: CIF byte-unchanged; PATCH under the
  CIF-narrative consistency policy.
- **Demographic contraindication gate for ED medication dispatch**
  (Issues #1316, #1328 — CATASTROPHIC pediatric aspirin/NTG +
  Tamsulosin sex/age mismatch). New
  `clinosim.modules.drug_safety.check_demographic_gate` and
  `reference_data/demographic_gates.yaml` catalog block a drug from
  emitting when the patient's age / sex disqualifies them (with
  ICD-10 prefix exceptions — Aspirin still allowed for pediatric
  Kawasaki M30.3 / acute rheumatic fever I00-I02). Wired into the
  ED encounter treatment dispatcher (`clinosim/simulator/emergency.py`)
  ahead of Order creation; blocked candidates are recorded in
  `patient.safety_skip_log` with the matching rule id and the
  patient age/sex that triggered the skip.

  Seeded rules:
  - `aspirin-pediatric-reyes` — Aspirin blocked below age 16 (Reye's
    syndrome risk), bypassed for M30.3 / I00 / I01 / I02.
  - `nitroglycerin-adult-only` — Nitroglycerin blocked below age 18
    (no routine pediatric indication).
  - `tamsulosin-adult-male-bph` — Tamsulosin blocked outside adult
    male (BPH-only, no pediatric / female indication).

  p=200 s=356 US + JP verification: pediatric Aspirin, pediatric NTG,
  pediatric Tamsulosin, female Tamsulosin all drop from cohort-level
  presence to 0 while adult Aspirin (US 27 / JP 21) and adult-male
  Tamsulosin (US 26 / JP 45) remain intact. RNG cascade is confined
  to the affected pediatric / non-BPH cohorts (adult-male behaviour
  is byte-identical); classified MINOR under the CIF-consistency
  policy for those cohorts.

- **Cesarean full intraoperative medication bundle**
  (#1285 sub-scope → PR). Extends the Cefazolin-only surgical
  prophylaxis added earlier to the full ACOG / ASA / ERAS
  cesarean intraop stack — every C-section mother record now
  carries six MedicationRequest Orders anchored to real ACOG
  timing intervals:
  - Cefazolin 2 g IV, 30 min preop (SCIP-INF-1)
  - Bupivacaine 0.5 % 12 mg intrathecal at incision (spinal
    anesthesia)
  - Fentanyl 25 mcg intrathecal at incision (opioid adjunct)
  - Ondansetron 4 mg IV at incision (antiemetic prophylaxis
    against spinal-induced hypotension)
  - Oxytocin 10 U IV bolus at cord clamp / +10 min (uterotonic,
    PPH prevention)
  - Ketorolac 30 mg IV at +60 min (postop multimodal analgesia,
    ERAS pathway)
  Drug catalog registrations landed alongside:
  - `rxnorm.yaml` gains RxCUIs 7824 (oxytocin), 1815 (bupivacaine),
    26225 (ondansetron), 35827 (ketorolac). All verified via
    tx.fhir.org $lookup on 2026-09-12.
  - `hot7.yaml` gains JP class-representative 7-digit codes
    2499401 (子宮収縮薬), 1214402 (局所麻酔剤). Also backfills
    display entries for 1149029 (Ketorolac) and 2391003
    (Ondansetron) — both were already referenced from
    `code_mapping_drug.yaml (JP)` but had no hot7 display, so the
    fallback lookup returned the bare code.
  - `locale/us/code_mapping_drug.yaml` + `locale/jp/code_mapping_drug.yaml`
    gain the missing intraop-drug entries.
  Determinism: fixed dose + timing anchors relative to `visit_date`;
  no RNG consumption. **PATCH-scope**: additive MedicationRequests
  on the C-section mother path only; no other emit path touched;
  no CIF change.
- **SSRI drug code registration (Sertraline / Escitalopram /
  Fluoxetine / Paroxetine / Citalopram)** (#1281 follow-up → PR).
  The chronic-med SSRI block wired for F32 / F33 / F41.1 in #1281
  used the internal drug names above, but none were registered in
  `codes/data/rxnorm.yaml` or the
  `locale/{us,jp}/code_mapping_drug.yaml` files, so the FHIR emit
  path rendered `MedicationRequest.medicationCodeableConcept.text`
  only. Now:
  - US: RxCUIs 36437 / 321988 / 4493 / 32937 / 2556 registered
    (all TTY=IN, verified against `tx.fhir.org` `$lookup` on
    2026-09-12).
  - JP: YJ 7-digit class codes 1179044 / 1179052 / 1179040 added
    for the PMDA-approved subset (Sertraline / Escitalopram /
    Paroxetine). Fluoxetine + Citalopram are NOT PMDA-approved in
    Japan; a JP-side lookup returns nothing for them and the emit
    falls back to text-only for those particular draws.
  - Regression guard: verified-code drift test + PMDA-omit
    invariant (`tests/unit/test_ssri_drug_code_registration_1281.py`).
  **PATCH-scope**: additive drug catalogue entries; no CIF change;
  no new RNG draws. Pairs with the #1281 chronic-med addition to
  make antidepressant MedicationRequest emission fully coded.
- **SNOMED coding for Order-derived clinical Procedures**
  (#1282 Sub-B → PR). The Order → Procedure emit path in
  `output/fhir_r4/lib/inline_bb.py` previously emitted
  `Procedure.code` with `text` only and an EMPTY `coding` array —
  36 % of all Procedure rows at p=10k s=354 (Issue #1282). New
  crosswalk `output/fhir_r4/procedures/procedure_name_snomed.yaml`
  maps free-text `Order.display_name` substrings to verified SNOMED
  CT codes: hemodialysis (302497006), CRRT / hemofiltration
  (233581009), ECMO (233573008), CPAP / BiPAP (47545007), wound
  care (225358003), timed urine collection (225113003), triage
  (225390008), oxygen therapy (57485005). First-match-wins
  ordering ensures the specific pattern beats a broader family
  match (e.g. `CRRT` beats `hemodialysis` when both keywords
  appear in the same display). Every SNOMED code is verified
  against `tx.fhir.org` `$lookup` — the regression suite includes
  a guard that fails on drift to an unverified code. Unmatched
  displays fall through to text-only (pre-#1282 behaviour). ED
  triage / admission-staging design decision (keep as
  `Procedure` vs move to `Encounter.classHistory`) is a separate
  follow-up. **PATCH-scope**: additive `code.coding` on matched
  Order-derived Procedures; no other emit path touched; no CIF
  change; no new RNG draws.
- **Cancer chronic follow-up routes to Oncology (`腫瘍内科`)**
  (#1280 Sub-A → PR). Pre-fix every C-chapter cancer chronic follow-
  up visit fell through the specialty dispatcher to
  `internal_medicine`, so p=10k s=354 audit patients carrying only
  C67 bladder / C22 liver / C71 brain (etc.) had every quarterly
  surveillance visit routed to `内科` / Primary Care rather than
  `腫瘍内科` / Oncology — matching the "cancer without oncology
  footprint" observation. Fix adds an `oncology` service line to
  `hospital_operations.yaml::available_departments`, maps every
  C-chapter code the sim emits (C15 esophageal, C16 gastric, C18
  colon, C22 hepatocellular, C25 pancreatic, C34 lung, C50 breast,
  C61 prostate, C67 bladder, C71 brain) to the `oncology` specialty
  in `_CHRONIC_DISEASE_SPECIALTY`, and rolls the granular sub-lines
  (`oncology_infusion`, `radiation_oncology`, `medical_oncology`,
  `hematology_oncology`) to the same bucket at hospitals that offer
  the general service. Small clinics that don't (`hospital_small.yaml`)
  keep the internal_medicine fallback via the existing rollup
  branch. Regression guard confirms both hospital shapes. **PATCH-
  scope**: FHIR-emit-only labeling change on the Encounter's
  serviceType / department; no CIF change, no new RNG draws. The
  broader #1280 scope (regimen probability tuning + regimen
  expansion for C15/C16/C22/C25/C67/C71 + cancer surgery emit) is
  deferred to follow-up PRs needing oncology clinical review.
- **Pregnancy complications sampling (O14 / O24 / O42 / O60 / O64)**
  (#1285 Sub-A → PR). Pre-fix every one of the ~185 US pregnancies
  at p=10k s=354 emitted no O-chapter complication code — the only
  O-codes present were O03 / O04 (abortion) and O80 / O82 (delivery
  mode). Real US obstetric care carries a complication code on
  20-40 % of pregnancies. `_pregnancy_lifecycle_events` now samples
  five independent Bernoulli complications at conception (rates
  targeting CDC / ACOG mid-band values: 5 % preeclampsia, 6 % GDM,
  5 % PROM, 10 % preterm labor, 4 % malposition) from
  `perinatal.yaml::complications.bernoulli_draws`, storing the hit
  codes on the pregnancy `TemporalStatePeriod.metadata`. At delivery
  time `simulator/perinatal.py::simulate_delivery_encounter` reads
  the complications back and surfaces them via
  `ClinicalDiagnosis.working_diagnoses` +
  `ConditionEvent.ground_truth_diseases`, so the FHIR emit path
  renders each as a secondary Condition attached to the delivery
  encounter. Draws use the existing per-mother-year
  `perinatal_delivery_seed` sub-RNG (isolated from the calendar
  master RNG — non-perinatal patients' streams are byte-neutral).
  Aborted pregnancies skip the sampler by construction. **MINOR-scope**:
  additive CIF `chronic_conditions`-like data on the pregnancy
  cohort; re-narrate suggested for pregnant patients.
- **Antidepressant chronic-med derivation for F32 / F33 / F41.1**
  (#1281 → PR, META #1137 axis 1). The chronic-medications
  dispatcher had no entries for the mental-health ICD codes, so
  every F32 (depressive episode) and F33 (recurrent depressive
  disorder) patient received zero antidepressants despite the
  diagnosis being planted on `chronic_conditions` (p=10k s=354:
  683 US and 369 JP diagnosed, 100 % untreated). Other chronic
  conditions (HTN → Amlodipine, T2DM → Metformin, dyslip →
  Atorvastatin, COPD → Tiotropium) already had generators in
  `chronic_medications.yaml`. Fix adds F32, F33, F41.1 entries with
  mutually-exclusive `ssri` class (Sertraline / Escitalopram /
  Fluoxetine / Paroxetine) at APA / VA-DoD first-line coverage
  (~65-75 % SSRI for depression, ~60 % for anxiety — matches SAMHSA
  per-diagnosis treatment rates for insured adults). Per META
  #1137's own sequencing note ("immediate work can land as minimal
  in-place YAML changes; module split comes when content
  accumulates"), the change lands as a YAML addition rather than a
  new `mental_health/` module — the SSRI generator uses the exact
  same infrastructure every other chronic condition already uses.
  Follow-up: register SSRIs in `codes/data/rxnorm.yaml` +
  `locale/{us,jp}/code_mapping_drug.yaml` so
  `MedicationRequest.medicationCodeableConcept.coding` populates
  (currently the emit path renders `.text` only until codes land).
  **MINOR-scope**: adds `MedicationRequest` rows for the F32/F33/F41.1
  cohort; re-narrate suggested for depressed and GAD patients.
- **Cesarean surgical antimicrobial prophylaxis (Cefazolin 2 g IV)**
  (#1285 (partial) → PR). ACOG mandates a preoperative single dose
  of Cefazolin 2 g IV within 60 minutes before skin incision for
  every cesarean delivery — this is SCIP-INF-1, a tracked inpatient
  quality measure with real-world US compliance > 95 %. Pre-fix the
  37 US C-sections at p=10k s=354 emitted zero Cefazolin
  MedicationRequests. `simulator/perinatal.py` now attaches a single
  Cefazolin `Order` (2 g IV single-dose, `ordered_datetime` set to
  30 min before delivery) to every C-section mother record. Full
  obstetric intraop bundle (Oxytocin, Bupivacaine spinal, Fentanyl,
  Ondansetron, Ketorolac) and pregnancy complications sampling
  (O10-O99) are deferred to a follow-up that first registers the
  missing drugs in `codes/data/rxnorm.yaml` +
  `locale/{us,jp}/code_mapping_drug.yaml`. **PATCH-scope**:
  additive MR on C-section deliveries only; no other emit path
  touched; deterministic via existing `_newborn_sub_seed`.
- **US maternal Tdap (CVX 115) during pregnancy (ACIP 27-36 weeks)**
  (#1283 → PR). ACIP recommends one Tdap dose per pregnancy at
  27-36 weeks gestation to boost maternal antibodies for the
  newborn's passive pertussis protection. Pre-fix the sim did not
  model this at all — every US Z34-carrying patient's Immunization
  stream was Tdap-free inside their pregnancy interval (0/185
  pregnancies covered at p=10k s=354). New
  `generate_pregnancy_tdap` in
  `clinosim.modules.immunization.engine` walks
  `patient.state_periods` (the pregnancy-lifecycle records META #957
  Incr 1 already emits) and, for each non-aborted period whose
  27-36-week window overlaps the sim, emits a Tdap `Immunization`
  at ~78 % coverage plus a small `not-done` share for realism. The
  enricher pass appends these to the schedule-driven list before
  sort/align. Locale-gated to US (JP has no equivalent universal
  maternal pertussis-booster policy). Uses the same per-patient
  sub-RNG as the schedule pass, so draws are deterministic per
  (patient, seed) and don't cascade into unrelated modules.
  **MINOR-scope**: adds Immunization rows for the US pregnant
  cohort; re-narrate suggested for those patients.
- **US pediatric ACIP primary immunization series wired**
  (#1279 → PR). `clinosim/locale/us/immunization_schedule.yaml`
  shipped only adult vaccines (influenza / covid19 / ppsv23 /
  tdap / zoster_rzv), so at p=10k s=354 every US patient age 0-17
  (n=1 286) received zero Immunization records — inverse of the
  ~90 % NIS-Child real-world coverage and inconsistent with the
  JP locale (JP peds average 15-17 imms/patient). Fix adds ten
  `pediatric_series` entries in the US schedule for the ACIP
  primary + adolescent series: HepB (birth / 1mo / 6-18mo),
  DTaP (2/4/6/15-18mo/4-6y), IPV (2/4/6-18mo/4-6y), Hib (2/4/6/12-15mo),
  PCV13 (2/4/6/12-15mo), Rotavirus (RotaTeq 2/4/6mo), MMR
  (12-15mo/4-6y), Varicella (12-15mo/4-6y), annual influenza
  from 6 months, adolescent Tdap booster (11-13y). Coverage
  numbers target NIS-Child 2023 completion rates. CVX `10` (IPV)
  registered in `codes/data/cvx.yaml` (verified against CDC IIS
  CVX list). HPV / MenACWY / Hep A / MenB deferred to a follow-up
  (need additional CVX registrations). **MINOR-scope**: the fix
  changes CIF Immunization coverage for pediatric patients (0
  → primary series) and, as a natural side effect, retrospectively
  emits pediatric-window vaccines for adults born after each
  vaccine's `available_from` (e.g., 45yo adults now carry childhood
  MMR record). RNG cascade limited to Immunization emit; unrelated
  modules unaffected. A `narrate` refresh is required for pediatric
  narrative-CIF documents.

### Fixed

- **Pediatric Enoxaparin VTE prophylaxis auto-issued at adult 40 mg**
  (#1276 → PR). `clinosim.modules.prophylaxis` fires the generic
  DVT rule (Enoxaparin 40 mg SC daily) on any inpatient encounter
  ≥ 48 h regardless of patient age. p=10k s=354 audit surfaced
  13 pediatric MRs (US 8 / JP 5) at the adult-flat 40 mg dose, none
  for a positive pediatric VTE-prophylaxis indication (e.g., asthma
  admission in a 9-year-old — not indicated by AAP / CHEST 2019
  guidelines). Both problems compound: an inappropriate indication
  at an unsafe dose. Fix adds a `pediatric_age_gate` skip condition
  (default `pediatric_age_ceiling: 15`) evaluated ahead of the
  other rules in `should_skip_dvt_prophylaxis`. Pediatric patients
  under the ceiling never receive the generic Enoxaparin order;
  positive-indication detection (ortho surgery, ICU immobilization,
  Kawasaki disease) + weight-based dosing (0.5-1 mg/kg SC q12h) is
  deferred to the pediatric-care module (META #1137). **PATCH-scope**:
  yaml-configurable, deterministic (no RNG), FHIR emit path
  unchanged apart from the removed inappropriate rows.
- **Pediatric BMI-derived E66 Condition emit uses adult thresholds**
  (#1284 → PR). The E66 dispatch block in
  `clinosim.modules.population.engine` fired the adult BMI thresholds
  (25 / 30 / 40) regardless of age, so a p=10k s=354 audit counted
  881 US pediatric patients (age 0-17) with any E66 code, 52 with
  `E66.01` "Morbid (severe) obesity", and **15 toddlers aged 2-5
  with `E66.01`** — BMI ≥ 40 is physiologically impossible in that
  age band. Adult E66 thresholds are not the correct pediatric coding
  practice; ICD-10-CM pairs pediatric obesity with `Z68.5x`
  BMI-for-age percentiles rather than the E66 cascade. Fix
  age-gates the dispatch at :data:`LEGAL_ADULT_AGE` (=20, the existing
  adult-boundary constant already used for the lifestyle-attribute
  gates in the same loop). Under-20 patients no longer receive
  `E66.01` / `E66.9` / `E66.3` from the BMI-derived path. Adult emit
  is unchanged. Full pediatric coding (Z68.5x + CDC BMI-for-age
  percentile sampling) is deferred to the metabolic/ module (META
  #1137). **PATCH-scope** at the same shape as #1272 — deterministic
  dispatch change to CIF `chronic_conditions` for pediatric only,
  no new RNG draws.
- **Coverage lifecycle not reconciled on patient death** (#1278 → PR).
  `_derive_coverage_status` (Issue #944) flips `Coverage.status` based
  on `period.end` vs the simulation snapshot date, but has no
  visibility into the patient's `deceasedDateTime`. p=10k s=354 audit
  found that of 163 US deceased patients 92 % kept `period.end` past
  DOD and 60 % kept `status="active"` (JP 91 % / 36 % of 219). Real
  payers cancel enrollment at DOD. `_drop_entries_after_death` already
  treats Coverage as start-gated (Issue #1219); the reconciliation
  step now also clamps surviving `period.end` down to DOD and flips
  `status="active"` → `status="cancelled"` (the FHIR R4 value the
  builder already uses for expired FY rows). **PATCH-scope**:
  FHIR-emit-only, no CIF change, RNG-neutral.
- **`_drop_entries_after_snapshot` — nested `Specimen.collection.collectedDateTime`
  bypass** (#1273 → PR). `_snapshot_ts_iter` walked only top-level date
  fields, so a `Specimen` whose collection timestamp landed one level
  deeper at `Specimen.collection.collectedDateTime` silently survived
  the CIF-snapshot cutoff filter — while its sibling `ServiceRequest`
  / `DiagnosticReport` / `Procedure` (all top-level date fields) were
  correctly dropped. Result: orphan `Specimen` rows with no
  matching request/report/procedure. Surfaced during the fresh
  p=10k s=352 acceptance verify on JP: 1 newborn metabolic-screen
  Specimen (`spec-54d2dce97809`, `collectedDateTime = 2026-09-15` past
  the 2026-09-12 sim end) had no sibling SR/DR/Procedure. Fix walks
  `Specimen.collection.collectedDateTime` and the FHIR-valid
  alternative shape `Specimen.collection.collectedPeriod.start` — the
  latter following the same `Period.start` policy the docstring
  already applied to other nested Period fields. Deliberately scoped
  to `Specimen` (the only R4 resource with a nested date-of-event); a
  generic recursive dict walk would over-filter (see the docstring's
  note on `Period.start` policy vs. projected-end policy for ongoing
  infusions). Verified end-to-end at s=352 p=10 000 JP: metabolic
  Specimen count now 69 (matches SR/DR/Procedure), total
  `Specimen.ndjson` down 49 rows (other past-snapshot Specimens also
  correctly caught). **PATCH-scope**: FHIR-emit filter granularity;
  no CIF change; RNG-neutral; sibling `_drop_entries_after_death`
  benefits from the same iterator improvement.

### Added

- **BMI-derived `E66.3` (Overweight, BMI 25-29.9) Condition emit**
  (#1272 → PR). Completes the 3-band ICD-10-CM E66 dispatch declared
  by #1126 (Issue #1137 metabolic-cluster scope). Pre-#1272 the BMI-
  derived Condition insertion block in
  `clinosim.modules.population.engine` had only two branches (E66.9
  for BMI ≥ 30, E66.01 for BMI ≥ 40), so patients in the overweight
  band (BMI 25-29.9 — ~30 % of US adults, ~20 % of JP adults) had no
  ICD Condition emitted at all. Downstream analytics keying on `E66.3`
  saw an empty cohort even though the BMI Observation itself was
  correctly emitted. Fix adds the missing `elif bmi >=
  BMI_OVERWEIGHT_THRESHOLD` branch (deterministic, RNG-neutral —
  same shape as the existing two branches) and registers `E66.3
  Overweight / 過体重` in `codes/data/icd-10-cm.yaml`. Verified
  end-to-end at s=352 p=1 000: US `E66.3=180 / E66.9=269 / E66.01=27`
  (was `0 / 269 / 27`); JP `E66.3=125 / E66.9=13` (was `0 / 13`).
  CIF `chronic_conditions` gains an `E66.3` entry for BMI 25-29.9
  patients — existing narrative-CIF files that reference
  `chronic_conditions` on these patients need a fresh `narrate` run
  to surface the new code (same class as #1251, #1126).

- **Newborn metabolic screen full FHIR shape** (#1252 sub-scope N6b →
  PR). The N6 slice emitted only a `Procedure` for the heel-stick event;
  downstream consumers querying `ServiceRequest.ndjson`,
  `Specimen.ndjson`, or `DiagnosticReport.ndjson` for a newborn screening
  panel saw nothing. N6b adds the three sibling resources so the
  diagnostic-workflow evidence a real EHR produces (order → specimen →
  aggregate report) is emitted alongside the physical-event Procedure:
    - `ServiceRequest` — LOINC 54089-8 "Newborn screening panel", SNOMED
      108252007 laboratory-procedure category, `status=completed /
      intent=order`, `authoredOn=admission` + `occurrenceDateTime=heel-
      stick`. `subject` + `encounter` refs to the newborn's Patient +
      birth admission.
    - `Specimen` — SNOMED 122554006 "Capillary blood specimen"
      (tx.fhir.org $lookup-verified 2026-09-11), `status=available`,
      `collection.collectedDateTime=heel-stick timestamp`, body-site +
      collection-method emitted as text only (no SNOMED coding — the
      repo's verified-code rule forbids fabricating unverified
      terminology bindings; verified heel / heel-stick codes are not on
      the tx-server used elsewhere in this codebase).
    - `DiagnosticReport` — LOINC 54089-8, HL7 v2-0074 "LAB" category,
      `status=final`, `basedOn → SR`, `specimen → Specimen`,
      `conclusionCode` carries the SNOMED pass / refer outcome from the
      shared sub-seed. The per-analyte `.result[]` is a follow-up scope
      (N6c); this MVP slice ships the overall verdict + workflow shape.
  All four resources (SR + Specimen + DR + Procedure) share the same
  sub-seed keyed on `patient_id`, so `DR.conclusionCode` and
  `Procedure.outcome.coding` are guaranteed byte-identical. Cross-ref IDs
  (`DR.basedOn → SR.id`, `DR.specimen → Specimen.id`) derived
  deterministically from `patient_id`. New per-locale yaml block under
  `newborn_screening.yaml::metabolic_screen.{service_request, specimen,
  diagnostic_report}` (all shared across JP / US; text-only body-site +
  method are locale-branched EN / JA). Verified end-to-end at s=351
  p=500: US 6/6 babies (6 SR + 6 Specimen + 6 DR + 6 Procedure), JP 3/3
  (3 SR + 3 Specimen + 3 DR + 3 Procedure); all cross-refs and verdict
  invariants held 100 %. **PATCH-scope**: additive FHIR emit + new
  `extensions["newborn"]["metabolic_screen"]` slot (parallel to the
  existing bilirubin / cchd_pulse_ox slots which shipped as PATCH);
  narrative CIF does not reference these resources; RNG unchanged (the
  sub-seed was already sampled by `build_metabolic_screen_procedure` in
  N6, and the new helper recomputes from the identical seed key
  deterministically).

### Fixed

- **Newborn metabolic screen: US schedule_day mismatch** (#1263 → PR).
  `build_metabolic_screen_procedure` used a single shared `schedule_day: 4`
  slot — JP-appropriate (before a 5-day discharge), but past the 2-day US
  birth-admission LOS, so the defensive discharge gate silently skipped
  the tandem-MS `Procedure` emission for every US well-newborn. Empirical
  gap at s=351 p=10k: JP 85/86 (99 %) vs **US 43/125 (34 %)** — 82
  US babies were missing the single most-important neonatal screening
  event. `newborn_screening.yaml::metabolic_screen.schedule_day` is now a
  per-locale dict (`jp: 4`, `us: 1` — heel-stick day 1, 24 h post-birth,
  per AAP Guidelines for Perinatal Care 8th ed. / US EHDI Act universal-
  screening cohort). SNOMED procedure code + category + pass/refer
  distribution remain locale-invariant. Verified end-to-end at s=351
  p=500: US 6/6 (100 %) offset ≈ 0.99 d; JP 3/3 (100 %) offset ≈ 3.98 d.
  **PATCH-scope**: additive US Procedure emission (screen was silently
  absent, no consumer was reading it); JP behavior unchanged; RNG
  independent (sub-seed keyed on `patient_id`).

- **US newborn MedicationAdministration.text truncated to first token**
  (#1264 → PR). The FHIR MedAdmin resolver runs a longest-prefix match of
  the CIF `drug_name` against `code_mapping_drug.yaml`; on a US catalog
  miss `base_name` stays at `.split(" ")[0]`, so US newborn drugs shipped
  useless single-word `.text`:
  `"Vitamin K1 (phytonadione) 1 mg IM"` → **`"Vitamin"`** (indistinguishable
  from adult Vitamin D supplement), and `"Erythromycin 0.5% ophthalmic
  ointment (Ilotycin)"` → **`"Erythromycin"`** (indistinguishable from
  systemic erythromycin antibiotic). Fixed by adding two multi-word
  catalog keys (`"Vitamin K1 (phytonadione)"` and `"Erythromycin 0.5%
  ophthalmic ointment"`) — the resolver's longest-prefix match now lands
  on the clean drug identifier and populates `.coding` with the
  authoritative RxNorm SCD (312424 = "0.5 ML vitamin K1 2 MG/ML Injection"
  and 310149 = "erythromycin 0.005 MG/MG Ophthalmic Ointment"). **Both
  RxCUIs verified 2026-09-11 via NLM RxNav `/REST/rxcui/<cui>.json`
  (TTY=SCD).** The RxCUIs `977786` and `313418` previously declared in
  `newborn_screening.yaml` at #1256 / #1262 were fabricated (`{"idGroup":
  {}}` on RxNav lookup — no such concepts exist in RxNorm) and are
  replaced with the verified ones here; they were never actually reached
  by the FHIR emit path (the resolver reads the US drug catalog, not the
  yaml `rxnorm_code` field), so the correction is emit-invisible.
  Verified end-to-end at s=351 p=500: US 6 babies × 2 MARs = 12 baby MARs,
  100 % emit the clean `.text` + RxNorm coding; JP unchanged
  (`ケイツーシロップ`). **PATCH-scope**: US drug catalog + rxnorm.yaml +
  newborn yaml (rxnorm_code field only, unused by emit) additions; no
  CIF schema change; no CIF byte drift; JP unaffected.

- **OPH (ophthalmic) route missing SNOMED coding on MedicationAdministration**
  (#1265 → PR). `_ROUTE_SNOMED` in `clinosim.modules.output.fhir_r4.lib
  .reference_data` had no entry for `OPH`, so `build_route_concept` fell back
  to `{"text": "OPH"}` with no `coding` for the newborn erythromycin
  ophthalmic prophylaxis (#1252 N7 US). Companion drugs on the same run
  (Vitamin K IM etc.) shipped a proper SNOMED route — only OPH was
  text-only. Fixed by registering `OPH → 54485002` (SNOMED CT "Ophthalmic
  route"). Both invariants held: JP display `点眼` added to `_ROUTE_JA`
  (`_validate_route_maps` keys⊇ guard), and the SNOMED display is a
  registered Synonym (verified 2026-09-11 via `tx.fhir.org/r4/CodeSystem
  /$lookup?system=http://snomed.info/sct&code=54485002` — module=core,
  active, FSN `Ophthalmic route (qualifier value)`). Verified end-to-end
  at s=351 p=500 US: 6/6 baby erythromycin MARs emit `{coding: [{system:
  snomed.info/sct, code: 54485002, display: "Ophthalmic route"}], text:
  "OPH"}`. **PATCH-scope**: FHIR-emit-only; no CIF change; JP unaffected
  (JP branch is a no-op for ophthalmic prophylaxis).

- **US `admission_hp` HPI doubled-space fingerprint** (#1266 → PR).
  `_build_hpi` / `_build_present_illness` / `_build_present_illness_ref`
  emitted `"Patient presented with {ctx.severity} symptoms."` as their
  no-disease-protocol fallback. For records with no graded severity
  (newborn Z38.0 US — Z38.0 is not a graded illness) `ctx.severity`
  was empty, so the raw f-string interpolated `""` and produced the
  doubled-space fingerprint `"Patient presented with  symptoms."` in
  every affected Composition's HPI section. Empirical at s=351 p=10k:
  **256 / 897 US admission_hp (28.5 %)** carried the fingerprint; JP
  cosmetically weaker (`"の症状で受診。"` leading-の) but not on the
  double-space class. Fixed with a symmetric empty-severity guard on
  all three sites: when severity is empty the sentence becomes
  `"Patient presented for evaluation."` (US) / `"受診となった。"` (JP),
  and `_build_present_illness` uses the `... for evaluation and
  admission.` variant. Verified end-to-end at s=351 p=500 US: **0/54
  admission_hp** now carry the doubled-space pattern; baby samples
  emit `"Patient presented for evaluation."`. **PATCH-scope**: narrative
  template-string fallback only; no CIF change; no RNG.

### Added

- **Newborn bilirubin + CCHD SpO2 + US ophthalmic prophylaxis** (#1252 →
  PR, sub-scope N7 — final slice of the newborn workup roadmap).
  * **Transcutaneous bilirubin (TcB) daily monitoring** — one reading
    per birth-admission day (1 / 2 / 3, per `newborn_screening.yaml
    ::bilirubin.schedule_days`), sampled from a normal distribution
    keyed on `patient_id`. Day-3 mean higher than day 1 (physiological
    jaundice peaks day 3-5). LOINC 58941-6, mg/dL (UCUM). New bundle-
    builder `_bb_newborn_bilirubin`.
  * **CCHD pulse-oximetry screening** — Right-hand + foot SpO2 at ≥ 24 h
    post-birth. Well-newborn cohort ~99.9 % pass. LOINC 59408-5 with
    SNOMED `bodySite` (368208006 right upper arm / 22335008 foot) to
    distinguish pre- vs post-ductal readings. New bundle-builder
    `_bb_newborn_cchd_pulse_ox`.
  * **US erythromycin ophthalmic prophylaxis** — 1 cm ribbon each eye
    within 1 h of birth, US CDC-standard for gonococcal ophthalmia
    prevention. JP branch declares `drug_name = ""` and returns no
    MAR entry (not JP standard). RxNorm 313418. Reuses existing
    `MedicationAdministration` emit — no new bundle-builder.
  Verified end-to-end at JP p=500 seed 342 — every baby now emits 3
  bilirubin Observations + 2 CCHD Observations. **PATCH-scope**:
  additive; uses `extensions` dict + existing MAR pipeline; no schema
  change.

- **Newborn tandem-MS metabolic screening** (#1252 → PR, sub-scope N6,
  minimum-viable slice). `clinosim.modules.newborn.engine
  .build_metabolic_screen_procedure` emits a `ProcedureRecord` for the
  heel-stick capillary blood collection event of the neonatal
  metabolic mass-screening (新生児マス・スクリーニング) — day 4 of
  birth admission by default (per `newborn_screening.yaml
  ::metabolic_screen.schedule_day`), SNOMED procedure code 405058008
  (Neonatal screening test), category 103693007 (diagnostic).
  Result outcome sampled from yaml (fresh sub-seed keyed on
  `patient_id`): ~99.7 % pass (SNOMED 385669000) / ~0.3 % refer
  (385671000), matching real cohort detection rates. Skipped when LOS
  is shorter than schedule_day (defensive). Full `ServiceRequest` +
  `Specimen` + `DiagnosticReport` per-analyte results are deferred to
  a follow-up scope — this PR emits the Procedure alone so consumers
  see evidence "screening happened with outcome X". Appended to
  `record.procedures` — flows through the existing `_bb_procedures`
  bundle-builder. **PATCH-scope**: additive; no schema change.

- **Newborn AABR hearing screen** (#1252 → PR, sub-scope N5).
  `clinosim.modules.newborn.engine.build_hearing_screen_procedure` emits
  a `ProcedureRecord` for the automated auditory brainstem response
  (AABR) hearing screen — scheduled 24 h into the birth admission
  (`newborn_screening.yaml::hearing_screen`), SNOMED procedure code
  232717001 (AABR screening test), category 103693007 (diagnostic).
  Result sampled from the yaml distribution using a fresh sub-seed keyed
  on `patient_id`: ~97 % pass (outcome 385669000) / ~3 % refer (385671000),
  matching AAP JCIH 2019 well-newborn cohort rates. Appended to
  `record.procedures` — flows through the existing `_bb_procedures`
  bundle-builder to emit a FHIR `Procedure` resource with correct SNOMED
  code + outcome. Skipped if the screen would land past discharge
  (defensive gate for LOS < 24 h). Verified end-to-end at JP p=500 seed
  342. **PATCH-scope**: additive; leverages existing `record.procedures`
  emit pipeline; no schema change.

- **Newborn Apgar score at 1 min / 5 min** (#1252 → PR, sub-scope N4).
  `clinosim.modules.newborn.engine.build_apgar_scores` samples from the
  distribution in `newborn_screening.yaml::apgar.minute_{1,5}_score_weights`
  (well-newborn cohort per AAP / MHLW 出生調査 — 1-min median 8, 5-min
  median 9) using a fresh sub-seed keyed on `patient_id`. Stored under
  `record.extensions["newborn"]["apgar"]`. New FHIR bundle-builder
  `_bb_newborn_apgar` (in `clinosim/modules/newborn/fhir_emit.py`,
  registered next to `_bb_anthropometrics`) renders LOINC 9271-8 (1 min)
  and 9274-2 (5 min) `Observation` resources with UCUM `{score}`
  valueQuantity and survey category. Verified end-to-end at JP p=500
  seed 342: every baby emits 2 Apgar Observations, 5-min mean > 1-min
  mean (matches real cohort transition physiology). **PATCH-scope**:
  additive; no CIF schema change (uses the pre-existing `extensions`
  dict); narrative CIF unchanged.

### Added

- **Newborn shift-cadence vital signs** (#1252 → PR, sub-scope N3). The
  observation module's vitals engine is disease-anchored (needs a
  `physiological_states` trajectory to perturb `baseline_vitals`); healthy
  Z38.0 newborns have no such trajectory, so the vitals emit was silent
  and every newborn shipped with zero timestamped vital signs across the
  birth admission — no heart rate, temperature, respiratory rate, SpO2,
  or blood pressure entries. `clinosim.modules.newborn.engine` now emits
  a shift-cadence `VitalSignRecord` series: 1 at admission + one per
  shift boundary (night 00:00 / day 08:00 / evening 16:00, per
  `newborn_screening.yaml::shift_vitals`) across the birth-admission LOS,
  using the neonatal `baseline_vitals` seeded by N1. Deterministic; no
  RNG. Verified end-to-end at JP p=500 seed 342: every baby now emits
  16 vital sets (5-day JP LOS × 3 shifts + 1 arrival) → FHIR renders 64
  vital-signs Observations per BABY cohort across all LOINCs (HR 8867-4,
  T 8310-5, RR 9279-1, SpO2 2708-6, blood-pressure panel 85354-9, level
  of consciousness 80288-4) — every axis was 0 pre-N3. **PATCH-scope**:
  additive; no schema change; narrative CIF was never using these entries.

### Fixed

- **Newborn `baseline_vitals` + occupation are age-appropriate** (#1252 → PR,
  sub-scope N1). `_build_newborn_patient` inherited the `PatientProfile`
  defaults (`BaselineVitals` HR 72 / BP 120/75 / RR 16 — adult values;
  `occupation="other"`), producing clinically implausible reference
  vitals on every baby and a nonsensical FHIR US Core Patient Occupation
  observation "その他 / Other occupation" on every 0-day-old. Now seeded from
  `perinatal.yaml::newborn` — HR 130 / BP 68/40 / RR 40 / T 36.7 / SpO2 97
  (term-newborn medians per AHA / Nelson Pediatrics 21st ed. + JP MHLW
  母子保健統計), and occupation `"infant"` (乳児 / Infant, aligned with the
  framework's Issue #360 G7 developmental-stage labels). PATCH-scope:
  patient-attribute defaults; no CIF schema change; narrative CIF was
  never using the previous adult values.

### Added

- **`clinosim/modules/newborn/` — birth-admission clinical workup** (#1252 → PR,
  sub-scope N2). New module that fills the gap between `simulator/perinatal.py`
  (owns Encounter + Patient shells) and `clinosim.modules.pediatric`
  (post-discharge well-child scope). Fires only on records whose
  `condition_event.condition_type == "newborn_birth"`; non-newborn records are
  a no-op. First slice ships Vitamin K prophylaxis (`MedicationAdministration`):
  JP Konakion oral 2 mg × 2 doses (day 0 within 24 h, day 7 before discharge —
  per MHLW 新生児 ビタミン K 欠乏性出血症予防, 2011 改訂), US Vitamin K1 1 mg
  IM × 1 dose (within 6 h of birth — per AAP Guidelines for Perinatal Care 8th
  ed.). Config-driven from `newborn_screening.yaml`; deterministic (no RNG).
  Enricher registered as POST_ENCOUNTER order 92 — after every encounter-level
  enricher populates its own data, before the document enricher (95) so
  downstream narratives that reference Vitamin K administration find the MAR
  entry in place. Verified end-to-end at JP p=500 seed 342: every baby now
  emits 1 Vitamin K MAR (day 0). Follow-up sub-scopes N3–N7 stack Apgar,
  hearing screen, metabolic screen, bilirubin monitoring, CCHD SpO2 screen,
  and (US) ophthalmic prophylaxis in the same module seam. **PATCH-scope**
  (additive CIF field, no schema change; narrative CIF still valid — the new
  MAR entries were absent before, so no consumer was reading them yet).

### Fixed

- **Newborn Patient.contact inherits guardian (mother) info** (#1246 → PR).
  `_build_newborn_patient` previously emitted an empty `ContactInfo`, so
  every newborn shipped without any FHIR `Patient.contact[]` entry —
  downstream chart / appointment / emergency-contact pipelines had no
  route to reach any responsible adult. Now the newborn's
  `ContactInfo.emergency_contact_*` carries the mother's name +
  preferred phone (`phone_mobile` fallback to `phone_home`) with
  `relationship = "MTH"`; the shared household landline is copied to
  the baby's own `phone_home`; the personal telecom (mobile / email)
  stays empty because a real newborn cannot be reached directly.
  Verified end-to-end at JP p=500 seed 342 — every baby now emits
  `Patient.contact[0]` with the mother's telecom.
  **PATCH-scope**: FHIR-Patient emit only.

- **Newborn given-name registration window** (#1247 → PR). `_build_newborn_patient`
  in `clinosim/simulator/perinatal.py` unconditionally emitted `given_name=""`
  for every newborn, so babies remained nameless in the CIF and FHIR output
  even months after birth. Now models JP 戸籍法 §49 (14-day birth-registration
  window): given name stays empty for the first 14 days after delivery and is
  sampled from the locale name pool afterwards using a fresh sub-seed keyed on
  the newborn's patient id (RNG-neutral against every other draw). Family
  name inheritance from the mother is unchanged. **PATCH-scope**: FHIR-Patient
  emit only; CIF-narrative that historically ignored the empty given name is
  unaffected (baby narratives already use "新生児" placeholders).

- **Pediatric immunization series: dose-gap silent-fabrication** (#1248 → PR).
  `generate_immunizations` drew each dose in a `pediatric_series` schedule
  entry with an independent coverage roll, so a missed dose 1 (coverage
  fail or "declined" record) did not gate the subsequent doses.
  Downstream: newborn Immunization records with `doseNumber = 2` (or 3)
  present without any `doseNumber = 1` in the record — implying an
  impossible "past vaccination" for a patient born inside the sim window.
  At v0.6.1 JP p=10k this affected 21 % of babies (21 of 99). Now the
  series discontinues on the first missed dose: dose N cannot be
  administered without dose N-1, matching real clinical practice. RNG
  cascade: the new `series_discontinued` gate is checked *before* any
  rng draw, so cross-series RNG for patients whose earlier doses fell
  outside the sim window (the pre-fix skip path) is unchanged — the shift
  is scoped to pediatric-series cohorts. **MINOR-scope** (CIF layer:
  immunization records removed; narrative CIF referencing those records
  needs a re-narrate).

## [0.6.1] - 2026-09-10

**PATCH** — Session 105 wave (14 PRs). Cumulative dangling-FHIR-reference
cleanup, VAX companion encounter follow-through, full JP national YJ
CodeSystem ship, and JP mental-health prevalence config gap fix. Every
change either preserves CIF ↔ narrative-CIF consistency directly (FHIR
emit-only fixes: dangling-ref scrubbers, per-encounter dispatch gates,
`nocoded` slice elimination) or has a narrow scope where a re-`narrate`
against the new structural CIF is a small refresh, not a full rebuild
(F33/F41.1 config addition affects ≲2 % of JP adults; YJ code catalog
replacements swap 16 fictitious codes for real MEDIS-registered codes on
1-2 drugs per patient at most). Version bump from 0.6.0 is PATCH — the
S105 wave delivers audit-driven quality improvements without the
schema-level breaks that trigger a MINOR bump.

### Session 105 (2026-09-08 → 2026-09-10) fixes

#### Fixed (FHIR reference-integrity cascade — dangling refs 2,509 → 0 at p=10k)

- **Composition.section.entry scrubber for post-death drops** (PR
  [#1226](https://github.com/TomoOkuyama/clinosim/pull/1226)). The
  `_drop_entries_after_death` filter (Issue #926) removed post-mortem
  Observation resources but left their references on surviving
  Composition sections. 1,866 dangling refs at JP p=10k in-hospital-
  death cohorts. Added a second-pass scrubber
  (`_scrub_refs_one_pass`) that walks every survivor and drops
  Reference items whose target is in the drop set.
- **MedicationAdministration.request gate on post-dedup MR set** (PR
  [#1225](https://github.com/TomoOkuyama/clinosim/pull/1225)). MR dedup
  (Issue #1177 byte-identical + Issue #1176/#1179 same-class) drops
  duplicate MRs, but the MA builder's dangling-ref gate used the raw
  order set. 357 dangling MA→MR refs. `BundleContext.emitted_mr_ids`
  now threads the actual emitted MR ids through so the gate reflects
  the true post-dedup surface.
- **Encounter after-death allow with start-gated invariant** (PR
  [#1224](https://github.com/TomoOkuyama/clinosim/pull/1224)). 5 IMP
  encounters in p=10k in-hospital-death cohorts were silently dropped
  because `Encounter.period.end` (body-out timestamp) exceeded dod.
  New `_AFTER_DEATH_START_GATED_RESOURCE_TYPES = {Encounter, Coverage,
  CareTeam}` gates on `period.start` only; `period.end` past dod stays
  legitimate. Bogus admission-after-death (`period.start > dod`) still
  drops — Issue #926 invariant preserved.
- **Procedure.reasonReference Z-code visit-reason gate** (PR
  [#1223](https://github.com/TomoOkuyama/clinosim/pull/1223)). Three
  Procedure emit sites (`procedures.py`, `oxygen_therapy.py`,
  `lib/inline_bb.py`) unconditionally emitted `reasonReference` while
  `conditions.py` (Issue #916) skips Condition emit for Z-chapter
  visit-reason codes (Z00.0/Z09/Z12/Z13/Z23/Z25-29/Z71/Z76). 45
  dangling refs. Symmetric `is_visit_reason_zcode` gate at all three
  Procedure emit sites.
- **Procedure Z-code gate uses per-encounter dx** (PR
  [#1227](https://github.com/TomoOkuyama/clinosim/pull/1227)). Residual
  41 refs from PR #1223 because the gate read record-level dx only;
  companion vax encounters (`ENC-VAX-*`) carry encounter-scoped Z23.
  New `encounter_primary_dx_code(record, encounter_id)` helper prefers
  per-encounter dx.
- **Encounter.diagnosis[] + reasonReference[] scrubber** (PR
  [#1232](https://github.com/TomoOkuyama/clinosim/pull/1232)). PR
  #1226 covered Composition / DR / MR / SR / MA / DocRef but missed
  `Encounter.diagnosis[*].condition.reference` (nested single Reference
  inside a BackboneElement list) and `Encounter.reasonReference[]`. 6
  JP + 1 US dangling in the in-hospital-death case.
- **MR/MA/Procedure.reasonReference scrub** (PR
  [#1236](https://github.com/TomoOkuyama/clinosim/pull/1236)). PR
  #1232 pattern extended to the 3 remaining resource types that also
  carry `reasonReference` lists to Condition. 118 JP + 31 US dangling
  refs closed.

#### Fixed (VAX companion encounter follow-through — Issue #1197 Pass 5+)

- **Per-encounter reasonCode with VAX Z23 stamp + attending physician**
  (PR [#1216](https://github.com/TomoOkuyama/clinosim/pull/1216)). The
  companion vaccination encounter (`ENC-VAX-*`, session 104 PR #1214)
  inherited the record's primary IMP admission dx as its FHIR
  `Encounter.reasonCode` — a burn patient's flu-shot visit was tagged
  T30.0. New `Encounter.admission_diagnosis_code` field on the CIF
  encounter dataclass carries the per-encounter dx; the enricher
  stamps Z23 on the VAX companion; the FHIR encounter builder prefers
  the encounter-scoped code when set, falling back to record-level.
  Same PR adds real attending physician stamping (was
  `Practitioner/UNKNOWN`).
- **VAX narrative dispatch — idempotent document_enricher re-invoke**
  (PR [#1229](https://github.com/TomoOkuyama/clinosim/pull/1229)).
  `document_enricher` runs at POST_ENCOUNTER; `enrich_immunizations`
  runs at POST_RECORDS and appends VAX encounters afterwards, so those
  encounters had no document stub / narrative. The enricher is now
  idempotent (skips encounters with existing docs) and
  `enrich_immunizations` re-invokes it after VAX creation — narrative
  dispatch: 0/1,478 → 1,478/1,478 (100%).
- **Narrative pass binds each stub to its OWN encounter context** (PR
  [#1238](https://github.com/TomoOkuyama/clinosim/pull/1238)). Even
  after PR #1229 delivered VAX stubs, the Stage 2 pass fell back to
  `encounters[0]` (parent IMP) for context, so 5,521 US / 1,387 JP
  VAX narratives ended up with stroke/burn/newborn subjective content.
  `_run_unit` now indexes encounters by id, per-stub `_build_context`
  is cached per encounter, and the written narrative's `encounter_id`
  reflects the stub's own encounter. Also fixes the same latent bug
  for `-ED` synth-bridge encounters.

#### Fixed (JP CodeSystem — 41.8 % NOCODED → 0.5 %)

- **Full JP national YJ CodeSystem shipped as clinosim artifact** (PR
  [#1230](https://github.com/TomoOkuyama/clinosim/pull/1230)). The
  jpfhir-terminology 2.2606.0 CodeSystem ships as `content=fragment`
  (first 2000/25,542 concepts, psychiatric/neurological drugs only),
  causing the emit path to route 41.8 % of MR / 25.1 % of MA to the
  JP-CLINS eCS `nocoded` slice for cardiovascular / respiratory /
  oncology YJ codes. `clinosim/codes/authoritative/JP_MedicationCode
  YJ_CS_full.json` (`content=complete`, 23,923 concepts, MEDIS-
  sourced) replaces the tx-server-fragment dependency; the emit gate
  (`_is_yj_code_valid`) checks against the full CS. Also curates 16
  historical clinosim yj.yaml codes that had been fictitious to real
  MEDIS-registered codes (Diclofenac / Milnacipran / Aminophylline /
  Disopyramide / Carvedilol / Nicardipine / Mannitol / Codeine /
  Mg-sulfate / Vasopressin / Levothyroxine / Adrenaline /
  Norepinephrine / Ferrous-citrate / Ringer's / Alendronate).
  Refresh script: `scripts/refresh_authoritative_yj_full.py`.
- **17 oncology / hormonal / supplement drug codes added to yj.yaml**
  (PR [#1234](https://github.com/TomoOkuyama/clinosim/pull/1234)).
  Oxaliplatin / Fluorouracil / Leucovorin / Capecitabine / Trastuzumab
  / Osimertinib / Pemetrexed / Carboplatin / Sorafenib / Bicalutamide
  / Lenvatinib / Leuprorelin / Tamoxifen / Anastrozole / Folic-acid /
  Cefcapene / ICS+LABA — real MEDIS 2026-08-31 版 codes. English
  drug-name lookups added to `code_mapping_drug.yaml`; fictitious code
  comments in `drug_names_ja.yaml` refreshed. MR NOCODED 3.36 % →
  0.49 %, MA NOCODED 0.97 % → 0.08 %.

#### Fixed (JP demographics + audit metric)

- **JP F33 (recurrent depression) + F41.1 (GAD) chronic prevalence
  config** (PR
  [#1240](https://github.com/TomoOkuyama/clinosim/pull/1240)). US
  `demographics.yaml` declared F33 / F41.1 (session 102 addition) but
  JP mirror was missing — F33 = 0 / F41.1 = 0 at JP p=10k despite F32
  = 297. Added `F33: {40-59: 0.015, 60-99: 0.02}` (~1-2% MHLW
  epidemiology) and `F41.1: {40-59: 0.012, 60-99: 0.015}` (~0.8-1.5%
  JP GAD). Also added F33 / F41.1 to `codes/data/icd-10.yaml` (JP
  code catalog) with canonical JA display so Condition emit resolves
  the display lookup cleanly.
- **AMB counting scope refinement — NAMCS-comparable slice**
  (PR [#1242](https://github.com/TomoOkuyama/clinosim/pull/1242)). The
  audit fork's US "AMB rate 6.29/adult/yr vs NAMCS 3.78" finding was a
  metric-definition mismatch, not code drift — clinosim's total AMB
  legitimately includes companion vax encounters (Issue #1197 Pass 5),
  chemo cycle visits, and post-discharge follow-ups outside NAMCS's
  office-based physician-visit scope. `verify_medical_stats.py` now
  prints `total_amb_per_adult_yr` (broader) alongside
  `namcs_amb_per_adult_yr` (excludes `ENC-VAX-*` / reasonCode Z23) so
  the audit can compare the narrow slice against the NAMCS 3.0-4.5/yr
  band directly.

### Session 105 (2026-09-08 → 2026-09-10) verification

- **JP p=10,000 s=329, window 2025-09-10 → 2026-09-10**: 2,509 → 0
  dangling FHIR references (all 7 scrubber PRs), MR NOCODED 41.8 % →
  0.49 %, MA NOCODED 25.1 % → 0.08 %, 100 % Immunization.encounter
  linkage (in-sim doses), 100 % VAX reasonCode Z23-only (was 73/74
  polluted at Pass 5), 100 % VAX CareTeam attending real Practitioner
  (was 74/74 UNKNOWN), 100 % VAX narrative populated with the correct
  encounter's context (was 1,387 files with parent IMP content).
- **US p=10,000 s=329, same window**: same class of fixes verified —
  100 % Immunization linkage, 100 % VAX reasonCode Z23, 5,521 VAX
  narratives populated with own context, 90.7 % MR
  `expectedSupplyDuration` populate, 100 % `Practitioner.display`
  populate, LOINC 64295-9 / 34895-3 sections emitted, age-cap gates
  hold (mammography>74 = 0, colonoscopy>75 = 0, annual-physical>89
  = 0).

## [0.6.0] - 2026-09-07

**MINOR** — the wave of feature + defect-fix work accumulated across
sessions 97-104 (2026-09-01 → 2026-09-07) is cut as v0.6.0. The
initial v0.6.0 tag was attempted on 2026-08-31 and **un-released the
same day** because META Issues #914 Bucket B / #957 remaining slices
/ #757 remaining mappings were left as follow-up. Sessions 97-104
closed those remaining sub-items and added a substantial further
feature + narrative-quality wave. All CIF ↔ narrative-CIF consistency
invariants required a MINOR bump per the versioning policy: seven of
the 30+ PRs since 0.5.0 are RNG-cascade or CIF-shape changes; a fresh
`narrate` run is required against the new structured CIF.

### Session 104 (2026-09-06 → 2026-09-07) additions

#### Added

- **Patient-profile realism keys for LLM narrative prompts** (PR
  [#1164](https://github.com/TomoOkuyama/clinosim/pull/1164)). Three
  new context keys populated by
  `replacement_strategy._build_extra_context` — `patient_demographics`
  (age / sex / employment / smoking / alcohol / marital / insurance
  anchor), `patient_biometrics` (Ht / Wt / BMI / blood type),
  `health_literacy_tag` (`low` / `medium` / `high` band). Bundle
  prompt v14 → v15 gains new Rule 6 HEALTH-LITERACY TONE consumer.
  SOAP-shaped docs (progress_note / outpatient_soap / ed_note) that
  previously saw only the coarse `patient_bucket` now get exact
  demographics + biometrics; discharge_instructions and
  family_communication tone matches the reader's literacy band.
  RNG-cascade — cache signature widens to include patient profile.
- **Disease-specific nursing content pilot** (PR
  [#1165](https://github.com/TomoOkuyama/clinosim/pull/1165)). New
  `clinosim/modules/document/reference_data/nursing_content.yaml`
  registers 5 acute-disease pilot entries
  (copd_exacerbation / diabetic_ketoacidosis /
  heart_failure_exacerbation / bacterial_pneumonia /
  cerebral_infarction) plus the 6 grandfathered chronic ICD-10
  prefixes. `_build_nursing_diagnosis` / `_build_care_plan` /
  `_build_patient_education` now merge acute-first, chronic-second,
  deduplicated. Pre-104 nursing content was chronic-only — every
  COPD-exacerbation admission produced the same nursing text as any
  other. Post-104, pilot disease admissions surface NANDA-I-grounded,
  disease-specific nursing diagnoses / NIC care actions / patient
  education topics. Byte-diff on non-pilot encounters is zero (the
  chronic axis reproduces the pre-104 hardcoded map verbatim). RNG-
  cascade on pilot-disease encounters (narrative text change).

#### Fixed

- **admission_hp EN Kanji heading leak** (PR
  [#1169](https://github.com/TomoOkuyama/clinosim/pull/1169),
  closes #1167). H100 verify surfaced 4 / 859 US narrative docs
  emitting bare 評価 / 薬物療法 / 検査 Kanji headings inside English
  admission-H&P `assessment_and_plan`. Bundle prompt v15 → v16 splits
  the REQUIRED heading list by locale (target_language=ja →
  【評価】/【薬物療法】/…, target_language=en →
  **Assessment / Medications / Diagnostics / Patient Education /
  Planned Length of Stay**). Non-admission_hp doc types unchanged;
  no RNG effect.
- **JP narrative EN-leak (14 oncology drug names + Rule 5
  descriptors)** (PR
  [#1170](https://github.com/TomoOkuyama/clinosim/pull/1170),
  partially closes #1168). H100 JP verify surfaced ~280 English-
  token leaks that are not Japanese-EHR-common medical acronyms. Two
  root causes:
  - 14 chronic-medication + chemo drugs (Osimertinib / Sorafenib /
    Lenvatinib / Anastrozole / Bicalutamide / Capecitabine /
    Carboplatin / Folic acid / Leucovorin / Leuprorelin / Oxaliplatin
    / Pemetrexed / Tamoxifen / Trastuzumab) had `drug_ja` katakana in
    `chronic_medications.yaml` but no entry in `drug_names_ja.yaml`
    → localizer missed them → EN name leaked to JA output. Added
    them under a new `# --- Oncology / 抗癌剤・分子標的薬 ---`
    section with MHLW YJ / brand annotations.
  - Rule 5 LOCALIZATION Section A pre-104 only covered severity
    (mild/moderate/severe). Verify surfaced 216+ bare
    Stage / Mild / Moderate / persistent / intermittent / Level
    tokens. v15 → v16 Section A now enumerates these + Grade,
    states case-insensitivity, and demonstrates compound severity
    forms ("Mild persistent" → 「軽度持続」).
  Category C leaks (Ice pack application / Elastic bandage wrap /
  Silver sulfadiazine cream / "mg PO daily" / Xray / daily) are
  deferred — mixed CIF-source root causes tracked as #1168 remainder.
- **Progress-note calendar-day filter** (PR
  [#1171](https://github.com/TomoOkuyama/clinosim/pull/1171),
  closes #1166). H100 US verify surfaced a progress-note whose
  Assessment cited "new fever spike to 38.5°C" while the same doc's
  Objective showed T 36.8°C. The 38.5°C reading was real but
  belonged to a different calendar day than the doc was labeled for.
  Root cause: `_filter_vitals_for_day` and 3 sibling per-day filters
  (session-103 lab/med filters) used `(ts - adm_dt).days` — a
  `timedelta.days` floor that buckets sub-daily admission times into
  24-h windows spanning two calendar days. Fix: switch to
  `(ts.date() - adm_dt.date()).days` in all four sites so day_index=N
  = Nth calendar day since admission (matches the
  `hospital_day_label` rendering the LLM sees). Byte-diff on
  encounters admitted late in a calendar day; no RNG effect.

#### Chore

- **dependabot: ruff 0.16.4 → 0.16.5** (PR
  [#1162](https://github.com/TomoOkuyama/clinosim/pull/1162)).
- **Documentation drift sweep** (PR
  [#1163](https://github.com/TomoOkuyama/clinosim/pull/1163)).
  CHANGELOG + AGENTS + module READMEs + docs/architecture updated to
  reflect the session 100-103 wave that had landed on master without
  documentation follow-up. See PR body for the drift punch-list.

### Sessions 100-103 (2026-09-05 → 2026-09-06) additions

### Added (session 103 — natural_death lifecycle end-to-end)

- **New `clinosim.modules.natural_death` enricher module** (C11g).
  Actuarial-driven per-patient mortality sampling replaces the prior
  "everyone survives the simulation window" fiction:
  - **C11g-1 (PR #1147)**: new
    `clinosim/locale/shared/actuarial_life_table.yaml` carrying
    single-year-age qₓ (probability of dying within 1 year given alive
    at age x) tables for US (CDC 2020) and JP (MHLW 2020),
    male / female / total, ages 0–110. Provenance block + citation
    URLs pinned in the yaml.
  - **C11g-2 (PR #1150)**: `NaturalDeathEnricher` samples death within
    the sim window from qₓ using a per-`person_id` sub-RNG (RNG cascade
    isolation, `feedback_rng_neutral_additive_field` pattern). Assigns
    `PersonRecord.death_datetime` when death is drawn; otherwise no-op.
  - **C11g-3a (PR #1152)**: `is_alive_at(t)` gate threaded into the 4
    event dispatchers (calendar, month-loop, healthcare-calendar,
    perinatal) so no encounter is generated for a patient after their
    `death_datetime`.
  - **C11g-3b / 4 / 5 (PR #1153)**: FHIR alignment —
    `Patient.deceasedDateTime` emitted on every dead patient,
    `Patient.active = false` on the same records, US Bundle profile
    kept. Cohort measurement (US p=50k s=325 5-year): 942 / 31,065
    patients (3.03 %); US p=10k s=326 1-year: 191 / 6,177 patients
    (3.09 %); zero encounters starting after death (date-strict).

### Added (session 103 — US insurance Coverage emit, PR #1149)

- **`Coverage` FHIR resource now emitted for US patients** with 9
  synthetic payor categories: Employer-sponsored group plan (~32 %),
  Medicare Part A/B (~14 %), Medicaid (~13 %), Medicare Advantage
  Part C (~9 %), Private individual-market (~9 %), Self-Pay / Uninsured
  (~7 %), CHIP (~7 %), VA / TRICARE / other public (~7 %), dual
  eligible (~3 %). Profile: `us-core-coverage`. Cohort measurement
  US p=10k s=326 1-year: 9,720 Coverage rows on 6,177 patients
  = 1.57 rows/patient (multi-year enrollment periods).
- **JP Coverage** (被用者保険被扶養者 / 被保険者 / 国民健康保険 /
  後期高齢者医療制度) continues to emit as before via the pre-existing
  `--jp-insurance` path; JP p=10k s=326 measurement:
  9,378 / 5,529 = 1.70 rows/patient.

### Added (session 103 — narrative CIF density round-out)

- **PR #1158 (Issue #1154)**: progress-note **per-day filter** for
  `assessment` (abnormal labs) and `plan` (medications) — was reading
  a non-existent `lab.day` / `med.day` field on CIF, so every
  progress-note day cited the same first-6 admission-day labs +
  medications verbatim across an 8-day stay. Two-path day resolution
  now honors explicit `.day` when present, falls back to
  `result_datetime` / `actual_datetime | scheduled_datetime` minus
  `encounter.admission_datetime`. Locale-agnostic (JP + US both
  benefit).
- **PR #1159 (Issue #1156)**: admission H&P EN branch —
  `physical_examination` prepends locale-neutral vitals line
  (`Vital signs: BP …/… mmHg, HR …/min, T …°C, SpO2 …% (RA), RR …/min.`),
  `assessment_and_plan` becomes CIF-derived (chief_complaint +
  working_diagnosis + severity + comorbidities + LOS + initial meds).
  JA branch was already correct; the fix parallels its structure into
  EN.
- **PR #1160 (Issue #1155)**: progress-note SOAP EN branch —
  `subjective` composer added (`Hospital day N. …` + abnormal-flag
  guards); `objective` now uses `_compose_pe_vitals_line`. Prior:
  bare `No special findings` on both slots for every US progress note.
- **PR #1161 (Issue #1157)**: `NarrativeOutput.structured` field
  dropped from serialised on-disk JSON when empty (was 100 % of docs
  carrying an empty `{}` slot; still preserved on the dataclass so
  QUESTIONNAIRE_RESPONSE emit has a clean insertion point).

### Added (session 103 — perinatal + imaging + JP pneumonia band)

- **PR #1146**: perinatal per-year stage counters instrumented for
  the pregnancy lifecycle (conception → prenatal 12/24/36 → delivery →
  postpartum 7d/28d → closed).
- **PR #1148 (Issue #1116)**: `perinatal.yaml::lifecycle.annual_conception_rate`
  recalibrated to CDC pregnancy-rate target (6–8 %). US p=10k
  measurement: 6.40 % conception rate; delivery emit share 3.54 %
  (target 3.5–6.5 %).
- **PR #1151**: `CT_soft_tissue` / `Soft_tissue_US` / `MRI_Lumbar`
  imaging code inference — was falling through to generic Imaging
  stub. Post-fix stub share 19.4 % → 3.2 %; measurement on US p=10k:
  0.0 % (0 / 217 imaging procs).
- **PR #1145 (Issue #1115)**: JP pneumonia `J18` hospital-cohort
  verifier band widened to (4, 14) — reflects Japan's higher
  hospitalisation-for-pneumonia rate in aging catchment cohorts.

### Added (session 102 — US demographics epidemiology bundle)

- **PR #1138 (Issue #1126)**: BMI-derived `E66` obesity `Condition`
  emit — was silently absent from cohort output despite the BMI
  field being present on every patient. Post-fix US p=10k: 49.24 %
  adults (target NHANES 35–50 %).
- **PR #1139 (Issue #1130/#1131/#1136)**: US cancer + dementia +
  osteoporosis prevalence-bump bundle. Post-fix US p=10k: cancer
  6.82 % adults (target 4–8), osteoporosis M81 9.12 % adults
  (target 4–15), dementia 6.84 % 65+ (still under Alzheimer Assoc
  13–33 target; residual gap tracked as session-102 known defer).
- **PR #1140**: chronic prevalence recalibration for depression
  (F32 + F33) + anxiety (F41.1) + young-adult HTN (18–39 band).
  Post-fix US p=10k: depression 11.56 % (10–15), anxiety 2.44 %
  (2–5), HTN 13.55 % (4–15 NHANES).
- **PR #1141 (Issue #1134)**: SDOH-derived Substance Use Conditions —
  `F17.210` (nicotine dependence, uncomplicated) + `F10.20` (alcohol
  dependence, uncomplicated) emitted from the SDOH-linked chronic
  activator. Post-fix US p=10k: tobacco F17 17.87 % adults (HC 10–25),
  alcohol F10 15.10 % (HC 5–15).
- **PR #1142 (Issue #1133)**: US `I21` MI + `I63` stroke incidence
  reduced ~35 % to match AHA benchmark (target 2–5 per 1000
  adult-yr). Post-fix US p=10k: MI 4.30 /kadult-yr, stroke
  6.76 /kadult-yr (broad prefix I63/I64/I61).
- **PR #1144 (Issue #1129)**: engine healthcare-calendar bug — was
  looping only over the `--start` year, not the full `[start_y, end_y]`
  window. Post-fix US p=10k: AMB per adult/yr 6.15 (up from
  the pre-fix 0.81; NAMCS target range clears when de-skewed for
  hospital-cohort catchment).

### Added (session 101 — hospital-cohort target-band verifier + prev calibrations)

- **PR #1121 (Issue #1108)**: US HTN 3-band recalibration into NHANES
  target (young / middle / senior bands independently tuned).
- **PR #1122 (Issue #1109/#1110/#1111)**: `HOSPITAL_COHORT_TARGET`
  dict in `scripts/verify_medical_stats.py` — flags axes where a
  Medicare-user (hospital-catchment) cohort legitimately deviates
  from general-population benchmarks (COPD, DM, dyslipidemia,
  median_age, outpatient_share). Emits `OK-HC` verdict instead of
  `FAIL` for these axes. YAML-side intent is now discoverable via
  the yaml `# Medicare-user cohort target` comment.
- **PR #1123 (Issue #1113)**: US `N18` CKD + `I50` CHF prevalences
  brought into benchmark band.
- **PR #1124 (Issue #1112)**: JP cancer prevalence −30 % into MHLW
  benchmark band.
- **PR #1125 (Issue #1117)**: hospital-cohort bands for `median_age`
  and `outpatient_share` added to the verifier.

### Added (session 100 — pre-release hardening bundle)

- **PR #1094 (Issue #1092)**: past-pregnancy marker `Z37.9` → `Z87.59`
  (Personal history of other specified conditions). Z37 stays on the
  active encounter; Z87.59 becomes the durable personal-history
  marker.
- **PR #1097 (Issue #1090)**: `Observation.code` alias for
  `Total_bilirubin` → `T_Bil` (canonical lab-name registry match).
- **PR #1095 (Issue #1091)**: LDL derivation via Friedewald equation
  when direct LDL absent, coded as LOINC 13457-7 (calculated LDL) to
  distinguish from measured LOINC 2089-1.
- **PR #1096 (Issue #1089)**: `MedicationAdministration.dosage`
  backfill from parent `Order` for bolus IV meds — was silently
  dropping dose on empty-MA IV paths.
- **PR #1098 (Issue #1088)**: US RxNorm coding added for 19
  top-missing drugs (session-99 code-review surfacing).
- **PR #1093 (Issue #1087)**: prophylaxis Enoxaparin auto-issue now
  consults the drug_safety gate before issuing (previously bypassed
  the anticoag+bleeding-risk contraindication check).
- **PR #1101 (Issue #1100)**: drug_safety gate universalised to every
  post-admission MR path (was originally scoped only to activator +
  order paths).
- **PR #1102 (Issue #1099)**: ED-course `MedicationRequest.status`
  set to `completed` at emergency encounter close (was leaking
  `active` on discharged ED visits).
- **PR #1120 (Issue #1103)**: TP (Total Protein) `Observation` emit
  from annual health-screening panel (was in the panel spec but not
  reaching the emit side).

### Added (session 99, prophylaxis — Issue #1071)

- **New `clinosim.modules.prophylaxis` enrichment module**: standard-of-care
  DVT (VTE) chemoprophylaxis for inpatient encounters ≥ 48 h. Registered as
  POST_ENCOUNTER order 75 (after `device` 70, before `hai` 80).
- **Enoxaparin 40 mg SC daily** emitted as a `MedicationRequest` (via the
  standard FHIR MR builder — no new adapter) for every eligible IMP
  encounter that is not on therapeutic anticoagulation and does not carry
  a contraindication (active bleeding / recent hemorrhagic stroke / GI
  bleed / delivery / active DVT-PE treatment).
- **Cohort measurement (US p=2000 seed=500, 12-month sim)**:
  IMP ≥ 48 h DVT-prevention coverage 61.2 % → 94.2 %.
  Residual 5.8 % = delivery admissions (Z37 / Z38) intentionally
  skipped — postpartum VTE protocol is out of the generic DVT rule.

### Added (session 99, drug_safety — Issue #1066)

- **New `clinosim.modules.drug_safety` foundation module**: class-based
  contraindication rule engine with severity-graded verdicts
  (allowed / minor / moderate / major / contraindicated) and
  alternative-drug substitution. Invoked synchronously from the `order`
  and `patient` modules, not registered as a POST_* enricher.
- **Contraindication rule set** (8 rules): warfarin+antiplatelet,
  anticoagulant+NSAID, β-blocker+non-DHP CCB, ACEi/ARB+K supplement,
  ACEi/ARB+K-sparing diuretic, statin+CYP3A4 strong inhibitor,
  allopurinol+thiopurine, SSRI+MAOI.
- **Alternative drug substitution**: revives Issue #437 dead-data
  `alternative_*` blocks in 15 disease YAMLs via `_indication_tag`
  markers + new `locale/shared/drug_substitution.yaml` generic pool.
- **CIF trace field `PatientProfile.safety_skip_log`** carrying the
  per-patient list of skipped candidates (candidate + active_conflict
  + verdict + substituted_with + context_hint). NOT emitted into FHIR
  structured resources (matches real EHR CPOE behavior).
- **`MedicationRequest.note[]` caution passthrough** for moderate DDI
  co-prescriptions (`authorReference.display = "clinosim drug_safety v1"`).
- **Narrative surfacing across all 4 layers**:
  - Layer 1 (context): `NarrativeContext.safety_skips` +
    `build_narrative_context` filter.
  - Layer 2 (template): `template_generator._render_safety_skips_line`
    appends deterministic avoidance bullets to A&P / Plan.
  - Layer 3 (production LLM prompt): `narrative_seed_bundle.yaml` v13
    → v14 gains `considered_but_not_prescribed` context key + Rule 2
    REQUIRED INCLUSION.
  - Layer 4: sync-note comments on 6 reserved individual prompts.
- **AD-60-style audit plug-in** `audit_drug_safety(patients)` — post-hoc
  missed-gate detector, direct-invocation (full AD-60 4-axis registration
  deferred).
- **verify_medical_stats.py `contraindicated_pair_count` metric**
  (target: 0 per cohort).

### Changed (session 99, drug_safety)

- **Contraindicated home-med pairs no longer form** in the activator
  (chronic-med derivation) or the admission-order pipeline (acute
  first-line drugs vs home meds). US p=1000 seed=500 baseline vs fix:
  30 contraindicated pairs → 0. MR total 2576 → 2572 (skipped or
  substituted). Cohort statistics (HTN prev / encounter mix / mortality
  / incidence) shifted only within small-sample noise.
- **Order-emit RNG shape shifts** where skips or substitutions occur.
  Consumer ETLs that hardcoded MR counts or specific-pair presence
  need to re-baseline against v0.6.0.
- **`clinosim.types.encounter.Order` gains a `notes: list[dict]` field**
  (empty default). MR builder passes non-empty entries into
  `MedicationRequest.note[]`.
- **`clinosim.types.patient.PatientProfile` gains `safety_skip_log:
  list[SafetySkipEntry]` field** (empty default, TYPE_CHECKING import
  to break the types→modules cycle).
- **`clinosim.types.document.NarrativeContext` gains `safety_skips:
  list[dict]` field** (encounter-filtered projection).
- **Issue #437 sibling scope closed**: the 4 previously-dead
  `alternative_*` block families in disease YAML now have a runtime
  reader (`disease.protocol.alternatives_by_indication`).
- **Test updates**: `test_I63_antiplatelets_can_coexist` tightened to
  no-anticoag subset (post-gate coexistence is verifiable only when no
  anticoagulant was picked first). `test_I63_can_yield_anticoag_plus_antiplatelet`
  renamed to `test_I63_anticoag_plus_antiplatelet_blocked_by_default`
  and now asserts the aspirin+anticoag pair is zero — the core B1 defect.
  The whitelist for narrow-indication exceptions (post-PCI+AF, mechanical
  valve) is a post-MVP follow-up.

### Migration notes (session 99, drug_safety)

- Downstream ETLs counting `warfarin+aspirin` / `warfarin+NSAID` /
  `β-blocker+verapamil` co-prescription events will see counts drop
  significantly. Re-baseline against v0.6.0.
- New MR.note authorReference `clinosim drug_safety v1` — note parsers
  that allowlist authorReferences must add it.
- No new FHIR resource types emitted, no bundle-structural change, no
  DetectedIssue.

### Added

- **Pregnancy lifecycle refactor: `TemporalStatePeriod` framework +
  biology-consistent obstetric emit (META #957 Incr 1).** Introduces a
  general-purpose time-boxed state pattern (`TemporalStatePeriod` on
  `PersonRecord.state_periods` + `PatientProfile.state_periods` with
  `has_active_state` / `get_active_state` / `state_history` query API)
  and migrates pregnancy off the pre-Incr-1 "Z34 as chronic condition"
  proxy model. The new `_pregnancy_lifecycle_events` scheduler consumes
  age-banded annual conception Bernoulli (MHLW 2022 / CDC NVSR 2022
  age-specific fertility rates in `perinatal.yaml::lifecycle`) →
  opens a pregnancy period with LMP + EDD (LMP + 280 d) → emits
  prenatal visits at gestational weeks 12/24/36 → emits delivery
  (EDD ± 7 d jitter) + two postpartum visits (7 d / 28 d) → closes the
  period with `outcome="delivered"`. Abortion path closes with
  `outcome="aborted"` and emits a single abortion encounter.
  Cross-year pregnancies carry via `state_periods`; year N+1's call
  short-circuits the conception Bernoulli via `get_active_state`.
  FHIR emit consequences: **Z34 problem-list-item goes to zero**
  (pregnancy is not a chronic condition); **Z37 problem-list-item is
  now derived from `state_history("pregnancy")` delivered periods**
  (one per delivered pregnancy, biology-consistent; replaces the
  session-95 s95-z37 chronic proxy). Prenatal supplements (folic acid,
  iron via `chronic_medications.yaml::Z34`) still emit via an
  activator-time hook keyed on `state_history("pregnancy")`
  non-empty. Z34 / Z39 now route to `obgyn` in
  `_CHRONIC_DISEASE_SPECIALTY`. Classification: **MINOR** — obstetric
  byte-diff (population-level statistical shift + FHIR resource
  reorganization). **Non-obstetric patients are byte-identical**
  (verified p=1000 US, 596/596 non-obstetric persons matched master's
  encounter lists); the chronic sampling loop consumes Z34/Z37
  Bernoulli draws as no-ops to preserve rng cursor. Deferred to Incr 1.5:
  proper per-encounter MedicationRequest emission for prenatal
  supplements (Incr 1 attaches them as home medications, slightly
  over-emitting past the pregnancy period); trimester-specific
  Z34.0X emit; q4w/q2w/q1w prenatal cadence; O24 GDM / O14
  preeclampsia comorbidities. Regression tests: full unit suite 5168
  pass + new `tests/integration/test_pregnancy_lifecycle_e2e.py` +
  rewritten `tests/unit/simulator/test_perinatal_delivery.py` (14
  tests over lifecycle contract + encounter builder). Author: Claude.

### Fixed

- **Chronic-continuation drugs (anticoagulant / statin / antihypertensive
  / antiplatelet) silently lost across encounters.** Two interacting
  defects caused patients newly started on a lifelong secondary-
  prevention drug at admission #1 to reach admission #2 without it as
  a home medication:
  (1) `discharge_rx.py::_append_item` defaulted `duration_days=7` for
      every discharge item, including those sourced from
      `continue_at_discharge` category blocks that are lifelong by
      design (anticoagulation, statin, antihypertensive, antiplatelet).
  (2) `helpers.py::_deactivate_to_layer1`'s acute-course filter used
      `int(_dur) <= 14` which also matched `duration_days == 0`, the
      disease-YAML convention for "long-term / unspecified" (e.g.
      `atrial_fibrillation_rvr.yaml`'s Apixaban + Metoprolol_succinate
      chronic-continuation entries).
  Together, both classes of lifelong meds cleared the acute filter and
  disappeared from `person.current_medications`, so the next
  admission's `_generate_home_medication_orders` (which reads from
  `patient.current_medications` via the cache) emitted nothing for
  them. Fix: `_append_item` accepts `chronic_continuation=True` from
  the `continue_at_discharge` caller (default 28 days for those); the
  filter now guards `0 < d <= 14` so 0 falls through as chronic.
  Regression tests: `test_continue_at_discharge_items_default_to_28_day_chronic_duration`
  + `test_duration_days_zero_is_chronic_and_carries_forward` +
  `test_duration_days_seven_is_acute_and_dropped` (sibling Bucket B
  guard). Verified end-to-end via the previously-failing integration
  test `test_anticoag_from_admission1_carries_forward_to_admission2_home_meds`
  which now passes. Classification: **PATCH** — bug fix restoring the
  A' Phase 1 invariant (Issue #440) + Bucket B invariant (Issue #914)
  compatibility. Structured-CIF drift limited to patients previously
  dropping chronic-continuation drugs; those now retain them across
  admissions as clinically expected. Author: Claude.
- **Ruff E741 in `tests/unit/test_lab_timeseries.py`.** Renamed
  ambiguous variable `l` (single lowercase L, indistinguishable from
  digit 1 in many fonts) to `row` in two set-comprehensions. Pre-fix
  the informational Quality CI check failed on every PR. No runtime
  behaviour change. Classification: **PATCH**. Author: Claude.

### Changed

- **Statistical tuning: I25 (ischemic heart disease) 70+ chronic_prevalence
  further-tuned 0.06 → 0.04 for MHLW/JCS target alignment (yaml-only).**
  The follow-up p=1000 seed=500 JP audit
  (`scripts/audit_realworld_stats_jp.py`) after the initial 0.10 → 0.06
  drop (#969) still showed emitted I25 70+ at 15.3 % — Δ+5.3pp above the
  冠動脈疾患 JCS 2018 ~10 % benchmark. Root cause: the observed care-seeking
  amplification factor between the sampled marginal (yaml value) and the
  emitted marginal (FHIR Condition prevalence) is ~3× under the current
  engine, not the ~1.7× / ~2.5× previously assumed, and is non-linear at
  low base rates. Fix: **yaml-only** — dropped
  `chronic_prevalence.I25["70-99"]` from 0.06 to 0.04 in
  `clinosim/locale/jp/demographics.yaml`; audit script mirror
  `CHRONIC_CONFIG_TARGETS_JP["I25"]` in
  `scripts/audit_realworld_stats_jp.py` updated to match. Inline citation
  comment updated to record the measured amplification (~3×) and the
  three sample points (0.06 → 15.3 %, 0.04 → 12.0 %, 0.03 → 11.1 %) that
  informed the choice. At 0.04 the emitted marginal lands at 12.0 % —
  well within the JCS 2018 5-15 % range and 3.3pp closer to the ~10 %
  midpoint. Classification: **MINOR** — cohort marginal shifts
  (I25 chronic prevalence), so CIF ↔ narrative-CIF byte-identity across
  the sim window is not preserved; a fresh `narrate` run is required.
  Author: Claude.

### Added

- **Issue #957 (male-C50 activation) — Breast cancer for male patients.**
  Real-world male breast cancer is ~1 % of C50 total (MHLW 患者調査 2020 /
  SEER 2020, primarily age 60+ at ~0.02 % carrier prevalence in the male
  60+ cohort). Pre-fix C50 was hard-locked female-only via
  `icd10_sex_restrictions.yaml`; no male patient could carry C50 as a
  chronic condition and the sibling cancer emit paths (follow-up,
  tumor-marker labs, radiation-therapy Procedure) never fired for male
  BC patients. Fix: (a) lift the sex-lock for C50 (C51-C58 female-genital
  sibling codes stay locked); (b) extend the `chronic_prevalence` YAML
  schema with a `by_sex: {F: {bands}, M: {bands}}` block so male / female
  age profiles are declared independently (female peak 40-60, male peak
  60+, ~1 % rate ratio); (c) US ICD-10-CM splits C50 into female-side
  (`C50.919`) / male-side (`C50.929`) unspecified-site leaves — new
  sex-conditional mapping entry + `map_diagnosis_code(code, country, sex=…)`
  optional kwarg + per-person callers in `_build_conditions` /
  `_build_encounter` / `_build_medication_admin` thread the patient's
  sex through so male BC patients receive the anatomy-appropriate
  billing code. New end-to-end test asserts male C50 → `C50.929`,
  female C50 → `C50.919` (US), and both sexes → `C50` identity
  mapping (JP). Adds `C50.929` display to `codes/data/icd-10-cm.yaml`.
  Classification: **PATCH** — the augmentation is sampled via a
  per-patient sub-RNG (`chronic_augment_sex_seed`), so the master
  population RNG stream stays byte-identical to the pre-#957 path
  for every patient (verified: fresh `p=60 seed=42` regen produces
  POP-000047 with sex=M age=38 chronic=[] — matches master exactly);
  the only structured-CIF drift is the addition of C50 chronic
  conditions on ~0.02 % of male 60+ patients (and the derived FHIR
  MedicationRequest / Condition + follow-up encounter cascade that
  follows). Fresh `narrate` is NOT required — pre-existing patients'
  narrative CIF stays consistent because their structural CIF is
  byte-identical to master.
  Author: Claude. Partial #957.
- **Issue #957 (Tier-3-B slice 1) — Perinatal delivery encounter.**
  Pre-fix the simulator carried Z34 (supervision of normal pregnancy)
  as a chronic marker on childbearing-age women, but emitted zero
  delivery Encounters — the obstetric service line was invisible to
  any FHIR consumer computing "births per year in this hospital".
  This slice adds a mother-side delivery inpatient encounter at a
  scheduled month per Z34 pregnancy-year: new
  `clinosim/locale/shared/perinatal.yaml` declares the encounter
  shape (admission dx `O80` single spontaneous delivery, discharge
  dx `Z37.0` single liveborn — mother-side outcome, LOS 5d JP / 2d
  US) + Procedure billing code (JP: `K894` 分娩介助, US: CPT 59400
  routine obstetric care). New scheduler
  (`_perinatal_delivery_events` in `population/engine.py`) picks the
  delivery month per Z34 woman via a per-(patient, year) sub-RNG
  (`perinatal_delivery_seed`); `simulator/engine.py` dispatches the
  new `delivery` event to `simulate_delivery_encounter`
  (new module `clinosim/simulator/perinatal.py`) which builds the
  inpatient encounter + Procedure. Verified JP p=3000 seed=1: **57
  delivery Encounters + 57 delivery Procedures + 57 Z37.0 discharge
  diagnoses across 57 patients** (perfect 1:1), all patients female
  ages 20-27, delivery dates April-October per config window,
  LOS = 5 days. FHIR Procedure emits `K894` (JP MHLW primary) +
  `59400` (US CPT secondary) coding. RNG contract: scheduler uses
  per-(patient, year) sub-RNG so pre-existing calendar events
  (chronic follow-ups, screenings, flu-vax, mammography, DR
  screening) are byte-identical for both Z34 and non-Z34 patients
  — verified by `test_delivery_scheduler_does_not_shift_non_z34_calendar_stream`.
  Newborn Patient generation + postpartum encounters + Z38
  (newborn-side birth outcome, emitted on the baby's record)
  remain a follow-up slice — multi-patient linked-encounter
  architecture (mother→baby partOf reference infrastructure) is
  deferred. Classification: **MINOR** — Z34-carrying women gain
  one new inpatient Encounter + Z37.0 Condition + delivery
  Procedure per pregnancy-year; CIF ↔ narrative-CIF byte-identity
  is broken for Z34 patients only, fresh `narrate` required for
  them. Author: Claude. Partial #957.
- **Issue #957 (Tier-3-A slice 2) — Chemotherapy per-cycle
  MedicationRequest + MedicationAdministration.** Extends slice 1
  (Encounter + Procedure only) to also emit one `Order`
  (order_type=MEDICATION → FHIR MedicationRequest) and one
  `MedicationAdministration` per drug on the regimen's
  `cycle_orders` list. Any consumer computing "cycles of X received"
  or "drug-days of chemo" now gets real records instead of a
  derived approximation. Verified JP p=5000 seed=1: **381 chemo
  encounters × cycle drugs = 609 CIF MARs + 609 CIF Orders**
  (Trastuzumab_q3w single-drug regimen dominant); FHIR-side
  MedicationAdministration / MedicationRequest per-drug counts
  match. Nurse assignment uses the same `medication_administration
  / department` staffing pool as inpatient MAR. 2 new tests:
  single-drug + multi-drug (FOLFOX) regimens both assert 1 Order
  + 1 MAR per drug with matching `order_id`. Classification:
  **MINOR** — new MedicationRequest + MedicationAdministration
  resources on chemo_visit encounters (scoped to cancer patients
  with an active regimen only). Author: Claude. Partial #957.
- **Issue #957 (Tier-3-A slice 1) — Chemotherapy cycle scheduling.**
  Real chemo regimens are cycle-based (FOLFOX q14d, CarboPem q21d,
  Trastuzumab q3w, LHRH q28d), not continuous daily therapy. Pre-fix
  the simulator carried chemo drugs as chronic daily
  `MedicationRequest`s only — the temporal signature was flat and any
  consumer computing "chemo cycles received in the year" got nonsense.
  This slice introduces a healthcare-calendar-level `chemo_visit`
  event: new `clinosim/locale/shared/chemo_regimens.yaml` declares the
  regimen library (cycle interval, course cycles, per-cycle drugs) +
  a per-cancer-code assignment table (`by_cancer`); the population
  scheduler (`_chemo_cycle_events` in `population/engine.py`) picks a
  regimen per chronic-cancer carrier via a per-patient deterministic
  sub-RNG (`chemotherapy_regimen_seed`) and emits `chemo_visit`
  `LifeEvent`s at the regimen's cycle cadence; `simulator/engine.py`
  dispatches these to `_simulate_outpatient_visit` with a chemo-
  specific `followup_spec` that routes to the oncology department
  and emits a `ProcedureRecord` for the chemotherapy administration
  (JP: G003 抗悪性腫瘍剤注入, US: CPT 96413). Verified on JP p=5000
  seed=1: **422 chemo-cycle encounters + 422 chemotherapy-
  administration Procedures across 36 patients**, cycle spacing
  matches regimen intervals exactly (17/12/13/4 cycles = q21d
  Trastuzumab / q14d FOLFOX / q28d LHRH / q21d CarboPem). Per-cycle
  drug `MedicationRequest` / `MedicationAdministration` remains a
  follow-up slice — oral chemo (Capecitabine, Tamoxifen, Anastrozole,
  Bicalutamide) continues to flow through `chronic_medications.yaml`
  unchanged. RNG contract: the scheduler uses a per-(patient,
  cancer_code) sub-RNG, so pre-existing calendar events (chronic
  follow-ups, screenings, flu-vax, mammography, DR screening) are
  byte-identical for both cancer and non-cancer patients — verified
  by `test_chemo_scheduler_does_not_shift_non_chemo_calendar_stream`.
  Classification: **MINOR** — new `chemo_visit` Encounter +
  Procedure resources shift the FHIR resource inventory; the
  scheduler itself is RNG-shape neutral against the rest of the
  calendar. Author: Claude. Partial #957.
- **Issue #757 (partial) — Chronic-medication-driven monitoring pipeline
  foundation.** New `clinosim/modules/monitoring/` module: YAML-driven
  `(medication → monitoring lab + per-visit probability)` mapping,
  fail-loud loader, pure-function `monitoring_labs_for_patient(current_medications, rng)`
  API supporting both dataclass and dict med shapes. Integration hook
  in `simulator/engine.py::_process_chronic_visit_event` merges the
  returned labs into the visit's `visit_labs` after the existing
  `labs_quarterly` / `labs_annual` mergers. Initial mappings
  (warfarin/Coumadin → PT_INR every visit; levothyroxine → TSH ~q6mo;
  metformin & insulin → HbA1c q3-6mo) close #736 (US warfarin patients
  emit 0 → 4/4 PT_INR at p=500). Digoxin/statin/lithium/immunosuppressant
  remain in the #757 table for later passes. Classification: **MINOR**
  — new `ev_rng.random()` calls in the chronic-visit dispatch shift
  the master-rng stream for warfarin/levothyroxine/DM patients.
  Author: Claude. Closes #736; partial #757.
- **Issue #957 (slice 1) — Tumor-marker reference ranges + baseline
  normals.** `chronic_followup.yaml` declared CEA / CA19-9 / AFP /
  PIVKA-II / CA15-3 / PSA as `labs_quarterly` / `labs_annual` for
  C18 / C22 / C34 / C50 / C61 cancer cohorts, but the outpatient lab
  emit path silent-dropped them because their canonical names were
  missing from both `derive_lab_values` and `BASELINE_LAB_NORMALS`
  (silent-skip gate). Fix: add in-remission-normal baseline values
  (PSA 1.5 ng/mL, CEA 2.5 ng/mL, …) + UCUM units in `LAB_UNITS` +
  reference cutoffs to `locale/{jp,us}/reference_range_lab.yaml` +
  LOINC mapping in US `code_mapping_lab.yaml` (JP intentionally uses
  the JP-CLINS `Uncoded` + `LocalCode` dual-slice pattern via the
  existing coding strategy). Verified JP p=500: 0 → 9 tumor marker
  Observations. Sample emit FHIR-valid (JP_Observation_LabResult
  profile satisfied). RT Procedure / chemo cycle / perinatal chain
  remain in #957 for later slices. Classification: **PATCH** —
  data-only additions, no simulation-logic change, no RNG shift.
  Author: Claude. Partial #957.
- **Issue #965 — Death-certificate + death-discharge-summary
  Compositions for deceased inpatients.** New per-section LLM
  refinement pipeline for 死亡診断書 (LOINC 64297-5) and
  死亡退院サマリー (LOINC 34133-9 extended) with 8+ section templates
  (autopsy status/findings, circumstances of death, complications &
  comorbidities, family communication, terminal course, treatment
  course, admission state). Closes #961.
- **Issue #972 — JP routine 定期予防接種 schedule + chronic-condition
  birthDate gate.** Adds age-appropriate pediatric immunization
  schedule per MHLW 予防接種法 (Hib / PCV13 / DPT-IPV / MR / VZV / JEV);
  clamps `Condition.onsetDateTime` at `birthDate` per Issue #968.
  Closes #917, #968.
- **Issue #954 — Missing procedure catalog entries.** Adds PCI (K546),
  pacemaker implant (K597), craniotomy (K169), ileus tube (K380),
  and bowel resection (K7161) to the procedure emit catalog.
  Closes #939.
- **Issue #951 — Anthropometric vitals emission.** Emits height,
  weight, BMI, and (pediatric) head-circumference `Observation`s per
  visit across every venue. Closes #946.
- **Issue #955 — AllergyIntolerance NKA + polyallergy support.**
  Emits explicit "no known allergies" positive assertion when the
  patient's allergy list is empty; supports multi-allergen patients
  with distinct `AllergyIntolerance` resources per allergen.
  Closes #942.
- **Issue #952 — `hospitalization.admitSource` + `dischargeDisposition`
  dual-slot fix.** Restores populated fields on all 703 IMP encounters
  via `_build_hosp_concept` with the dual-slot (EN coding + locale
  text) pattern. Closes #941.
- **Issue #953 — Universal post-snapshot event filter.** New bundle-
  layer filter drops any resource whose `effectiveDateTime` /
  `authoredOn` / `performedDateTime` falls after `snapshot_date`,
  including cascade-generated MedAdmin / DR entries that pre-date
  fixes only propagate at emit time. Closes #945.

### Fixed

- **Issue #909 — Per-patient singleton Observation ids leaked the
  Patient hex tail.** 32,690 records (2.63 % of all Observations)
  across the alcohol / smoking / occupation / blood-abo / blood-rh /
  carelevel families had `.id` whose 12-hex tail was byte-identical
  to `Patient.id`'s tail — trivially recovering the patient link.
  Root cause: both `resolve_patient_id` and each family's opaque-id
  resolver hashed the same unsalted `patient_id` string, so
  `sha256(patient_id)[:12]` reappeared in both slots. Fix: salt each
  family's hash input with its observation-key kind slug
  (`blood-abo-observation-key:{patient_id}` etc.) so `.id` diverges
  from `Patient.id` and from every other family. Identifier.value
  kept equal to `patient_id` so consumers keep the same round-trip
  path via the `Identifier.system` URI. Regression test parametrized
  over all 6 families verifies the tails diverge. Classification:
  **PATCH** — 6 families' `.id` values change, no other fields
  touched. Closes #909.
- **Issue #918 — ImagingStudy series-as-studies duplication.**
  780 same-encounter same-description pairs within 60 min (189
  head-CT pairs within 30 min) and 0 pairs in the 1-6 h bucket —
  the tell-tale hole between "series-as-studies" cluster and
  legitimate repeat imaging (≥ 6 h). Extreme audit sample
  `pt-02ee09c03138`: 3 head-CTs at 21:20 / 21:37 / 21:40 (medically
  impossible on one scanner). Fix: extend the Issue #822 dedup with
  a wider `(encounter, modality, body_site) within
  _SERIES_AS_STUDIES_WINDOW_MIN (60 min)` criterion; gated to
  CT / MR / US / XA (CR chest-X-ray legitimate ICU repeats left
  alone). Regression tests cover the audit shape + retention of
  legitimate 6h-apart repeats. Classification: **PATCH** — no CIF
  Order records deleted, only the redundant ImagingStudyRecord.
  Closes #918.
- **Issue #916 — 43 % of Conditions were ICD-10 Z-chapter
  visit-reason codes.** 14,384 / 33,188 Conditions were Z09
  (follow-up) / Z00.0 (checkup) / Z23 (immunization) / Z12.x /
  Z13.5 pseudo-diagnoses, every one emitted as `clinicalStatus=resolved`
  with same-day `abatementDateTime` — polluting the problem list
  with non-diseases. Fix: new `is_visit_reason_zcode` predicate
  (Z00-Z02 / Z09 / Z11-Z13 / Z23 / Z25-Z29 / Z71 / Z76 base bands;
  Z80-Z99 personal-history / device-presence codes preserved as
  clinical facts). Gated three emission paths in `conditions.py` +
  `encounter.py` on the predicate: Condition primary/admission emit
  skipped, `reasonReference` and `diagnosis[]` refs suppressed so no
  dangling refs remain. `Encounter.reasonCode` still carries the
  Z-code text + coding. Verified JP p=100: 0/179 Conditions carry
  any Z-code (was ~43 %). Classification: **MINOR** — Condition
  resource count drops by ~43 % (`33,188 → ~18,804`), so cohort
  totals differ. Closes #916.
- **Issue #911 — AVPU + GCS sampled independently produced 52 %
  same-day contradictions (6,152 `AVPU=U + GCS=15` impossible
  pairs).** Three coordinated fixes: (1) `nursing_enricher.py` skips
  GCS emission on vitals without AVPU (removes default-A
  `GCS ≈ 15` records that were unpaired against real AVPU); (2)
  `vitals_pipeline.py` stabilizes AVPU per (patient, day) via an
  isolated per-day sub-RNG from `sha256("avpu:<patient>:<day>")` —
  master-rng consumption preserved by still calling `_loc_for(state,
  disease_id, day, rng)` and discarding (pattern per
  `feedback_rng_neutral_additive_field`); (3) `nursing.py` sets
  GCS = 15 strictly for AVPU = A (jitter skipped; `rng.integers`
  draw still consumed to preserve stream shape). Verified JP p=200:
  in-range % 48 → **100 %** across all AVPU categories, median GCS
  now 15 / 13 / 9 by category (was 14 across every category).
  Classification: **MINOR** — vitals `consciousness_level` /
  `gcs_score` values change per patient-day. Closes #911.
- **Issue #913 — MedicationAdministration ignored parent
  MR.timing.repeat.frequency in 76.5 % of prescriptions.** MAR ran
  on a hardcoded drug-name / route dispatch and defaulted to TID
  (3/day) for oral drugs regardless of prescription frequency, so
  amlodipine 1/day emitted 3 admins/day (3× on-chart over-dose
  signature; 100 % of amlodipine / atorvastatin / candesartan /
  clopidogrel / apixaban / lansoprazole / vitamin D / metformin /
  tiotropium prescriptions mismatched their own MR). Fix: new
  `_admin_hours_from_frequency` helper maps prescribed per-day
  frequency to MAR admin slots (1→[8], 2→[8,20], 3→[8,14,20],
  4→[0,6,12,18], 6→q4h, 8→q3h, ≥12→q4h cap for continuous
  infusions — cap reflects real MAR practice for drips). Ordering:
  antibiotic clinical-override (Q6H β-lactam combos + Q8H
  carbapenem / adv-cephalosporin) → `order.frequency_per_day` →
  legacy drug-name fallback. Verified JP p=100: match rate
  23.5 % → **63.6 %**, under-admin 16.3 % → **0.0 %**.
  Classification: **MINOR** — MedAdmin count per medication order
  changes; downstream Composition / discharge-summary references
  propagate. Closes #913.
- **Issue #914 (Bucket A) — Pyelonephritis 4-drug template
  eliminated.** Pre-fix ~90 % of acute pyelonephritis admissions
  received ≥3 antibiotics simultaneously, with 72/92 receiving the
  identical 4-drug template Ceftriaxone + Cefcapene + Meropenem +
  Levofloxacin. Two root causes: (1) UTI's `discharge_oral` listed
  two alternative oral agents without an `exclusive_classes`
  marker → both emitted; (2) unconditional `escalation` trigger on
  day-3 non-improvement fired the entire escalation drug list
  regardless of clinical criteria. Fix: UTI `discharge_oral` now
  declares `exclusive_classes: ["oral_antibiotic"]` with per-entry
  `drug_class` + probability weights (Levofloxacin 0.65 / Cefcapene
  0.35 JP; Cipro 0.55 / TMP-SMX 0.45 US). Escalation entries gain
  an optional `probability` field consumed by the daily-loop branch
  (Meropenem 0.4 JP, Meropenem 0.4 + Pip-Tazo 0.2 US → ~15 %
  effective escalation, matching IDSA UTI 2010 / JP 尿路感染症 GL
  2015). Verified JP p=300: 4-drug template 72 → **0**; IMP ≥3-drug
  rate 24.5 % → **11.8 %**; 急性腎盂腎炎 ≥3-drug 90 % → **0 %**.
  Bucket B (antibiotics on non-infectious encounters — hypertension /
  dyslipidemia / stable COPD) remains as follow-up in #914.
  Classification: **MINOR** — antibiotic emit rate + escalation
  rate shift per-encounter. Partial #914.
- **Issue #964 — Practitioner qualification population.**
  Populates `Practitioner.qualification` for non-MD / RN roles
  (technicians, therapists, dietitians) with regulatory-appropriate
  identifiers. Closes #962.
- **Issue #970 — MedicationRequest.authoredOn timing invariant.**
  Ensures `MR.authoredOn` precedes every linked MedicationAdministration
  `effectiveDateTime`, restoring the temporal ordering guarantee.
  Closes #967.
- **Issue #973 — IV MedicationRequest infusion rate emission.**
  Populates `dosageInstruction.doseAndRate.rateQuantity` for
  continuous drips and `timing.repeat.duration` for bolus antibiotics
  via `iv_infusion_defaults.yaml`. Closes #966.
- **Issue #974 — Encounter.reasonCode ⊆ diagnosis[] invariant.**
  Ensures every `reasonCode.text` has a matching Condition in
  `diagnosis[]`. Closes #912 (encounter-side sibling of
  conditions-side #912 fix).
- **Issue #975 / #976 — Practitioner allocation balance + surgery
  roster scaling.** Corrects staff allocation across the full roster
  and scales surgery roster to catchment volume. Closes #915,
  #975 GS residual.
- **Issue #977 — I25 (ischemic heart disease) 70+ chronic prevalence
  further tuning (0.06 → 0.04).** Follow-up to #969 that landed
  emitted marginal at 15.3 % (above JCS 2018 ~10 % benchmark);
  measured amplification is ~3× not the assumed ~1.7-2.5×. Adjusts
  `chronic_prevalence.I25["70-99"]` + audit script mirror. Emitted
  marginal now 12.0 %, within JCS 2018 5-15 % range. Closes #969
  follow-up.
- **Issue #978 — ServiceRequest.authoredOn ≤ DR.issued invariant.**
  Sibling of #967: ensures `SR.authoredOn` precedes every linked
  `DiagnosticReport.issued`. Closes #971.
- **Issue #949 — ICD-10 sex-lock dispatch.** Sex-gates ICD-10
  dispatch to eliminate anatomically-impossible diagnoses (e.g. male
  patients with pregnancy codes). Closes #947.
- **Issue #950 — Adult social-history age gate.** Adult smoking /
  alcohol / LTCI carelevel Observations are now suppressed for
  pediatric patients (< adolescence). Closes #938, #940.

### Narrative CIF

- **Issue #987 — Vitals prepended to physical_examination narrative
  + chief complaint × physical exam consistency guard.** Closes
  #979, #980.
- **Issue #988 — ED workup / disposition from CIF orders + FamilyHistory
  narrative + 100+ per-disease chief-complaint variants.** Closes
  #981, #982, #983.
- **Issue #989 — HPI enrichment (ROS / home meds / prior care) +
  assessment personalization (patient-specific values) + discharge
  instructions expansion (32 disease templates).** Closes #984, #985,
  #986.

### LLM prompts

- **Issue #993 — LLM refinement enabled for referral_note (紹介状).**
  `template_only` → `template_seed_bundle` refinement path. Closes
  #990.
- **Issue #994 — PROCEDURE_NOTE (処置記録, LOINC 28570-0) DocumentType +
  LLM refinement pipeline.** Closes #992.
- **Issue #995 — OPERATIVE_NOTE (手術記録, LOINC 11504-8) DocumentType +
  LLM refinement pipeline.** Closes #991.
- **Issue #996 — LLM prompt v11 → v12 bundle cross-ref cleanup + full
  audit report.**
- **Issue #1001 — 14 dormant per-task prompts marked as reserved +
  DDS autopsy naming drift fix + missing DDS complications prompt.**
  Closes #999, #1000.
- **Issue #1002 — Per-doc-type LLM guidance blocks for operative_note /
  procedure_note / death_certificate / death_discharge_summary in
  `narrative_seed_bundle.yaml` v13.** Closes #997, #998.

- **Issue #912 — Inpatient `Encounter.reasonCode` orphaned from
  `Encounter.diagnosis[]`.** Pre-fix, 35.7 % (30/84) of IMP encounters
  at JP p=1000 seed=500 emitted a `reasonCode.text` whose Condition
  did not exist in the patient's record — `diagnosis[]` linked to a
  chronic comorbidity or refined discharge Condition instead. Two
  paths converged:
  (a) `admission_diagnosis_code` (e.g. `J44.1` COPD急性増悪, `N10`
  急性腎盂腎炎) drove `reasonCode`, but the encounter-primary
  Condition was built from `discharge_diagnosis_code` and could carry
  a different ICD (`N20.0` 腎結石 for the pyelonephritis case);
  (b) when the discharge dx merged into a chronic problem
  (`is_chronic_primary` path — COPD-exacerbation admissions whose
  chronic list contains `J44`), the encounter-primary was suppressed
  entirely and `diagnosis[]` only carried the chronic (`J44`), while
  `reasonCode` retained the leaf `J44.1` — never matched. Fix: new
  `needs_admission_diagnosis_condition` helper in
  `conditions/primary_ref.py` decides whether the admission dx
  round-trips via the primary/chronic Conditions; when not,
  `_build_conditions` emits an extra `Condition` (opaque id derived
  from `{encounter_id}-admission`, category `encounter-diagnosis`,
  `text` = leaf-code display so `.text` matches `reasonCode.text`, JP
  eCS `admitting` diagnosis-type extension) and `_build_encounter`
  appends a matching `diagnosis[]` entry with `use=AD` at the trailing
  rank. Both builders route the decision through the same helper so
  ids stay consistent. Verified on JP p=1000 s=500: mismatched IMP
  encounters 30 → 0 (35.7 % → 0.0 %). PATCH-scope — CIF unchanged,
  new FHIR Condition rows only fire for encounters that would
  otherwise fail the invariant.
  Closes #912.
- **Issue #966 — IV MedicationRequests now carry infusion rate /
  bolus duration.** Pre-fix, 421/421 IV-route `MedicationRequest`
  resources emitted on JP p=1000 s500 (post-#920) had no
  `dosageInstruction.doseAndRate.rateQuantity` (and no
  `timing.repeat.duration`) — leaving downstream drug-safety alerts
  (KCl > 10 mEq/h, vancomycin > 10 mg/min, phenytoin > 50 mg/min)
  unreproducible and nursing-side administration reconstruction
  impossible. Fix: new `augment_iv_dosage_with_rate` helper (called
  from both `build_dosage_instruction` and
  `_build_discharge_medication_request`) resolves per-drug defaults
  from a new yaml catalog
  `clinosim/locale/shared/iv_infusion_defaults.yaml` — continuous
  drips (saline, KCl, insulin drip, pressors) get
  `doseAndRate.rateQuantity`; intermittent bolus drugs
  (antibiotics, PPI, blood products) get
  `timing.repeat.duration` + `durationUnit = "min"`; IV push
  drugs (< 5 min: naloxone, fentanyl, ketorolac, morphine push)
  intentionally get NEITHER, per feedback_semantic_correctness
  _over_coverage — a fabricated rate on a push drug is worse than
  an honest absence. Priority order at emit: explicit rate already
  in the dose text (`12 U/kg/h`, `100 mL/h`) wins over catalog.
  Post-fix coverage: 301/318 (94.7 %) on JP p=1000 s500; the
  remaining 17 are all catalog-declared push drugs. Constants live
  in yaml (`feedback_constants_live_in_external_config.md`) so
  pharmacists / nurses can tune rates without a code change; the
  catalog covers 74 drugs plus a `default` fallback (30-min bolus).
  Closes #966.
- **Issue #915 — Practitioner allocation broken (16 % (18/116)
  Practitioners never referenced by any Encounter/CareTeam).** Pre-fix,
  ED encounters hardcoded `assign_staff(..., "internal_medicine", ...)`
  in `simulator/emergency.py`, so all 4 emergency-medicine specialists
  (DR-EM-*) in the roster were unreferenced — every `EMER` encounter was
  attributed to an internist. Radiology `DiagnosticReport.performer` /
  `resultsInterpreter` fell back to the encounter attending, so all 4
  radiologists (DR-RAD-*) were also unreferenced. Allied-health staff
  (PT/OT/ST/RD/MSW + rehabilitation MDs) appeared in `Practitioner.ndjson`
  but no clinical resource ever named them. And `generate_roster`
  created 2 physicians each for `nutrition` and `medical_social_work`
  service lines (DR-NU-*, DR-ME-*) — depts that are staffed by
  dietitians / social workers, not MDs — leaving 4 perpetually-
  unreferenced practitioners. Fix (four coordinated changes):
  (1) `simulator/emergency.py:116` — ED attending drawn from
  `emergency_medicine` pool (falls through to any physician when roster
  has no DR-EM);
  (2) `output/fhir_r4/labs/diagnostic_report.py` — imaging DR
  performer / resultsInterpreter deterministically picks a radiologist
  from the roster via `sha-lite(role-salt + study_id + order_id)` hash
  (RNG-neutral additive per `feedback_rng_neutral_additive_field`);
  (3) `output/fhir_r4/encounters/care_team.py` — inpatient CareTeam
  gains PT / OT / ST / RD / MSW / rehab-physician participants via
  role-salted encounter-id hash, mirroring the pharmacist pattern
  (SNOMED role codes 36682004, 80546007, 159026005, 159033005,
  106328005, 309362007);
  (4) `modules/staff/engine.py` — physician generation skipped for
  `nutrition` and `medical_social_work` depts. Verified on JP p=1000:
  **112/112 Practitioners referenced (0 unreferenced)**, DR-EM own
  100+ EMER encounters each, DR-RAD signs 60+ radiology DRs each,
  allied-health each get 60+ CareTeam refs. MINOR — CIF
  `attending_physician_id` changes on `EMER` encounters (RNG cascade
  at `rng.choice`) and new CareTeam participants require a fresh
  `narrate` run. Closes #915.

### Changed

- **Statistical tuning: comorbidity multipliers + I25 70+ prevalence + PPSV23
  coverage aligned to MHLW audit targets (yaml-only).** The p=1000 seed=500
  JP audit (`scripts/audit_realworld_stats_jp.py`) flagged three cohort
  marginals that had drifted under the v0.5.0 marginal-preserving engine:
  (1) chronic conditions/patient MEAN was 2.99 vs MHLW 国民生活基礎調査
  2019 target 2.3 (65+ 平均 2.3, 全年齢 1.4), (2) I25 (ischemic heart
  disease) 70+ prevalence was 18.8% vs 冠動脈疾患 JCS 2018 target 10%
  (Δ+8.8pp), (3) PPSV23 lifetime 65+ M was 35.8% vs config target 40%
  (Δ-4.2pp) — under-shoot after care-seeking + min_age eligibility filtering.
  Fix: **yaml-only** — (1) reduced every `comorbidity_correlations`
  multiplier in `clinosim/locale/jp/demographics.yaml` by ~15% (e.g.,
  I10→E78 2.2→1.9, E11.9→N18 2.5→2.1) keeping JSH/JCS correlation SHAPE;
  US mirror in `clinosim/locale/us/demographics.yaml` applied the same
  ~15% reduction. (2) `chronic_prevalence.I25["70-99"]` lowered 0.10 →
  0.06 in `clinosim/locale/jp/demographics.yaml`; audit script mirror
  `CHRONIC_CONFIG_TARGETS_JP["I25"]` in `scripts/audit_realworld_stats_jp.py`
  updated to match. (3) `pneumococcal_ppsv23.coverage_by_age_sex["65-99"]`
  in `clinosim/locale/jp/immunization_schedule.yaml` bumped 0.40/0.42 →
  0.45/0.47 (M/F). Inline citation comments preserved; numeric values
  only. Per the marginal-preserving engine, the yaml value IS the target
  sampled marginal — adjustments picked so the emitted marginal lands
  near the MHLW benchmark. Classification: **MINOR** — cohort marginals
  shift (chronic prevalence + comorbidity load + immunization rate), so
  CIF ↔ narrative-CIF byte-identity across the sim window is not
  preserved; a fresh `narrate` run is required.
  Author: Claude.

### Added

- **Issue #961 — Death certificate (死亡診断書) Composition for deceased
  inpatients.** Pre-fix, 47/6,389 deceased patients on the JP p=6,389
  dataset (`Patient.deceasedDateTime` set) all received the same
  generic 退院時サマリー Composition as ambulatory discharges — zero
  死亡診断書 were emitted despite 医師法第 20 条 mandating one for
  every physician-certified death. Fix: **additive** new
  `death_certificate` document spec (LOINC 64297-5, verified via
  loinc.org LONG_COMMON_NAME) with a new `discharge_once_if_deceased`
  generation frequency that fires whenever
  `encounter.discharge_disposition == "exp"` (already populated by
  `inpatient.py:537` when `death_occurred`). Emits **alongside** the
  existing 退院時サマリー (never replaces it — the discharge summary
  remains required for billing/administrative discharge processing).
  Sections cover the 医師法第 20 条 legally-defined fields: 直接死因
  (immediate cause, sourced from `clinical_diagnosis.discharge_diagnosis_code`),
  直接死因までの期間, 原死因, 影響を及ぼした傷病名, 死因の種類, 解剖の有無.
  JP dispatch uses `jpfhir-doc-typecodes` CS with 死亡診断書 title
  (dual-slot in `.text` per feedback_dual_slot_at_emit_site_not_post_process);
  US dispatch uses LOINC + "Death certificate" title. Verified on
  JP p=1000 seed=500 2025-01-01→2026-03-31: 1/1 deceased patient
  received a death certificate, 0 false positives. Classification:
  **PATCH** — the fix is a new FHIR Composition emit derived from an
  existing CIF field (`Encounter.discharge_disposition`); no structured
  CIF byte drift beyond the additive `ClinicalDocument` stub entries
  which the narrative CIF ↔ structured CIF contract already covers via
  the two-pass lifecycle.
  Author: Claude.

### Changed

- **Issue #939 — Procedure catalog gaps for cardiology / neurosurgery /
  GI-obstruction admissions.** Pre-fix, the Procedure catalog was 65 codes
  / ~440 records across 40,066 encounters and completely omitted the
  standard-of-care interventions for four common admission reasons: 0/17
  MI admits had PCI, 0/101 HF admits had pacemaker/ICD/CRT, 0/6 ICH
  admits had craniotomy/hematoma-evacuation, 0/9 ileus admits had ileus
  tube or bowel resection. Root cause: the bedside procedure engine
  (`clinosim/modules/procedure/engine.py`) held disease → procedure
  dispatch rules only for orthopedic + general-surgery admissions.
  Fix: **additive** — five new entries added to `_BEDSIDE_PROCEDURES` +
  `_PROCEDURE_METADATA` (`coronary_pci`, `pacemaker_implant`,
  `craniotomy_hematoma_evacuation`, `ileus_tube_placement`,
  `bowel_resection`) with real MHLW K-codes (K546 経皮的冠動脈形成術,
  K597 ペースメーカー移植術, K164-1 頭蓋内血腫除去術（開頭）, J034-2
  イレウス用ロングチューブ挿入法, K719 結腸切除術) added to
  `clinosim/codes/data/k-codes.yaml` and CPT codes (92920, 33208, 61312,
  44500, 44140) added to `clinosim/codes/data/cpt.yaml`. Dispatch table
  `_ISSUE939_PROCEDURE_RULES` maps `acute_mi` → PCI @ 0.85,
  `heart_failure_exacerbation` → pacemaker @ 0.10, `hemorrhagic_stroke`
  / `subdural_hematoma` → craniotomy @ 0.35, `ileus` → tube @ 0.60 +
  resection @ 0.20 (JCS / JSNS baseline uptake). Each dispatch draws
  from a per-(encounter, proc_type) sub-RNG
  (`issue939_procedure_seed`) so the additive emissions do NOT cascade
  the shared patient-scoped rng — every existing lab / imaging /
  discharge-Rx / memoize consumer keeps its pre-fix byte-shape; only
  the new Procedure records join the CIF. Consequence: structured CIF
  gains Procedure rows for the four admission-reason cohorts (rates
  match spec on the 500-encounter cohort test), so a fresh `narrate`
  run is required for CIF ↔ narrative-CIF consistency — MINOR (v0.6.0).
  Closes #939.
- **MINOR driver** — `chronic_prevalence` yaml values for **E11.9 (T2DM)**,
  **N18 (CKD)**, and **J44 (COPD)** in both `clinosim/locale/jp/demographics.yaml`
  and `clinosim/locale/us/demographics.yaml` restored to hospital-user
  cohort targets. The Issue #739 ~0.5× downscale was double-compensation
  under the v0.5.0 marginal-preserving engine (#902) and caused the
  emitted cohort to under-shoot the intended hospital / Medicare-user
  targets (JP E11.9 70+ 13.27% vs ~20%, N18 60-69 7.26% vs ~15%, etc.).
  US also restores E78 downscale. YAML-only fix — no code change; the
  marginal-preserving engine already handles the new base_prev values
  correctly. B-3 phase 2 completion. Closes #919.
- **Issue #927 — Ambulatory (AMB) encounter length by visit type.**
  Pre-fix, every outpatient encounter (~37k in JP p=10000) had
  `Encounter.length` drawn from a uniform `rng.integers(15, 45)`
  regardless of visit purpose, producing a flat 15-44 min plateau that
  excluded the 5-10 min 再診 (return-visit) peak that dominates JP
  primary-care volume. Length is now drawn from a per-visit-type
  triangular distribution whose parameters live in
  `clinosim/locale/<country>/ambulatory_visit_length.yaml`
  (grand-design rule: tunable constants live in yaml, not code):
  JP `chronic_followup` triangular(5, 9, 20) — the 再診 short tail;
  JP `health_screening` triangular(20, 30, 45) — 特定健診 intake;
  plus buckets for `post_discharge` and `pediatric_visit` and US
  equivalents keyed on AHRQ MEPS / CPT E/M reference visit lengths.
  The sampler routes through the `clinosim.determinism` proxy
  (cross-platform bit-reproducible) via a per-encounter sub-RNG
  (`ambulatory_visit_length_seed`), which isolates the length draw
  from the caller's `opd_rng` — downstream RNG consumers (staff, vitals,
  labs, prescription sampling) keep their pre-fix byte-shape. The
  removed constants `OUTPATIENT_VISIT_DURATION_MIN_MIN` and
  `OUTPATIENT_VISIT_DURATION_MAX_MIN` have no external callers.
  Home-visit / inpatient / ED length logic is intentionally unchanged.
  Consequence: Structured CIF `Encounter.length` distribution changes
  for outpatient encounters — this is the intended fix; a fresh
  `narrate` run is required for consistency, so the next release is
  MINOR (v0.6.0).

- **Issue #926 — Post-mortem event emission gate.** Every FHIR bundle
  went through a bundle-finalize walk that dropped resources whose
  timestamps fall after the subject `Patient.deceasedDateTime`, and
  `Patient.active` now flips to `false` for deceased patients (was
  `true` for 5/5 deceased at p=1000 baseline). The immunization
  enricher additionally clamps `_as_of` at date_of_death so the
  annual flu scheduler cannot pick a post-mortem November. The
  bundle-level filter is belt-and-braces — it walks
  effectiveDateTime / issued / authoredOn / occurrence / recorded /
  collected / date / performed / started + Period.start/end mirrors,
  drops YYYY-MM-DD > deceasedDateTime, and keeps same-day terminal
  activity (labs, MAR, death certificate). RNG shape is preserved
  for living patients; deceased-subset immunization records shift
  slightly because the shortened `as_of` window changes the number of
  `rng.random()` draws inside `generate_immunizations`. Closes #926.
- **Issue #921 — Adult vaccine timing seasonality.** Flu was
  single-month (100% of 22,538 doses in November across 10 seasons)
  and COVID-19 was uniform-monthly with no wave structure. New
  yaml-driven `seasonal_distribution` block per country selects flu
  month from Oct-Feb (JP, Nov peak) / Sep-Feb (US, Oct-Nov peak); new
  `wave_epochs` block per country drives COVID-19 with a two-stage
  sampler (age-weighted epoch pick → monthly_curve within the clipped
  epoch window). Both fall back to legacy behavior when yaml is
  absent (bit-identical for callers without the config). Preserves
  the #928 death gate via the `_as_of` clamp. RNG cascade limited to
  the immunization sub-RNG stream
  (`ENRICHER_SEED_OFFSETS['immunization']`); master untouched.
  Micro-simulation (500 JP patients, 10y): Nov = 40% of flu, COVID
  wave peaks 2021-06 / 2021-11 / 2022-11 / 2023-11 / 2024-11 with
  documented gaps. → **PATCH** per commit body. Closes #921.
- **Issue #922 — Pediatric over-representation and elderly
  under-representation.** JP emitted cohort ran 0-14 at 17.42% vs
  MHLW 患者調査 2020 5.4% target and 65+ at 44.34% vs 56%. Root cause:
  well-child + immunization pediatric schedule fired 9.56
  encounters/patient at severity=0.0, bypassing the care-seeking
  gate. Three composed structural fixes:
  (1) `clinosim/config/pediatric_schedule.yaml` well_child_infant
  [6,7,8] → [3,4,5], well_child_early [2,3] → [1,2],
  immunization_infant [2,3] → [1,2] toward MHLW 乳幼児健康診査 cadence.
  (2) New `care_seeking.age_conditional` block in
  `locale/{jp,us}/demographics.yaml` (mirrors the sex_ratio pattern);
  resolved via `_care_seeking_threshold_mean` — RNG-shape neutral
  (only the `mean` argument to `rng.normal(mean, sd)` changes).
  (3) `modules/pediatric/calendar.py` participation gate at top of
  `generate_pediatric_events` — one `prng.random()` per person-year
  decides whether the family skips this year's entire schedule.
  Post-fix p=1000 s=500 audit: 0-14 8.0%, 65+ 50.0%, 75+ 30.6%; all
  bands 25-84 pass ±3pp vs 患者調査. Cohort-shape RNG cascade →
  **MINOR** (v0.6.0). Closes #922.
- **Issue #947 — Sex-locked ICD-10 dispatch.** Six female patients
  in the p=6389 v0.5.0 snapshot emitted `N41.0` (acute prostatitis)
  from the UTI differential picker. Root cause: two per-file inline
  `_SEX_RESTRICTED_ICD = {"N40": "M"}` tables covered exactly BPH;
  every other anatomy-locked ICD (N41, N70-N77, O00-O9A, C50-C63,
  etc.) could silently emit onto the opposite-sex patient. Fix — new
  canonical yaml `clinosim/locale/shared/icd10_sex_restrictions.yaml`
  + `clinosim/simulator/sex_gating.py` (loader + two helpers:
  `is_sex_locked_for` / `pick_sex_compatible_dx_code`). The
  differential picker in `modules/diagnosis/engine.py::
  get_current_diagnosis_code` walks the already-probability-sorted
  candidate list to the next sex-compatible entry — no fresh RNG
  state consumed, preserving cross-platform bit-reproducibility.
  Every candidate locked → falls back to `UNRESOLVED_DIAGNOSIS_ICD`
  (R69) rather than emit a locked code. Also unifies the two inline
  tables through the helper. New regression tests at
  `tests/unit/simulator/test_sex_gating.py` cover N41.0 on females /
  O-chapter on males / neutral codes never blocked / unknown sex
  never blocks. Closes #947.
- **Issues #938 + #940 — Age gates for adult social-history and
  LTCI.** Adult alcohol / smoking Observations and LTCI carelevel
  Observations previously emitted for every patient regardless of
  age. New `age_gates.{alcohol,smoking}_min_age` (default 15 per
  USPSTF / MHLW 高校 health-checkup) in
  `modules/sdoh/reference_data/social_history.yaml` — pediatric rows
  are now absent (spec-clean, no placeholder). New
  `eligibility_gates` in `modules/care_level/reference_data/
  care_level.yaml` implements the 介護保険 rules: 第1号被保険者 (universal)
  age ≥ 65; 第2号被保険者 (requires 相当疾病) age 40-64 with a
  chronic condition in the F00 / G30 / G20 / J44 / I60-I69 / G12.2 /
  M80 subset that clinosim actually emits. Eligibility filter runs
  after the per-patient sub-RNG draw, so RNG shape is unchanged for
  skipped patients. p=1000 s=500 verification: 0-14 alcohol/smoking
  0 (was 8), 40-64 carelevel 0 (was ~1-2% category error), 65+
  carelevel 19 (was universal). Closes #938 + #940.

### Fixed

- **JP Coverage.period + insurance-type age gate** (Issue #923). Two
  defects converged into ≥32 % of JP encounters being emitted without a
  valid Coverage row:
  - Every `Coverage.period` was a single hard-coded fiscal year
    (`2025-04-01 .. 2026-03-31`), leaving 32.9 % of encounters (11,908
    before start + 1,270 after end at p=10000) outside any Coverage.
  - The identity-driven `Coverage.type.text` sampler had no age gate:
    142 patients aged ≥ 75 carried non-`後期高齢者医療制度` insurance
    (`高齢者の医療の確保に関する法律` §50 requires all ≥ 75 residents to
    enrol in 後期高齢者医療制度), and 157 minors (< 18) were booked as
    `被用者保険（被保険者）` — a role a child cannot legally hold.
  Fix: `_build_coverage_resources` now emits **one Coverage row per
  fiscal year** the patient has encounters in (JP FY = 4/1 → 3/31,
  boundaries in `locale/jp/identity.yaml::fiscal_year`), with the
  category re-evaluated per FY: ≥ 75 at period end → `後期高齢者医療制度`
  (payor swapped to the 後期高齢者 insurer, 1割 copay); < 18 at period
  start on an employee policy → demoted to `被扶養者`. The JP identity
  provider (`_sample_scheme`) additionally refuses to nominate a minor
  as a household subscriber (all-minor households fall back to 国保).
  Verified on p=1000 seed 500 (2025-01-01 → 2026-08-31): encounters
  outside any Coverage.period 0/4011 (0.00 %, was ~40 %); minors on
  被保険者 0 (was 157). PATCH-scope — CIF unchanged, FHIR emit only.
- **Issue #924 — Referral letter self-loop.** JP-CLINS 診療情報提供書
  (LOINC 57133-1) previously emitted `Organization/hospital-main` in
  BOTH `920` (紹介元) and `910` (紹介先) `entry.reference`, giving a
  self-loop in 100% of referral Compositions while the narrative
  asserted `紹介先:他院`. Fix: new catalog
  `clinosim/locale/jp/external_organizations.yaml` (10 plausible 診療所
  / 病院 / 大学病院) + `documents/referral_orgs.py` samples an entry from
  `(patient_id, encounter_id)` via `sha256 % N` (RNG-neutral per
  `feedback_rng_neutral_additive_field.md`; no master-RNG
  consumption, stable across processes and platforms). The referral
  Composition builder overrides `910`'s entry + narrative with the
  sampled facility; `920` still pins hospital-main since all fire
  paths model outgoing referrals. `_bb_compositions` appends only the
  Organizations actually referenced by an emitted letter (orphan
  catalog entries stay out of ndjson). Verified on JP p=500 s=500:
  self-loops 8 → 0, distinct 910 destinations 1 → 5, narrative reads
  e.g. `紹介先:佐藤ファミリークリニック。`. FHIR-emit-only,
  byte-identity preserved for non-referral outputs. → **PATCH**.
  Closes #924.
- **Issue #920 — Discharge / outpatient-renewal MedicationRequests
  missing structured dose.** `_build_discharge_medication_request`
  populated `dosageInstruction` with only `route` and free-text
  `dose`; the structured `doseAndRate.doseQuantity` was never
  written, so 91.2% of MedicationRequests (83,506 / 91,532 at
  p=10000) shipped with no numeric dose — a Japanese prescription
  without a dose is legally invalid. Fix parses `item.dose` (e.g.
  `"5mg"`) + `item.frequency` (`"bid"`) via the same
  `parse_dose_string` / `_FREQ_PER_DAY` helpers the inpatient
  `build_dosage_instruction` path uses (single-source parsing).
  Emits `doseAndRate.doseQuantity` when parseable, `timing.repeat`
  when a frequency is available, and `rateQuantity` for IV
  continuous-infusion patterns (`"/h"`, `"continuous"`, `"drip"`);
  unparseable dose → element omitted rather than fabricated
  (`feedback_semantic_correctness_over_coverage`). Two
  `chronic_medications.yaml` entries with empty `dose` from the
  earlier bare-name migration (#442) restored with 添付文書-cited
  defaults (Adoair 250 Diskus 1回1吸入 1日2回, サルタノールインヘラー
  100μg 発作時頓用). JP p=200 s=500 verification: has_dose 8.5% →
  97.9%; residual 2.1% is genuine no-fixed-dose supportive IV /
  vaccine / mEq range strings. Closes #920 and closes #910 (subsumed
  — audit shows anti-thrombotics are already 100% oral in JP output).
- **Issue #925 — Composition.section.entry empty.** At v0.5.0 the
  SOAP-note (34131-3) and JP-CLINS discharge-summary (18842-5)
  Composition builders emitted `section.title` / `section.code` /
  `section.text.div` but never populated `section.entry[]`, so a
  document-first FHIR consumer had no structured link from a
  Composition to its underlying MRs / Observations / Procedures /
  Conditions (37,028 SOAP notes + 668 DS at p=10000). Fix: single
  `_build_encounter_resource_index(entries)` walk in
  `documents/composition.py` buckets already-emitted resources by
  `(encounter.reference, resourceType)`; the index is refreshed in
  `_build_bundle` immediately before the first Composition builder
  fires and threaded through `BundleContext.encounter_resource_index`.
  `_SECTION_ENTRY_TYPES` maps section-title → resourceType-bucket
  (plan → MR+SR+Procedure, objective → Obs+DR, assessment →
  Condition, etc.); narrative-only sections (subjective / HPI / chief
  complaint) stay text-only. JP-CLINS eDS section builder extends
  `_JP_DS_MULTI_ENTRY_TYPES` for 342 / 344 / 444 (333 hospital_course
  intentionally omitted — pinned to `JP_DocumentReference`).
  Encounter-id resolution routes CIF ids through
  `resolve_encounter_id` before lookup with a fall-through so unit
  tests pre-keying the index still work. Zero eligible resources →
  `entry` omitted rather than `entry: []`. JP p=500 s=500 verification:
  34131-3 SOAP 0/1713 → 1713/1713 populated, 18842-5 DS 0/39 → 39/39
  populated; narrative-only slugs (10164-2 HPI etc.) correctly stay
  empty per spec. FHIR-emit-only → **PATCH**. Closes #925.
- **Issue #944 — Coverage.status vs snapshot_date.** Pre-fix,
  `Coverage.status` was hard-coded `"active"` for every per-FY row,
  regardless of whether `period.end` fell before CIF `snapshot_date`
  (FHIR R4 requires "cancelled" for expired coverage). New
  `_derive_coverage_status(period_end, snapshot_date)` helper:
  returns `"cancelled"` iff `period.end < snapshot_date`; boundary
  (`period.end == snapshot_date`) inclusive → still active;
  `snapshot_date is None` defaults to `"active"` (identity-only
  tests / legacy CIF without metadata — backward compatible).
  `_build_coverage_resources` gains an optional `snapshot_date` arg;
  `BundleContext` gains a `snapshot_date` field populated by
  `convert_cif_to_fhir` reading `cif/metadata.json` (soft-failure).
  Verification (JP p=1000 s=500, snapshot 2026-03-31): 1016 Coverage
  → 554 active (FY2025 current) + 462 cancelled (FY2024 expired,
  previously all falsely active). Zero mismatch between period.end
  and status. Closes #944 (remaining part after #934 fixed multi-FY
  + age-gate portions).
- **Issue #941 — Encounter.hospitalization.admitSource +
  dischargeDisposition dual-slot regression.** Reporter measured
  0/703 populated IMP encounters, but the emit path DOES set
  `coding.code` correctly; the visible failure was that
  `coding.display` carried the JP label and the
  `_strip_japanese_display_on_english_only_systems` post-processor
  stripped it (HL7 admit-source / discharge-disposition CodeSystems
  are on the English-only-CS prefix allowlist), while `.text` was
  never populated at emit site. Fix pairs an EN-canonical
  `coding[0].display` (survives HAPI validation AND the strip walker)
  with a locale-resolved `.text` slot per the dual-slot pattern
  documented in `feedback_dual_slot_at_emit_site_not_post_process`.
  Also honours `deceased=True` when the CIF-side discharge_disposition
  is unset — falls back to yaml-configured `deceased_code` (`"exp"`)
  instead of `fallback_code` (`"home"`); defence in depth for
  hospital-mortality analytics. Fallback + deceased codes + JP-CLINS
  ValueSet binding URLs live in
  `clinosim/locale/shared/encounter_disposition_defaults.yaml`.
  JP p=1000 s=500 verification: admitSource populated 0/87 → 87/87;
  dischargeDisposition 0/87 → 82/87 (5 in-progress IMPs correctly
  have no discharge); deaths 5/5 marked `exp`. Emit-only, no CIF
  schema addition, no byte-diff on already-populated `.text` →
  **PATCH**. Closes #941.
- **Issue #945 — Universal post-snapshot event filter.** For
  inpatients whose admission was still open at CIF `snapshot_date`,
  the generator pre-emitted planned future events (nursing notes,
  vitals, MAR, imaging, DR, MR, Composition) with
  `effectiveDateTime` / `date` / `started` AFTER snapshot — 4,798
  leaked event resources at v0.5.0 p=10000, furthest event 28 days
  past snapshot. New `_drop_entries_after_snapshot` universal filter
  placed after the #928 death filter in `_build_bundle`, walks every
  non-dimensional bundle entry, extracts every gating timestamp
  (effectiveDateTime / issued / authoredOn / occurrence / recorded /
  collected / date / performed / started plus Period.start on period
  / effectivePeriod / performedPeriod / occurrencePeriod plus
  DocumentReference.context.period.start), and drops the entry when
  any YYYY-MM-DD prefix exceeds `ctx.snapshot_date` (inclusive on
  snapshot day). `_POST_SNAPSHOT_ALLOWED_RESOURCE_TYPES` whitelists
  Patient / Encounter / Coverage / CareTeam / Practitioner /
  PractitionerRole / Organization / Location / Endpoint / Device /
  Medication — `Encounter.period.end` for open admissions and
  `Coverage.period.end` for active insurance legitimately reach past
  snapshot (#944 already flips Coverage.status). Uses `.start` only
  (not the `.end` mirror the death filter uses) so an infusion begun
  before snapshot with a projected end past snapshot survives. A
  second-pass reference scrubber removes dangling `.result[]` /
  `.section[*].entry[]` / `.hasMember[]` / `.derivedFrom[]` /
  `.basedOn[]` / `.report[]` / `.context.related[]` /
  `MedicationAdministration.request` after cascade-drop (fixed-point
  bounded at 3 passes), closing the 51 dangling references that
  otherwise broke `reference_integrity` on US p=100 shards. Per-type
  drop counts surface via `snapshot_filter_dropped` in `simulator.log`.
  RNG-shape neutral (post-process filter, no draws). JP p=1000 s=500
  verification: 437 event-typed entries with datetime > snapshot →
  0; filter log `{"ClinicalImpression": 51, "Observation": 182,
  "DocumentReference": 204}`. **PATCH** per commit body. Closes #945.
- **Vulture false-positive whitelist for `load_allergens`.**
  Vulture (60% confidence) reported `load_allergens` unused after
  #942 added a sibling `load_allergen_config`, splitting the intent
  path. Both functions are kept (legacy catalog shape vs the new
  NKA + polyallergy blocks) and `load_allergens` is called at
  `engine.py:153` in `allergy_enricher`, imported by two unit
  tests, and documented as public API — whitelist entry added to
  `vulture_whitelist.py`.

### Added

- **Issue #946 — Anthropometric vitals (height / weight / BMI /
  head-circumference).** Pre-fix, not a single body-height /
  body-weight / BMI / head-circumference Observation was emitted in
  v0.5.0 (0 records across 6,389 patients / 1,243,667 Observations),
  breaking BMI analytics, weight-based drug-dose verification,
  pediatric growth-chart consumers, frailty / sarcopenia assessments,
  and 栄養管理計画書 Composition consistency. Per encounter now
  emits four LOINC-coded Observations (`category = vital-signs`):
  8302-2 body height (cm), 29463-7 body weight (kg), 39156-5 BMI
  (kg/m²), 8287-5 head circumference (cm — pediatric only, WHO / AAP
  routine-measurement cutoff age ≤ 3, tunable in yaml). Adults use
  fixed `patient.height_cm` + per-encounter weight drift; pediatric
  values come from per-age × per-sex p50 medians in
  `clinosim/locale/shared/anthropometric_reference.yaml` (WHO /
  MHLW / MEXT for JP; WHO / CDC for US); BMI is computed at emit
  time from emitted height and weight so the triple is internally
  consistent. Per-encounter noise derived via
  `hashlib.sha256(f"{patient_id}|{encounter_id}|<suffix>")` →
  Gaussian quantile through `mpmath.erfinv` (prec=128) — the same
  pattern as `_derive_rh_factor`, RNG-neutral per
  `feedback_rng_neutral_additive_field.md` (master stream untouched).
  All tunables (clamp bounds, pediatric medians, head-circ max age,
  adult-path threshold, per-encounter noise SDs) live in the
  anthropometric_reference.yaml. JP p=1000 s=500 verification:
  8302-2 / 29463-7 / 39156-5 each 3,654 records / 576 patients;
  8287-5 69 records / 12 pediatric patients (age ≤ 3). BMI
  consistency spot-check within ±0.1 rounding. Introduces new
  CIF-independent Observations tied to encounter-time values →
  **MINOR** (v0.6.0) per `feedback_versioning_policy_
  cif_narrative_consistency`. Closes #946.
- **Issue #942 — AllergyIntolerance NKA positive assertion +
  polyallergy.** Pre-fix, 84.9% of patients had zero
  `AllergyIntolerance` records (5,424/6,389 at JP p=1000 s=500) and
  polyallergy was 0% — "absent" was ambiguous between "no known
  allergy" and "not assessed". Every patient now carries at least
  one record. NKA emit uses SNOMED `716186003` "No known allergy"
  with localized `code.text` (`アレルギー歴なし` JP /
  `No known allergies` US), `clinicalStatus=resolved` /
  `verificationStatus=confirmed`; `type` / `category` /
  `criticality` omitted per NKA shape. Bypasses the JFAGY JP-Core
  substitution — NKA is a status code, not a JFAGY allergen.
  Polyallergy: age-conditional conditional probability given ≥ 1
  allergen (child 10% / adult 25% / elderly 55%), +15%
  chronic-illness bonus (C / N18 / D80-D84), 2-4 records with
  `additional_count_weights` (60/30/10). Secondary allergens
  sampled without replacement from the catalog; penicillin biases
  next-allergen category weights toward medication (+20%
  cross-reactivity). All tunables live in
  `allergens.yaml` under `nka` / `polyallergy` / `cross_reactivity`
  blocks (`feedback_constants_live_in_external_config`). RNG shape:
  per-patient sub-RNG via `derive_sub_seed` (SHA256 pattern) —
  master stream untouched, only the `AllergyIntolerance` emission
  stream shifts. Narrative `_build_allergies` collapses a
  single-NKA cohort to the NKDA fallback phrasing rather than
  surfacing "no known allergy" verbatim. p=1000 s=500 verification:
  0 patients with zero records (was 5,424/6,389), polyallergy 4.17%
  overall, elderly 5.21% > adult 3.45%. `AllergyIntolerance` CIF
  reshapes → narrative regeneration required → **MINOR** (v0.6.0).
  Two `test_document_chain*.py` baseline_prevalence expectations
  widened 5-30 → 95-150 (per-patient rate now ≥ 100%; load-bearing
  detections preserved). Closes #942.
- **Issue #943 — Cancer + obstetric service lines.** Closes the
  0-emission gap for oncology and obstetrics and dilutes the I10
  hypertension dominance that skewed the encounter reasonCode
  distribution to 41%. Oncology: five MHLW / SEER-calibrated cancers
  added — C18 colon / C22 liver / C34 lung / C50 breast (F-only) /
  C61 prostate (M-only) — via `chronic_prevalence` in JP + US
  `demographics.yaml` with age gates, quarterly surveillance visits
  in `chronic_followup.yaml` with tumor markers, and representative
  regimens in `chronic_medications.yaml` (Capecitabine/Oxaliplatin,
  Sorafenib/Lenvatinib, Osimertinib/Pemetrexed/Carboplatin,
  Tamoxifen/Anastrozole/Trastuzumab, Bicalutamide/Leuprorelin).
  C22 added to ICD-10 + ICD-10-CM catalogs. Obstetrics: Z34
  (supervision, F 20-44 active-pregnancy proxy) + Z37 (delivery
  outcome marker, F 25-64 past-birth marker); Z34/Z37/Z38 added to
  ICD-10 catalog, Z34.90/Z37.9 to CM catalog; Z34 monthly prenatal
  follow-up with folic acid + iron supplements. I10 dilution:
  `chronic_followup` interval 1 → 4 months (JSH quarterly cadence
  for stable HTN); JP prevalence 0.20/0.50/0.65 → 0.11/0.30/0.40
  by age band; US 0.33 → 0.22. JP p=1000 s=500 verification: cancer
  Conditions 0 → 46, obstetric Conditions 0 → 33 (Z34: 13, Z37:
  20), I10 encounter reasonCode share 41% → 24.7%, chemo/prenatal
  MedicationRequests 0 → 259. Scope limitations tracked in
  follow-up **Issue #957** (deep chemo cycle scheduling — FOLFOX
  infusion days, taxane pre-med; delivery Encounter + mother-baby
  link + newborn Patient generation + Z38 birth event; no radiation-
  therapy Procedure emission K722/K731; no oncology-specific
  Composition). RNG cascade across every seed / country (new
  chronic codes cascade sampling, I10 retuning) → **MINOR**
  (v0.6.0). `test_memoize_hit_bit_identical` xfail loosened to
  `strict=False` — the specific p=100/s=42 fixture no longer
  triggers with the shifted cohort; underlying defect class
  unchanged (other seeds still exhibit it). Fixture updates:
  `test_fhir_family_history` accepts any `C50*` prefix for US
  billable-leaf resolution (`C50.919`);
  `test_anticoag_carryforward` reseeded 49 → 55 (same maintenance
  pattern as sessions 42 / 89 B-3 / 90 determinism / #933 restore).
  Closes #943.
- **Anticoag-carryforward integration test scouted to seed=49** (post
  #933 restore). The B-3 chronic-prevalence restore reshaped the US
  E11.9 / E78 / J44 / N18 marginals, causing seed=45 to lose the
  AFib + 2-admission + newly-started-anticoag candidate; seed=49 is
  the first that retains the fixture (POP-000360). Fixture-only
  change; same maintenance pattern as the seed=42 → 43 migration in
  the v0.5.0 release notes. (Later re-scouted to seed=55 in #956;
  see the Added entry for Issue #943.)

## [0.5.0] - 2026-08-28

**MINOR** — Two independent MINOR drivers folded into this release:

1. B-3 marginal-preserving chronic-condition sampler reshapes
   `chronic_conditions` per patient (Structured CIF change; fresh
   `narrate` required).
2. Cross-platform bit-reproducible RNG variates for byte-identity
   between Mac ARM and x86 Linux (RNG shape changes; fresh CIF+narrate
   required).

Session 89 post-Issue-#854 audit resolutions + session 90 cross-platform
determinism + narrative-review follow-ups (pediatric localization,
per-day lab filter). See
[`docs/reviews/2026-08-28-session-89-post-p1000-audit.md`](docs/reviews/2026-08-28-session-89-post-p1000-audit.md)
and
[`docs/reviews/2026-08-28-cross-platform-determinism.md`](docs/reviews/2026-08-28-cross-platform-determinism.md)
for the per-finding timelines and technical summaries.

### Changed

- Progress-note narrative now filters labs to the correct hospital day
  and adds two new context fields for the LLM. Prior behavior:
  `_render_abnormal_labs` filtered on `lab["day"]` but CIF lab_results
  carry only `result_datetime`, so every day's progress note cited the
  day-0 admission labs verbatim (POP-000021 DKA case: 12 progress notes
  all quoting Glucose 518 / pH 7.18 / HCO3 10.1 despite CIF showing
  day-by-day recovery). New `clinosim/modules/document/narrative/lab_timeseries.py`
  module (5 pure helpers, 17 unit tests) computes day-of-lab from
  `result_datetime - admission_datetime` and exposes:
  * `abnormal_labs_today` — today's measured H / L / critical labs
    (existing key; filter now works)
  * `lab_trend_today` — per today-measured lab: prior value + flag +
    direction (改善 / 悪化 / 不変 / 初回測定 in JA; improving /
    worsening / stable / initial in EN)
  * `lab_current_state` — carry-forward: abnormal labs from earlier
    days not redrawn today, cited with `(day N)` suffix
  Prompt template (JA + EN) rules pin `lab_trend_today` as the ONLY
  authorized source of trend claims (LLM must not invent trend not
  listed). H100 post-fix regen on the DKA case confirms day-3
  progress note now cites day-3 labs with trend words + carry-forward
  of earlier-day abnormals with proper day suffix. **PATCH** — CIF
  byte-identical to pre-fix; only narrative rendering changes.
- Bit-reproducible RNG variates for cross-platform byte-identity.
  ``numpy.random.Generator.beta`` / ``.normal`` / ``.exponential``
  reach ``libm`` for ``log`` / ``exp`` / ``pow`` / ``cos``, and IEEE 754
  mandates correct rounding only for basic arithmetic + ``sqrt`` — not
  for transcendentals. Apple Silicon and x86 Linux ``libm``
  implementations differ at the last few ULP, which shifts every
  downstream ``rng.random()`` cursor. In session s88j-late this drift
  produced 13-file delta and content differences in every "common"
  file when regenerating ``p=10000 s=500`` on Mac vs H100.
  New ``clinosim.determinism`` module reimplements the three variates
  on top of ``rng.random()`` (pure integer arithmetic — bit-identical
  across platforms) and ``mpmath`` transcendentals (pure Python integer
  arithmetic — bit-identical across platforms). Precision constant
  lives in ``clinosim/config/determinism.yaml`` (grand-design
  principle: tunables outside code). A tiny ``_DeterministicRngProxy``
  wraps every ``np.random.default_rng(...)`` at the ten simulator
  entry points; downstream call sites see the same Generator API and
  keep the same signatures, so no domain-code edits were needed for
  the ~81 ``rng.{beta,normal,exponential}`` call sites the codebase
  contains today. Cross-platform byte-identity verified against fresh
  regen on Mac ARM + H100 x86: US p=100 s=42 → 24/24 files identical,
  US p=500 s=42 → 25/25 files identical. RNG shape changes →
  structured CIF regenerates (algorithms differ from numpy's Cheng /
  Ziggurat), narrative CIF regenerates alongside → **MINOR** bump
  under the versioning policy. New dep: ``mpmath>=1.3`` (pure Python,
  ~200 KB).
- Population chronic-condition sampling now preserves marginal prevalence
  (B-3). `demographics.yaml → chronic_prevalence[code][band]` is now
  semantically the target marginal prevalence in the **sampled synthetic
  population** (the pipeline input; the emitted patient cohort skews
  sicker via care-seeking + encounter-emission filters and is by design).
  `clinosim/modules/population/engine.py` rescales per-patient sampling
  probability by the population-expected compound (comorbidity × BMI ×
  smoking) multiplier so `E[final_prev] ≈ base_prev` across the age × sex
  band, while each multiplier still shapes WHICH patients get the
  condition. Discovered via post-Issue-#854 p=1000 audit: under the old
  multiplicative pipeline, chronic marginals over-shot targets by 2-5× on
  cascading-comorbidity codes (JP p=1000 s=42 examples: I25 age 70+ 0.488
  vs target 0.10, E78 age 70+ 0.824 vs 0.45, mean chronic conditions/
  patient 3.24 vs MHLW 65+ 2.3). Post-fix regen at JP p=1000 s=42: I25
  70+ 0.161, E78 70+ 0.520, mean 2.63 — the residual over-shoot is care-
  seeking filter bias which is by design (hospital-catchment skew).
  The previous "reduce base_prev" workaround (Issue #739 for
  E11.9/N18/US T2DM/COPD) was surgical and did not generalize — the
  new engine handles the systematic case with no per-code manual
  tuning. New pure helpers on `population/engine.py`:
  `_target_prev_at_age`, `_bmi_category_probabilities`,
  `_smoking_status_probabilities`, `_expected_lifestyle_multiplier`,
  `_expected_comorbidity_multiplier`. No new tunable constants — all
  inputs come from existing yaml (grand-design principle). The
  Issue #739 base_prev downscales in `chronic_prevalence` are now
  over-compensations against the new engine and will be restored to
  their intended hospital-cohort targets in a follow-up recalibration
  PR (B-3 phase 2). Structured CIF changes on `chronic_conditions`
  list per patient, narrative CIF referencing those records will
  regenerate → **MINOR** bump under the versioning policy.
- Anticoag-carryforward integration test scouted to seed=43 (was 42).
  The B-3 marginal-preserving sampler reshapes chronic conditions
  cohort-wide, so seed=42 no longer contains the required AFib +
  2-inpatient-admissions + newly-started-anticoag fixture; seed=43
  retains one such patient. The test's own docstring already
  authorizes seed migration when the fixture drifts. Fixture-only
  change; no invariant relaxation.

### Docs

- Clarify per-season vs cumulative-record semantics on
  `coverage_by_age_sex` in `clinosim/locale/{jp,us}/immunization_schedule.yaml`
  and add a "Cumulative record vs per-season" section to
  `modules/immunization/README.md` (+ ja). Discovered via post-Issue-#854
  p=1000 audit: raw "% of 65+ patients with ≥1 Immunization record"
  hits ~100%, which looked like a bug against MHLW インフルエンザ 65+
  ~53% (per-season). Per-vaccine per-scheduled-dose measurement on the
  same sample confirms actuals match config within ±5% (flu M 0.503
  vs 0.55, F 0.570 vs 0.58, COVID lifetime M 0.906 vs 0.90, F 0.952 vs
  0.92, PPSV23 M 0.355 vs 0.40, F 0.441 vs 0.42). Aggregate "≥1 record"
  vs per-season MHLW is an apples-to-oranges error — with
  `history_years=10` a moderate per-season rate accumulates to ~1.0
  over the EHR window, which is the correct behavior for a
  hospital-attending elderly patient. No code / config value change.
  → **PATCH** under the versioning policy.
- Clarify hospital-catchment skew on `age_distribution` in
  `clinosim/locale/{jp,us}/demographics.yaml` and add a "Cohort skew vs
  sampled population" section to `modules/population/README.md` (+ ja).
  Discovered via the same p=1000 audit: JP 65+ share in the emitted
  cohort is 48% vs the `age_distribution` config target 30% (Census).
  Root cause is by-design — the `age_distribution` table is the
  **sampled population** target (matching each country's Census), then
  the care-seeking threshold + encounter-emission gate filter out
  non-visiting persons, so the emitted patient cohort skews
  elderly-heavy by construction. Against MHLW 患者調査 2020 (65+ ≈ 56%
  of hospital patients) the emitted cohort is far closer than against
  Census. Do NOT re-weight `age_distribution` to make the cohort match
  Census — that would break the general-population sampling contract
  depended on by comorbidity / life-expectancy / seasonal-risk
  calculations. No code / config value change. → **PATCH**.
- Add `scripts/audit_realworld_stats_jp.py` — JP cohort vs real-world
  statistics audit with corrected benchmarks (MHLW 患者調査 for age,
  per-vaccine per-scheduled-dose for immunization, MHLW / JCS / JDS /
  JSN guideline prevalence for chronic diseases). Replaces the ad-hoc
  scratchpad script the p=1000 audit used. Registered under
  "Data-refresh helpers" in `scripts/README.md`. Diagnostic only; not
  a hard gate. → **PATCH**.
- Clarify `AllergyIntolerance` scope in
  `clinosim/modules/allergy/reference_data/allergens.yaml`,
  `modules/allergy/README.md` (+ ja), and
  `scripts/audit_realworld_stats_jp.py` (B-4). The 15% overall gate
  models the fraction of patients with a **clinically documented FHIR
  `AllergyIntolerance`** (medication + severe food + environmental) —
  a narrower surface than "any allergic disease". Hay fever (J30) and
  food intolerance (K90.4) emit as `Condition`, not `AllergyIntolerance`.
  Post-Issue-#854 p=1000 audit flagged 13.5% actual vs 30-40% (MHLW
  アレルギー疾患実態調査) as a deviation — that comparison was
  apples-to-oranges: MHLW 30-40% includes J30 + K90.4 which are
  out-of-scope for `AllergyIntolerance`. The correct band for clinically
  documented `AllergyIntolerance` in real hospital EHR is 10-20%, and
  the current 15% sits comfortably in that range. Documentation-only;
  no code / config value change. → **PATCH** under the versioning policy.

### Fixed

- Chronic-condition age gate on implied-chronic assignment
  (`simulator/inpatient.py::_IMPLIED_CHRONIC_BY_DISEASE`). Discovered
  via post-Issue-#854-close p=500 review: 6- and 7-year-old male
  patients were being assigned `J44` (COPD) as a chronic condition
  because the `bacterial_pneumonia` → COPD implied-chronic path had
  only a sex gate (`N40` BPH male-only), no age gate. Now every
  age-restricted ICD code (COPD / CKD / heart failure / dementia /
  Parkinson's / atrial fibrillation / hypertension / Type 2 DM /
  osteoporosis / knee OA / BPH / chronic liver disease) has a
  minimum-age gate mirroring the `demographics.yaml chronic_prevalence`
  lower bounds. Verified against JP p=500 s=42 regen: 61 minors, 0
  age-restricted chronic conditions (previously 2 minors had J44 COPD).
  Structured CIF changes on affected minor records (`chronic_conditions`
  list); narrative CIF referencing those records will regenerate —
  **MINOR** bump under the new versioning policy.
- `Composition.section.code` now carries `.text` alongside the LOINC
  `.coding[].display`. Discovered via post-Issue-#854-close p=500
  review: 11,050 section codes on the JP p=500 s=42 sample had their
  `coding.display` (JP) stripped by the
  `_strip_japanese_display_on_english_only_systems` post-process
  walker but no sibling `.text` on the CodeableConcept, so JP
  consumers were left with a bare LOINC code and no user-facing
  label. Fixed at both emit sites:
  `_build_composition_generic` (general Composition) and
  `_build_radiology_imaging_report_composition` (imaging report
  Findings / Impression sections). Now the dual-slot pattern
  (`coding.display` may be stripped by locale walker; `text` carries
  the locale display) holds throughout. Verified against JP p=200
  s=42 regen: 4,278 stripped-display section codes, 100% have JP
  `.text`. FHIR-emit-only, structured CIF unchanged, narrative CIF
  unaffected → **PATCH** under the new versioning policy.
- Discharge MedicationRequest `identifier:rpNumber` is now `"2"` on
  inpatient encounters (was uniformly `"1"`, colliding with the
  inpatient-orders MR set that also uses `"1"`). Discovered via
  post-Issue-#854-close p=500 review: on JP p=500 s=42, 42 (patient,
  encounter) groups had duplicate `(rpNumber, orderInRp)` pairs because
  the discharge builder restarted its `orderInRp` counter from `1`
  while sharing `rpNumber=1` with the inpatient MRs, so an inpatient
  MR and a discharge MR would both claim `(rp=1, orderInRp=3)`. Model
  the discharge prescription as a distinct Rp group (`rpNumber=2`) on
  inpatient encounters — the JP-CLINS `rpNumber` semantic
  ("処方箋内 RP 番号 / 剤番号") accommodates multiple Rp groups within
  one prescription. Outpatient renewal has no inpatient orders to
  collide with, so `rpNumber=1` remains correct there. Verified against
  JP p=500 s=42 regen: 0 duplicate `(rpNumber, orderInRp)` pairs
  (previously 42 groups). FHIR-emit-only, structured CIF unchanged,
  narrative CIF unaffected → **PATCH** under the new versioning policy.
- mb-org / mb-sus Observation `.category[].text` is now populated
  (previously absent, so the JP `_normalize_jp_observation_category`
  post-process swap left the category with a bare `{system, code}`
  pair and no user-facing label). Discovered via post-Issue-#854-close
  p=500 review: 59/87,627 (0.07%) `JP_SimpleObservationCategory_CS`
  category entries lacked `.text` — all localized to microbiology
  Observations (mb-org / mb-sus) whose emitter set `coding.display` but
  omitted the parent CodeableConcept `.text`. Now `microbiology.py`
  populates `.text` on the lab category with a locale-appropriate
  label ("検査" on JP, "Laboratory" on US) so the post-process
  normalizer carries it forward. Verified against JP p=200 s=42 regen:
  all 46/46 mb-* Observation categories have `.text` (previously all
  46 lacked it). FHIR-emit-only, structured CIF byte-unchanged,
  narrative CIF unaffected → **PATCH** under the new versioning
  policy.

### Changed

- `MedicationAdministration.id` now emits opaque `mar-<12hex>` (16
  chars, fixed) instead of the pre-fix compound
  `mar-{encounter_id or patient_id}-{index:05d}`. Discovered via the
  post-Issue-#854-close p=500 review — MA was overlooked in the
  original sweep. New PUBLIC constants
  `MEDICATION_ADMINISTRATION_ID_PREFIX = "mar-"` and
  `MEDICATION_ADMINISTRATION_KEY_SYSTEM = "urn:clinosim:identifier:medication-administration-key"`;
  the compound structural key round-trips on
  `MedicationAdministration.identifier[]` alongside any JP-specific
  `rpNumber` / `orderInRp` identifiers. MA is a leaf in the FHIR
  reference graph — no other resource type references MA by id — so
  this is a stand-alone-tail migration with no downstream cascade.
  Byte-output changes on MA NDJSON only (~20k records on JP p=500
  s=42 sample, none on other resource types); structured CIF is
  byte-unchanged and narrative CIF is unaffected — PATCH under the
  new versioning policy. (Post-#854 remainder.)
- **Issue #854 CLOSE** — `Patient.id` now emits opaque `pt-<12hex>`
  (15 chars, fixed) instead of the pre-#854 simulation-generation slug
  `POP-{n:06d}`. The `POP-{n}` slug is preserved on
  `Patient.identifier[]` under the new PUBLIC
  `POPULATION_SLUG_KEY_SYSTEM = "urn:clinosim:identifier:population-slug"`
  so consumers who key on the human-readable generation id (iris4h-ai
  clinical cockpit, integration tests) can still recover it. 44
  downstream cross-ref sites across 29 modules (Observation /
  MedicationRequest / MedicationAdministration / Procedure /
  DiagnosticReport / ImagingStudy / DocumentReference / Composition /
  ClinicalImpression / CareTeam / Condition / AllergyIntolerance /
  Encounter / Immunization / FamilyMemberHistory / Coverage / HAI /
  blood_type / smoking_alcohol / care_level / inline_bb) route through
  the shared `patient_ref(cif_patient_id)` helper — never string-format
  the CIF value directly. Design decision rationale: 4-axis eval (data
  quality, clinical consistency, module responsibility decomposition,
  OSS code structure) all favour full opaque; narrative CIF is
  patient-id-agnostic by design (fact_extractor emits `patient.age` /
  `patient.sex` / chronic conditions, never patient_id), so no narrate
  regen is required. External URL contract breakage
  (`/Patient/POP-000002` → `/Patient/pt-<hex>`) is a consumer/deploy
  concern (iris4h-ai UI update) tracked separately. Byte-output changes
  on Patient NDJSON + every downstream slice carrying a
  `.subject.reference` (~all resource types on JP p=10000 s500 sample);
  structured CIF unchanged, narrative CIF unaffected — **PATCH** under
  the new versioning policy. Row 18 CLOSES Issue #854. (Continues
  PR #857 / #863 / #867 / #868 / #869 / #878 / #879 / #880 / #881 /
  #882 / #883 / #884 / #885 / #886 / #887 / #888 / #889 / #890 / #892
  opaque-id pattern.)
- Bucket C patient-scoped stand-alone `Resource.id` now emits opaque
  `{prefix}-<12hex>` (fixed length) for all four resource kinds:
  `Immunization.id` = `imm-<12hex>` (16 chars),
  `FamilyMemberHistory.id` = `fmh-<12hex>` (16 chars),
  `Coverage.id` = `cov-<12hex>` (16 chars),
  `AllergyIntolerance.id` = `allergy-<12hex>` (20 chars). All four are
  stand-alone in the FHIR reference graph (no downstream cross-ref
  cascade), so no callers need updating. Structural keys round-trip on
  each resource's `.identifier[]` under per-kind
  `urn:clinosim:identifier:{kind}-key` systems. `Coverage.identifier[]`
  gains the structural-key entry as a second slot alongside the
  pre-existing JP member-id composite (`保険者番号:記号:番号:枝番`) —
  both consumers keep working. Byte-output changes on Immunization
  (~29k) / FamilyMemberHistory (~19k) / Coverage (~7k) /
  AllergyIntolerance (~1k) records on the JP p=10000 s500 sample.
  Structured CIF is byte-unchanged (opaque-id migration is FHIR-emit
  only) and narrative CIF is unaffected, so under the new versioning
  policy this ships as a PATCH bump. Row 18 (`Patient.id`) deferred
  — the external identity contract with downstream consumers
  (iris4h-ai, HAPI validator, integration tests) requires a maintainer
  design decision. (Issue #854 Bucket C rows 14-17; continues PR #857 /
  #863 / #867 / #868 / #869 / #878 / #879 / #880 / #881 / #882 / #883 /
  #884 / #885 / #886 / #887 / #888 / #889 / #890 opaque-id pattern.)

## [0.4.1] - 2026-08-27

Issue #854 Bucket A + Bucket B closeout — every per-patient-event FHIR
`Resource.id` now emits an opaque `sha256`-derived short id, and every
downstream cross-reference resolves via a shared writer-owned helper. The
pre-#854 compound key is preserved on each resource's `.identifier[]`
under a per-kind `urn:clinosim:identifier:{resource}-key` system for
round-trip. **LEAK ROOT** (`Encounter.id`) migrated — 33 emit sites
across 22 modules re-routed through the shared `encounter_ref` helper.

The change is FHIR-emit-only: structured CIF is byte-unchanged and the
narrative CIF from the previous `narrate` run stays valid. Under the
CIF↔narrative-CIF-consistency versioning policy (documented above) this
ships as PATCH.

Byte-diff across the JP p=10000 s500 sample is comprehensive on the FHIR
side (every resource type that carries a compound-id or an
`encounter.reference`); determinism holds by construction (SHA-256 is
deterministic, same `(seed, config)` → identical opaque ids across runs).

Remaining opaque-id work (`Patient.id` — row 18 of the plan) is deferred
— it requires a maintainer design call on external identity.

Note: this release was initially tagged as v0.5.0 on 2026-08-27 before
the CIF↔narrative-CIF-consistency versioning policy was formally
documented. The v0.5.0 tag has been retracted from remote and the
release renumbered to v0.4.1 to align with the new policy.

### Changed

- **LEAK ROOT** — `Encounter.id` now emits opaque `enc-<12hex>` (16 chars,
  fixed) instead of the pre-#854 shape `ENC-POP-{patient}-{encounter}`
  (~24-30 chars, plus optional `EMER`/`OP`/`-ED` suffixes). Every
  downstream cross-reference site (Observation / MedicationRequest /
  MedicationAdministration / Procedure / DiagnosticReport / ImagingStudy /
  DocumentReference / Composition / ClinicalImpression / CareTeam /
  Condition / AllergyIntolerance / Specimen — 33 emit sites across 22
  modules) now routes through the shared `encounter_ref(cif_encounter_id)`
  / `resolve_encounter_id(cif_encounter_id)` helpers exported by
  `clinosim.modules.output.fhir_r4.encounters.encounter`. New PUBLIC
  constant `ENCOUNTER_KEY_SYSTEM = "urn:clinosim:identifier:encounter-key"`
  carries the pre-#854 CIF `encounter_id` on `Encounter.identifier[]` for
  round-trip. Synth-ED bridge encounters (structural key
  `{IMP_id}-ED`, materialised at `lib/inline_bb.py` when the IMP has
  `admit_source=EMD`) also flip to opaque; `lib/ed_reattribution.py`
  computes both IMP and bridge opaque targets via the resolver so the
  ED→IMP routing walker keeps matching correctly. Byte-output changes on
  Encounter NDJSON + every downstream slice that carries an
  `encounter.reference` (~all resource types on JP p=10000 s500); MINOR
  bump still batched at v0.5.0. (Issue #854 Bucket B — PR-encounter;
  continues PR #357 / #863 / #867 / #868 / #869 / #878 / #879 / #880 /
  #881 / #882 / #883 / #884 / #885 / #886 / #887 / #888 / #889 opaque-id
  pattern.)
- Lab `Observation.id` now emits opaque `lab-<12hex>` (16 chars, fixed)
  instead of the pre-#854 compound `lab-{encounter_id}-{idx:04d}` (~33
  chars). `DiagnosticReport.result[]` references funnel through the same
  `lab_observation_id(enc_id, idx)` resolver the writer uses, so
  reference-integrity is preserved by construction. The pre-#854 compound
  key is round-tripped on `Observation.identifier[]` under the new
  `urn:clinosim:identifier:lab-observation-key` system so consumers can
  recover the source-path metadata without string-parsing the id. Byte-
  output changes on the lab-`Observation` NDJSON slice (~4,267 records
  on the p=200 sample, ~243,543 records on the JP p=10000 s500 sample);
  MINOR bump will be batched with the rest of the Bucket A row 4 sweep
  (`obs-vs` / `obs-standalone` / `obs-microbiology`) at v0.5.0.
  (Issue #854 Bucket A row 4 — PR-obs-lab; continues PR #357 / #863 /
  #867 / #868 / #869 opaque-id pattern.)
- Vital-sign / GCS / NEWS2 `Observation.id` now emits opaque
  `vs-<12hex>` (15 chars), `gcs-<12hex>` (16 chars), `news2-<12hex>`
  (18 chars) instead of the pre-#854 compounds
  `vs-{enc_or_patient}-{index:04d}-{suffix}` (~33-42 chars),
  `gcs-{enc_or_patient}-{i}`, `news2-{enc_or_patient}-{i}`. Three new
  PUBLIC key-system URIs — `urn:clinosim:identifier:vital-sign-observation-key`
  (one system covers all 4 vs-* emit sites: per-parameter vitals,
  BP-panel, AVPU `loc`, supplemental-oxygen `o2`),
  `urn:clinosim:identifier:gcs-score-observation-key`, and
  `urn:clinosim:identifier:news2-score-observation-key` — carry the
  pre-#854 compound structural key on `Observation.identifier[]` for
  round-trip. All three families are stand-alone (no cross-reference
  cascade). Byte-output changes on ~15,314 vs / 3,989 gcs / 3,989 news2
  Observation records on the p=200 sample (~827,244 vs + 211,928 gcs +
  211,928 news2 on the JP p=10000 s500 sample); MINOR bump still batched
  at v0.5.0. (Issue #854 Bucket A row 4 — PR-obs-vs; continues PR #857 /
  #863 / #867 / #868 / #869 / #878 opaque-id pattern.)
- `Composition.id` now emits opaque `comp-<12hex>` (17 chars, fixed)
  across both emit paths (general via `_build_composition_generic` +
  radiology via `_build_imaging_report_composition`). Composition.identifier
  is 0..1 in FHIR R4 and JP-CLINS eDS/eReferral pins its `.system` to the
  JP resource-instance URI, so a structural-key round-trip identifier
  cannot be attached — callers needing the pre-#854 id must derive it
  deterministically via `_resolve_composition_id(structural_key)`; the
  existing single `Composition.identifier.value` slot continues to carry
  the opaque `.id`. Structural keys:
    - general: pre-#854 id body (CIF-doc-id body with `doc-` prefix
      stripped)
    - radiology imgrpt: `{encounter_id}-imgrpt-{seq}`
  Cross-reference migrated: `DocumentReference.relatesTo[].target.reference`
  in the health-checkup DR builder now routes through the shared
  `_resolve_composition_id` helper. Byte-output changes on the
  Composition NDJSON slice (~969 records on p=200 JP, ~51,967 records
  on JP p=10000 s500); MINOR bump still batched at v0.5.0. (Issue #854
  Bucket B — PR-composition; continues PR #857 / #863 / #867 / #868 /
  #869 / #878 / #879 / #880 / #881 / #882 / #883 / #884 / #885 / #886
  opaque-id pattern.)
- `DocumentReference.id` now emits opaque `doc-<12hex>` (16 chars, fixed)
  instead of the pre-#854 compound `doc-{encounter_id}-{task_type}` set
  on the CIF-side `doc.document_id`. New PUBLIC constant
  `DOCUMENT_REFERENCE_KEY_SYSTEM = "urn:clinosim:identifier:document-reference-key"`
  carries the pre-#854 structural key on `DocumentReference.identifier[]`
  alongside the pre-existing `urn:clinosim:documentreference-id`
  identifier. Cross-references migrated: `DR.relatesTo[].target.reference`
  (sibling DR chain for `appends`) routes through the new
  `document_reference_id_for_cif_doc_id` helper; `Composition.section[].entry`
  populated by `_bb_compositions`' `enc_to_free_text` precomputed map,
  now stores the OPAQUE id instead of the CIF-doc-id compound. The CIF-
  side `doc.document_id` field itself is unchanged. Byte-output changes
  on the DocumentReference NDJSON slice + every cross-ref site (~904
  records on p=200 JP, ~57,166 records on JP p=10000 s500); MINOR bump
  still batched at v0.5.0. (Issue #854 Bucket B — PR-document-reference;
  continues PR #857 / #863 / #867 / #868 / #869 / #878 / #879 / #880 /
  #881 / #882 / #883 / #884 / #885 opaque-id pattern.)
- `ImagingStudy.id` now emits opaque `imgst-<12hex>` (18 chars, fixed)
  instead of the pre-#854 compound `imgst-{encounter_id}-{idx}` set on
  the CIF-side `study.study_id`. New PUBLIC constant
  `IMAGING_STUDY_KEY_SYSTEM = "urn:clinosim:identifier:imaging-study-key"`
  carries the pre-#854 structural key on `ImagingStudy.identifier[]`
  alongside the pre-existing `urn:dicom:uid` identifier. Cross-references
  (`DiagnosticReport.imagingStudy[]`, `DR.media[].link`) migrated to
  route through the shared `imaging_study_id_for_cif_study_id` helper —
  every reference site derives the opaque id from the same CIF
  `study.study_id` the writer uses, byte-consistent by construction.
  The CIF `study.study_id` field itself is unchanged (`imgst-{enc}-{idx}`),
  preserving the 1:1 pairing with `report.report_id = imgrpt-{enc}-{idx}`
  that consumers rely on for radiology-report ↔ study joining. Byte-
  output changes on the ImagingStudy NDJSON slice + every cross-ref
  site (~65 records on p=200 JP, ~4,735 records on JP p=10000 s500);
  MINOR bump still batched at v0.5.0. (Issue #854 Bucket B —
  PR-imaging-study; continues PR #857 / #863 / #867 / #868 / #869 /
  #878 / #879 / #880 / #881 / #882 / #883 / #884 opaque-id pattern.)
- `DiagnosticReport.id` now emits opaque across all 3 emit paths — each
  family keeps its historical prefix so consumers filtering by
  `.startswith("dr-mb-")` / `.startswith("imgrpt-")` keep working:
  lab-panel `dr-<12hex>` (15 chars), microbiology `dr-mb-<12hex>` (18
  chars), radiology `imgrpt-<12hex>` (19 chars). Three PUBLIC key-system
  URIs (`urn:clinosim:identifier:lab-panel-diagnostic-report-key` /
  `mb-diagnostic-report-key` / `radiology-diagnostic-report-key`) carry
  the pre-#854 compound structural key on `DiagnosticReport.identifier[]`
  for round-trip. DR is a leaf resource on the p=200 sample (nothing
  references DR.id back) so no cross-ref cascade guard needed — the
  `imaging_report.py` Composition builder still uses the CIF-side
  `report.report_id` (unchanged) for seq extraction. Byte-output changes
  on the DR NDJSON slice (~715 records on p=200 JP, ~42,514 records on
  JP p=10000 s500); MINOR bump still batched at v0.5.0. (Issue #854
  Bucket B — PR-diagnostic-report; continues PR #857 / #863 / #867 /
  #868 / #869 / #878 / #879 / #880 / #881 / #882 / #883 opaque-id
  pattern.)
- `Condition.id` now emits opaque `cond-<12hex>` (17 chars, fixed) instead
  of the pre-#854 compounds `cond-{encounter_id}-primary` (encounter-
  diagnosis path) and `cond-chronic-{patient_id}-{i:02d}` (chronic
  problem-list path). New PUBLIC constant `CONDITION_KEY_SYSTEM =
  "urn:clinosim:identifier:condition-key"` carries the pre-#854
  structural key on `Condition.identifier[]` for round-trip. Resolver
  helpers `encounter_primary_condition_id` / `chronic_condition_id` /
  `_resolve_condition_id` in `conditions/primary_ref.py` — the existing
  `primary_condition_ref()` / `primary_condition_ref_from_codes()` public
  helpers now return the opaque id, so every downstream reader that goes
  through them (Encounter.reasonReference + Encounter.diagnosis[] +
  Procedure.reasonReference + MedicationRequest.reasonReference +
  ClinicalImpression.finding[] + Composition.section[].entry via the
  precomputed enc_to_primary_cond map) inherits opaque cross-refs
  automatically. Four inline compound builders migrated
  (procedures.py fallback, encounter.py chronic-fan-out,
  composition.py unit-test fallback). Byte-output changes on the
  Condition NDJSON slice + every cascade site (~776 records on p=200 JP,
  ~39,179 records on JP p=10000 s500); MINOR bump still batched at
  v0.5.0. Largest single Bucket B PR by touched-file count. (Issue #854
  Bucket B — PR-condition; continues PR #857 / #863 / #867 / #868 /
  #869 / #878 / #879 / #880 / #881 / #882 opaque-id pattern.)
- `Specimen.id` now emits opaque `spec-<12hex>` (17 chars, fixed) instead
  of the pre-#854 compounds `spec-{enc or patient_id}-{i}` (microbiology
  cultures) and `spec-lab-{obs_id_body}` (companion post-process). Both
  producers — `labs/microbiology.py::_bb_microbiology` and
  `post_process/specimen.py::_build_companion_specimen` — funnel through
  a shared `_resolve_specimen_id` resolver. New PUBLIC constant
  `SPECIMEN_KEY_SYSTEM = "urn:clinosim:identifier:specimen-key"` carries
  the pre-#854 structural key on `Specimen.identifier[]` for round-trip
  (existing `urn:clinosim:specimen-id` clinosim-internal identifier
  preserved alongside; existing `urn:clinosim:identifier:hai-event-id`
  HAI identifier on microbiology Specimens preserved). Cross-references
  (`Observation.specimen`, `DiagnosticReport.specimen[]`) receive
  `spec_id` via variable propagation from the emit site, so
  reference-integrity is preserved by construction — no cross-ref site
  needs touching. Byte-output changes on the Specimen NDJSON slice
  (~4,271 records on p=200 JP sample, ~243,803 records on JP p=10000 s500
  per Issue #854); MINOR bump still batched at v0.5.0. This is the first
  per-type PR of Bucket B. (Issue #854 Bucket B — PR-specimen; continues
  PR #857 / #863 / #867 / #868 / #869 / #878 / #879 / #880 / #881
  opaque-id pattern.)
- Microbiology `mb-org-*` (organism isolate) and `mb-sus-*` (per-antibiotic
  susceptibility) `Observation.id` now emit opaque `mb-org-<12hex>` /
  `mb-sus-<12hex>` (19 chars each, fixed) instead of the pre-#854 compounds
  `mb-org-{enc or patient_id}-{i}` / `mb-sus-{enc or patient_id}-{i}-{j}`.
  Two new PUBLIC key-system URIs — `urn:clinosim:identifier:mb-organism-observation-key`
  and `urn:clinosim:identifier:mb-susceptibility-observation-key` — carry
  the pre-#854 compound structural key on `Observation.identifier[]` for
  round-trip. `DiagnosticReport.result[]` cross-references funnel through
  the same resolvers so the reference edge stays byte-consistent by
  construction (same reference-integrity guard as PR #878 lab). The
  existing `HAI_EVENT_ID_SYSTEM` identifier is preserved alongside the
  structural-key identifier (HAI cross-ref audit path still works).
  Closes Bucket A row 4 for all Observation families (4 PRs total —
  lab / vs+gcs+news2 / stand-alones / microbiology). Byte-output changes
  on ~12 records on the p=200 sample (~1k on JP p=10000 s500); MINOR
  bump still batched at v0.5.0. (Issue #854 Bucket A row 4 —
  PR-obs-microbiology; continues PR #857 / #863 / #867 / #868 / #869 /
  #878 / #879 / #880 opaque-id pattern.)
- 13 stand-alone `Observation.id` families now emit opaque `<prefix>-<12hex>`
  instead of the pre-#854 compounds. Nursing: `braden-*` / `morse-*` /
  `barthel-*` / `intake-*` / `urine-*` / `output-*`. Demographics + SDOH:
  `blood-abo-*` / `blood-rh-*` / `smoking-*` / `alcohol-*` /
  `occupation-*`. Encounter + condition: `carelevel-*` / `codestatus-*`.
  Each family owns its own PUBLIC `urn:clinosim:identifier:<kind>-observation-key`
  URI carrying the pre-#854 compound structural key on
  `Observation.identifier[]` for round-trip. All 13 families are
  stand-alone (no cross-reference cascade). Byte-output changes on
  ~5,845 records on the p=200 JP sample (~40k on JP p=10000 s500); MINOR
  bump still batched at v0.5.0. This closes Bucket A row 4 alongside
  PR-obs-lab / PR-obs-vs / PR-obs-microbiology. (Issue #854 Bucket A row
  4 — PR-obs-standalone; continues PR #857 / #863 / #867 / #868 / #869 /
  #878 / #879 opaque-id pattern.)

## [0.4.0] - 2026-08-26

MINOR bump — 4 opaque-id refactors (Device / DUS / Procedure / ServiceRequest + basedOn cascade)
change `Resource.id` byte-output for the same seed, and `Order.clinical_intent_ja` is a new
CIF-side field. Per the determinism guarantee at the top of this file, MINOR is required.

Cumulative volume impact on the JP p=10000 s500 sample:
- 5 opaque-id refactors (this + #863 in v0.3.0): 100 % of `.id` on 5 resource kinds (Device / DUS / Procedure / SR / MR) now `<prefix>-<12hex>`; 0 dangling cross-refs on 336,510+ links
- 4 JA localization fixes (#870 / #871 / #872 + #862): ~290k `.text` fields (mostly SR.reasonCode) shift from English to Japanese where writers were migrated
- 5 CIF-quality fixes (#846 / #848 / #850 / #851 / #852): DR conclusionCode consistency, no double-admission, day-0 first dose, MA.dosage backfill, medication `.text` multi-word JA

### Changed

- **`ServiceRequest.id` is now opaque + cross-references (`DR.basedOn`, `Observation.basedOn`, `ImagingStudy.basedOn`) resolve through the shared helper** (Issue #854 Bucket A, row 1 — 274,806 records, second-largest volume after Observation). Extends the opaque-id pattern (PR #357 → #863 → #867 → PR #868) to ServiceRequest. Pre-#854 shape: `sr-{order_id}` for stand-alone lab / imaging orders (`sr-ORD-ENC-POP-000012-...`, up to 53 chars — Bucket A row 1 max in Issue #854) and `sr-{encounter_id}-{panel_key}-{N}` for panel lab orders (`sr-enc1-CBC-1`). Post-#854 shape: `sr-<12hex>` (15 chars, fixed) for all paths. New module-private helper `_resolve_service_request_id(structural_key)` in `clinosim/modules/output/fhir_r4/labs/service_request.py` — structural key = pre-#854 SR id body without the `sr-` prefix (i.e. `order_id` for stand-alone, `{encounter_id}-{panel_key}-{N}` for panel). New PUBLIC constant `SERVICE_REQUEST_KEY_SYSTEM = "urn:clinosim:identifier:service-request-key"` for the identifier[] round-trip. `order_to_sr_id` now internally computes the structural key via a new module-private `_order_to_sr_structural_key(order, panel_counter)` split-out helper (single source of truth for the compound derivation) then passes it through the resolver — every caller (DR.basedOn via `_sr_ids_for_group`, Observation.basedOn via direct `order_to_sr_id` call, panel bucketing in `_bb_service_requests`) automatically inherits opaque behavior. Two direct-string readers explicitly updated to use the resolver: `imaging_study.py::_build_imaging_study.basedOn` and `diagnostic_report.py:radiology_dr.basedOn`. Both emit sites (`_build_standalone_sr` for lab standalone / `_build_imaging_sr` for imaging / `_build_panel_sr` for panel) call the resolver and populate `identifier[]` with the structural-key round-trip alongside the pre-existing PLAC placer identifier (`_build_sr_skeleton` extended to always append the structural-key entry — `placer_value` doubles as the structural key input). `_build_panel_sr` signature extended with `panel_counter` so `placer_value` can be rebuilt from the anchor Order (was: `placer_value = sr_id[len(SR_ID_PREFIX):]`, which post-#854 would strip to the opaque hex — now the human-readable panel key is preserved for hospital ordering systems). Downstream: `modules/order/audit.py:155` `.startswith(SR_ID_PREFIX)` gate still fires correctly (`sr-<12hex>` still starts with `sr-`); `audit/axes/clinical.py` `.removeprefix("ServiceRequest/")` walkers are id-shape-agnostic — no changes needed. `modules/order/audit.py::_build_order_proof` panel-SR detection updated to consult `ServiceRequest.identifier[]` under `SERVICE_REQUEST_KEY_SYSTEM` (since the panel-name substring no longer lives in the opaque id). Visible effects on the JP p=10000 s500 sample: (a) `ServiceRequest.id` length drops from up to 53 chars to a fixed 15, giving 49 chars of headroom under FHIR R4's 64-char cap. (b) Patient identifier no longer leaks into `ServiceRequest` URLs. (c) All 3 downstream cross-referencing resources — 42,514 `DiagnosticReport.basedOn`, 1,580,109 `Observation.basedOn`, 4,735 `ImagingStudy.basedOn` — automatically match the opaque `.id` by construction (no dangling references possible). Byte output changes across ServiceRequest + DR + Observation + ImagingStudy NDJSON — MINOR-bumpable at next release. Test coverage: existing `tests/unit/output/test_fhir_service_request.py`, `test_fhir_service_request_imaging.py`, `test_fhir_observations_basedon.py`, `test_fhir_radiology_dr.py`, `test_fhir_diagnostic_report_basedon.py`, `test_fhir_imaging_study.py` updated to compare `.id` and cross-refs via `_resolve_service_request_id(<structural_key>)` calls instead of literal `sr-{compound}` shapes (16+ assertion sites across 6 files). `tests/unit/test_diagnostic_report_panels.py::_order` factory hardened to set `order_id` (pre-#854 the factory relied on the tolerant fall-through that emitted meaningless `sr-`; post-#854 `derive_opaque_id` correctly rejects empty structural keys). `tests/unit/test_imaging_inference.py` literal-id assertion swapped for a resolver-driven expected value. 1,022 existing `tests/unit/output/` tests still pass; 4495 whole-tree unit tests still pass. P=200 seed=500 sim + FHIR emit verify: 4,552 SR records, all opaque (non-opaque = 0, missing structural-key ident = 0), 5,744 downstream `basedOn` cross-refs (1,412 DR + 4,267 Observation + 65 ImagingStudy) resolve without a single dangling reference. Third per-type PR of Issue #854 Bucket A per the recipe in `docs/plans/2026-08-25-issue-853-854-non-hai-mr-opaque-id.md` Appendix A row 3. Final remaining Bucket A row: Observation (1.58M records) — land as the immediate follow-on to close the "intermediate deploy carries mismatched-shape basedOn window" the plan warned about.
- **`Procedure.id` is now opaque across every emit path** (Issue #854 Bucket A, row 2). Extends the opaque-id pattern (PR #357 → #863 → #867) to `Procedure`. Three distinct emit sites all resolve through the SAME `_resolve_procedure_id` shared helper: `procedures.py::_build_procedure` (CIF-driven surgery/bedside/rehab, sample pre-#854 id `ENC-POP-000003-635459597438-PROC-POP-000003-002` — note the **patient id embedded twice** per Issue #854), `inline_bb.py::_bb_procedures` (order-derived, sample pre-#854 `proc-order-ORD-ENC-POP-000004-346099516150-ED-T0` up to 58 chars = Bucket A row 2's max), and `oxygen_therapy.py` (O2 procedures, sample pre-#854 `proc-o2-ENC-POP-000170-152552432067` with a 3-way fallback chain on order_id / enc_id / patient_id-seq). Post-#854 all three emit `proc-<12hex>` (17 chars, fixed). Each callers composes its own source-path-specific structural key (preserving the encounter-scoping property in the CIF path — `{enc_id}-{procedure_id}` — and the source-slot property in the order / O2 paths); the resulting compound is preserved on `Procedure.identifier[]` under a new PUBLIC constant `PROCEDURE_KEY_SYSTEM = "urn:clinosim:identifier:procedure-key"` via `wrap_as_identifier`, computed via `structural_key_system()` from the Phase-1a foundation (`clinosim/modules/output/fhir_r4/lib/ids.py`). No new foundation code. `Procedure.reasonReference[]` continues to point at `Condition/*` — those ids stay compound (Bucket B) until a future PR migrates Condition. Visible effects on the JP p=10000 s500 sample: (a) `Procedure.id` length drops from up to 58 chars (Bucket A row 2 ceiling) to a fixed 17, giving 47 chars of headroom under FHIR R4's 64-char cap. (b) Patient identifier no longer leaks into `Procedure` URLs, matching the "Resource.id is opaque" intent PR #357 established for antibiotic MR. (c) The "patient id embedded twice" anti-pattern (Issue #854 explicitly called out) is gone. Byte output changes across the Procedure NDJSON — MINOR-bumpable at next release. Test coverage: new file `tests/unit/output/test_fhir_procedure_opaque_id_854.py` (10 cases pinning the resolver contract, canonical PROCEDURE_KEY_SYSTEM URI, and `_build_procedure` emit path — CIF-driven, opaque .id on JP/US, structural-key round-trip on `identifier[]`, fallback shapes when encounter_id / procedure_id are missing). Existing `test_fhir_oxygen_therapy_procedure.py::test_procedure_emitted_from_vitals_only_when_no_o2_order` updated to assert the opaque .id equals `_resolve_procedure_id("proc-o2-ENC-1")` and the structural key survives on `identifier[]` — pre-#854 it asserted the literal compound shape. 1,032 existing `tests/unit/output/` tests still pass. P=200 seed=500 sim + FHIR emit verify: 39 Procedure records, non-opaque = 0, missing structural-key ident = 0, length distribution = 17 (single length, all opaque). Second per-type PR of Issue #854 Bucket A per the recipe in `docs/plans/2026-08-25-issue-853-854-non-hai-mr-opaque-id.md` Appendix A row 2; follow-on: ServiceRequest → Observation (land close together to minimize DR/Observation `basedOn[]` mismatched-shape deploy window).
- **`Device.id` and `DeviceUseStatement.id` are now opaque** (Issue #854 Bucket A, first per-type PR). Extends PR #863's opaque-id pattern (`derive_opaque_id` + `identifier[]` round-trip via `structural_key_system`) to the Device / DUS pair. Pre-#854 shape: `Device.id = "dev-ENC-POP-{patient}-{encounter}-{kind}-{seq}"` (up to 55 chars, Bucket A row 5 in Issue #854), `DUS.id = "dus-{device_id}"` (up to 59 chars, Bucket A row 3 — MAX id length across all resource types in the JP p=10000 s500 sample). Post-#854 shape: `Device.id = "dev-<12hex>"` (16 chars, fixed), `DUS.id = "dus-<12hex>"` (16 chars, fixed). Both resolvers hash the SAME structural key (CIF `DeviceRecord.device_id`) so a viewer can trivially pair DUS ↔ Device by matching the trailing 12 hex chars — only the 4-char prefix differs. `DUS.device.reference` goes through the same `_resolve_device_id` derivation as `Device.id`, keeping the cross-reference byte-consistent by construction. Two new module-private helpers in `clinosim/modules/output/fhir_r4/procedures/device.py`: `_resolve_device_id(structural_key)` and `_resolve_device_use_statement_id(structural_key)`. Two new canonical Identifier.system URIs (PUBLIC constants — writer/reader shared): `DEVICE_KEY_SYSTEM = "urn:clinosim:identifier:device-key"` and `DEVICE_USE_STATEMENT_KEY_SYSTEM = "urn:clinosim:identifier:device-use-statement-key"`, both computed via `structural_key_system()` from the Phase-1a foundation (`clinosim/modules/output/fhir_r4/lib/ids.py`). Both resources unconditionally emit `identifier[{system, value: cif_device_id}]` for round-trip. Visible effects on JP p=10000 s500 sample: (a) `Device.id` and `DUS.id` length drops from up to 55 / 59 chars to a fixed 16, giving 48 chars of headroom under FHIR R4's 64-char cap. (b) Patient identifier no longer leaks into `Device` / `DeviceUseStatement` URLs — Bucket A ids now match the FHIR R4 "Resource.id is an opaque logical identifier" intent that PR #357 established for antibiotic MR and PR #863 widened to all MR. (c) Cross-reference `DUS.device.reference` is byte-consistent with the parent `Device.id`. Scope: `_bb_device` and `_bb_device_use` in `procedures/device.py` (CIF-driven emit path — 98 Device + 98 DUS records in the sample). The single facility-level fixture Device (`dev-infusion-pump` emitted from `encounters/facility.py:151`, a shared asset per the CY8-20 dangling-reference closure) is intentionally NOT touched — it is master data (Bucket D per Issue #854), not per-patient-event data, and consumers reference it by its stable hand-authored id (`medications/medications.py:1432`). Byte output changes on Device and DeviceUseStatement NDJSON — MINOR-bumpable at next release. Test coverage: new file `tests/unit/output/test_fhir_device_opaque_id_854.py` (14 cases pinning opaque `.id`, deterministic + cross-key-distinct resolvers, canonical Identifier.system URIs, identifier[] round-trip on both Device and DUS, DUS.device.reference byte-consistency with Device.id, US locale + placement_date empty edge cases). 1,036 existing `tests/unit/output/` tests still pass. P=200 seed=500 sim + FHIR emit verify: 3 Device (1 facility, 2 CIF-driven), 2 DUS — all CIF-driven ids opaque, 0 missing structural-key ident, 0 dangling `DUS.device.reference`, s88k-fu #852 English single-word `.text` invariant preserved at 0. This lands the first row of Issue #854 Bucket A per the recipe in `docs/plans/2026-08-25-issue-853-854-non-hai-mr-opaque-id.md` Appendix A; remaining Bucket A rows (Procedure, ServiceRequest, Observation) follow in subsequent per-resource PRs.

### Fixed

- **`ServiceRequest.reasonCode.text` no longer ships as English on JP output** (Issue #871). 274,806 / 274,806 (100 %) of JP `ServiceRequest.reasonCode.text` entries shipped the English `Order.clinical_intent` verbatim on the iris4h-ai 2026-08-26 deploy verify (master `74a72f608e`, JP p=10000 s500) — `"Chronic-medication monitoring (Atorvastatin): Statin hepatotoxicity monitoring …"`, `"Outpatient follow-up: Creatinine"`, `"Admission workup: Na"`, `"Escalation day 3: Vancomycin (no improvement)"`, `"ED workup: CBC"`, etc. The CIF field `Order.clinical_intent` is behavior-load-bearing — `_sr_intent_from_clinical_intent` maps its EN keywords to FHIR `SR.intent` values (`"outpatient follow-up"` → `instance-order`, `"ed workup"` / `"ed imaging"` → `original-order`), `medication_pipeline._determine_route` reads `"bid"` for route inference, `validator.consistency` gates on `"HELD"`, and `medications.py` behavior branches on 3 sites — so localizing the CIF field in place is unsafe. Fix: add parallel display-only slot `Order.clinical_intent_ja: str = ""` at `types/encounter.py:182` (same writer/reader locale-split pattern established by `Encounter.chief_complaint` / `Encounter.chief_complaint_ja` for Issue #360 G1). New shared helper `_pick_reason_text(source, lang)` in `clinosim/modules/output/fhir_r4/labs/service_request.py` prefers the JA slot on JP output when populated, falls back to the EN `clinical_intent` when empty — silent-no-op fallback preserves pre-#871 behavior for writers that have not been migrated. Applied to both SR emit sites (`_build_standalone_sr` + `_build_panel_sr`). Writers migrated to populate both fields (32 sites across 8 modules): `modules/monitoring/enricher.py` (dominant volume via `medication_monitoring.yaml` — 8 `rationale_ja` + 6 `drug_ja` slots added; composes `慢性投薬モニタリング ({drug_ja}): {rationale_ja}` template), `modules/order/engine.py` (9 sites — `_build_lab_order` extended with `clinical_intent_ja=""` param; admission workup / admission imaging / first-line / supportive / day monitoring; imaging orders read new `clinical_indication_ja` from disease-YAML spec with graceful fallback for un-migrated YAMLs), `modules/health_checkup/engine.py` (`"health_checkup"` → `"健康診断"`), `simulator/outpatient.py` (`Outpatient follow-up: {test_name}` → `外来フォローアップ: {test_name}`), `simulator/emergency.py` (3 sites — ED workup / ED imaging / ED treatment), `simulator/daily_loop.py` (8 sites — Day archetype workup / imaging / stop / new medication / device-therapy / new procedure / escalation / diet), `simulator/unknown_condition.py` (5 sites — Unknown {complaint} initial / imaging / med intent / Day 4 fever / Day monitoring), `simulator/medication_pipeline.py` (4 sites — Home medication continue + 3 Chronic monitoring branches read new `intent_ja` from disease-YAML with graceful fallback). Downstream behavior parsers (`_sr_intent_from_clinical_intent`, `medication_pipeline._determine_route`, `validator.consistency`, `medications.py` 3 gates) all continue reading `clinical_intent` (EN) verbatim — the JA slot is display-only and never drives behavior (regression-pinned by `test_sr_intent_mapping_still_reads_en_field`). Parameter values (drug names, lab names, exam names, complaint text, archetype identifiers) inside the JA templates are kept as-is — full parameter localization would require per-YAML `_ja` slot authoring across 20+ disease YAMLs and is deferred to a follow-on PR; template shells are translated so the human-readable half of every `reasonCode.text` is JP-native on JP output. New: `tests/unit/output/test_fhir_sr_reason_code_ja_871.py` (13 tests) — 5 direct-helper tests (`_pick_reason_text`: JA-populated → JA; JA-empty → EN fallback; US locale ignores JA; dict-shape accepted; empty-both), 3 end-to-end tests via `_bb_service_requests` covering JP-with-JA / JP-fallback / US-ignores-JA, 1 regression pin against `_sr_intent_from_clinical_intent` reading EN, 2 monitoring-enricher composition tests (JA composed from YAML `drug_ja` + `rationale_ja` / empty-`rationale_ja` leaves JA slot empty), 1 yaml coverage guard (every drug entry has `drug_ja`; every monitoring entry has `rationale_ja`), 1 no-EN-in-JA-value guard. 4,532 whole-tree unit tests still pass; ruff check + format clean. Post-fix target on the same deploy sample: EN-like `SR.reasonCode.text` drops from 274,806 → 0 for records emitted by migrated writers; residual EN comes from disease-YAML `clinical_indication` / `chronic_monitoring[].intent` fields that have not yet been extended with `_ja` siblings (silent-no-op fallback keeps them working, subsequent PRs can extend the YAMLs incrementally). No behavior parser touched — pre-#871 SR.intent mapping / route derivation / validator behavior byte-preserved. Consistent with `feedback_fhir_emit_bug_no_direct_patch.md` (fix stays at CIF-authoring + FHIR-emit reader layer; no derived state patched).
- **`ImagingStudy.reasonCode.text` no longer ships as English on 30 chief-complaint vignette phrases** (Issue #872). 3,608 `ImagingStudy` records (76.2 % of the 4,735 that carry `reasonCode`) in the JP p=10000 s500 sample (iris4h-ai 2026-08-26 deploy verify) shipped the English `Encounter.chief_complaint` verbatim via the CY7-03 walker at `clinosim/modules/output/fhir_r4/labs/imaging_study.py:80-88` — e.g. `"Sudden onset weakness, speech difficulty, facial droop"`, `"Dyspnea on exertion, orthopnea, lower extremity edema"`, `"Displaced distal radius fracture requiring ORIF"`. The remaining 1,127 records already localized to Japanese because those encounters' disease YAMLs authored `chief_complaint` as a plain-JA string (so CIF `chief_complaint` = JA, not EN). Fix: introduce `_CHIEF_COMPLAINT_JA` (30 entries covering every distinct EN vignette observed on the deploy) and a `_localize_chief_complaint(text, lang)` helper in `labs/imaging_study.py`; the walker invokes it once per encounter before writing to `_enc_reason_by_id`. JP-only lookup — US output preserved unchanged. Unknown values pass through as-is so the 1,127 already-JA records are preserved and a future disease-YAML EN vignette degrades gracefully to the CIF text rather than a placeholder. Longer-term the disease YAMLs should author `chief_complaint: {en, ja}` (dict form) so `_disease_chief_complaint_ja` populates `Encounter.chief_complaint_ja` and the emit path can prefer that; that CIF-authoring work is deferred to a follow-on PR. New: `tests/unit/output/test_fhir_imaging_study_ja_reason_code_872.py` (17 tests) — 7 direct-helper parametrize cases, US-passthrough / unknown-passthrough / already-JA-passthrough / empty-string safety pins, 30-vignette inventory coverage guard (mirrors the 2026-07-22 slug-guard pattern from `test_fhir_composition_section_title_jp.py`), no-EN-in-JA-value guard, and 4 end-to-end regression tests via `_bb_imaging_studies` covering JP-localize / US-preserve / already-JA-passthrough / novel-EN-passthrough. 4,536 whole-tree unit tests still pass. Post-fix target on the same sample: EN-like `ImagingStudy.reasonCode.text` → 0 (assuming the deploy chief-complaint vignette set is unchanged). No CIF-side changes; FHIR-emit-only fix via the inline dict — consistent with `feedback_fhir_emit_bug_no_direct_patch.md`.
- **`Composition.section.title` no longer leaks 16 raw English snake_case section keys on JP output** (Issue #870). 11,536 `Composition.section.title` entries (5.2 % of 221,265) in the JP p=10000 s500 sample shipped raw slugs — `ed_workup` / `disposition` (2,938 each), `treatment_plan` / `test_schedule` / `surgery_schedule` / `special_nutrition_management` / `other_plans` / `estimated_los` (878 each), `discharge_estimate` / `explanation_consent` (878-tier), and the rehab-plan block `session_frequency` / `rehab_team` / `policy` / `goals` / `functional_status` / `basic_movement` (49 each) — instead of the Japanese display used by the other 94.8 % of section titles. `_localize_section_title` at `clinosim/modules/output/fhir_r4/documents/composition.py:218` looks the section up in `_SECTION_TITLE_JA` and falls back to the raw slug when the key is missing — the 16 keys above were not registered so they passed through verbatim. Fix: add the 16 keys to `_SECTION_TITLE_JA` (`ed_workup → 救急外来での評価`, `disposition → 転帰`, `treatment_plan → 治療計画`, `test_schedule → 検査予定`, `surgery_schedule → 手術予定`, `special_nutrition_management → 特別栄養管理`, `other_plans → その他の計画`, `estimated_los → 予定入院期間`, `discharge_estimate → 退院見込み`, `explanation_consent → 説明と同意`, and the 6 rehab keys). US output preserved unchanged (`_localize_section_title` is a no-op for `lang != "ja"`). The intentional silent-no-op fallback stays — a future new template slug still emits with its raw form rather than crashing. New: added 16 parametrize cases + 1 inventory-guard test (`test_all_iris4h_ai_2026_08_26_flagged_slugs_covered`) + 1 end-to-end regression covering ED- and rehab-shaped section dicts to `tests/unit/output/test_fhir_composition_section_title_jp.py`. 4,537 whole-tree unit tests still pass. Post-fix target on the same sample: snake_case leak → 0. No CIF-side changes; fix is entirely at FHIR emit time via the `_SECTION_TITLE_JA` dict extension — consistent with `feedback_fhir_emit_bug_no_direct_patch.md`.
- **`Procedure.code.text` no longer ships as untranslated English on 3 order-derived procedure kinds** (Issue #861). 15 `Procedure` records (0.50% of 3,011) in the JP p=10000 s500 sample carried English CIF-template strings in `code.text` with no `coding[]` fallback, so a JA-locale consumer had no way to render a Japanese label. All three go through the same emit site (`clinosim/modules/output/fhir_r4/lib/inline_bb.py:697`, `_code_text = _localize_drug_name(display, ctx.country)`) but missed `drug_names_ja.yaml` entries. Fix: add 3 cleaned-form entries (post-":" split, matching `_localize_drug_name`'s step-2 strip-prefix lookup): `graduated compression stocking on unaffected leg` → `弾性ストッキング(患側外・段階的圧迫)` (8 records — DVT prophylaxis), `cervical collar until cleared` → `頚椎固定(頚椎カラー・画像判定まで)` (6 records — trauma admission), `emergent dialysis stat` → `緊急透析` (1 record — dialysis order). US output preserved unchanged (helper is a no-op for `is_us(country)`). New: 5 regression tests in `tests/unit/output/test_fhir_procedure_jp_text.py` covering each phrase + US passthrough + yaml integrity. 1009 existing output/ unit tests still pass. P=200 seed=500 sim + FHIR emit verify: English-only `.code.text` Procedure records drop 15 → 0. No CIF-side changes; fix is entirely at FHIR emit time via the yaml dictionary lookup.
- **`ImagingStudy.description` no longer ships as English on 34 stub-only exam kinds** (Issue #862). 1,060 `ImagingStudy` records (**22.4%** of 4,735) in the JP p=10000 s500 sample shipped English CIF stub descriptions (`ECG`, `Echocardiogram`, `ECG_12lead`, `Echocardiography_TTE`, `Carotid_ultrasound`, `Ankle_Xray`, `FAST_Ultrasound`, `CT_Angiography_Chest`, `MRCP`, `Slit_lamp_exam`, etc. — 34 distinct kinds) via the Issue #822 stub-only fallback branch at `clinosim/modules/output/fhir_r4/labs/imaging_study.py:240`. The body_sites-based procedure lookup returns nothing for these disease-YAML-sourced exam names (`- {test: "FAST_Ultrasound"}` in `traffic_accident_severe.yaml` and 33 other kinds), so `_stub_desc` from `study.description` emitted through unchanged; no `procedureCode[]` or `coding[]` fallback exists on `ImagingStudy` to recover a JA form. Fix: add 34 entries in a new `# --- Imaging exam names (Issue #862)` section of `clinosim/locale/shared/drug_names_ja.yaml` covering every English-only description observed on the sample, plus a new module-private `_localize_imaging_exam_name(exam_name: str) -> str` helper in `labs/imaging_study.py` that normalizes underscores to spaces and does a case-insensitive lookup. Called only on JP output (`lang == "ja"`); US output preserved unchanged. Unknown keys pass through as-is so the surface degrades gracefully to the CIF English name rather than a placeholder. Coverage vs. deploy inventory: top-15 exam kinds account for 991 / 1,060 records (93.5%); the remaining 19 tail kinds (`Wrist_CT`, `Hand_CT`, `MRI_Lumbar`, `CT_perfusion`, `Repeat_compression_ultrasound`, etc.) are also fully covered — post-fix count of English-only descriptions drops 1,060 → 0. New: 13 regression tests in `tests/unit/output/test_fhir_imaging_study_ja_description_862.py` covering the direct helper (top-volume + multi-word + unknown-key passthrough + case insensitivity) and the full `_build_imaging_study` emit path (stub-only JP → JA, US → English preserved, unknown-key JP → English preserved, top-15 yaml integrity gate). 1,017 existing `tests/unit/output/` tests still pass. P=200 seed=500 sim + FHIR emit verify: English-only `.description` on ImagingStudy resources drops 0 → 0 (P=200 sample happens not to include any of the affected exam kinds); the invariant is pinned at unit level for full coverage. No CIF-side changes; fix is entirely at FHIR emit time via the yaml dictionary lookup — consistent with `feedback_fhir_emit_bug_no_direct_patch.md`.

### Changed

- **`MedicationRequest.id` is now opaque across every emit path** (Issue #853 + Issue #854 Bucket A entry). Extends PR #357's Phase-1b antibiotic-MR pattern (`mr-{sha256(order_id)[:12]}` + `identifier[]` round-trip via `urn:clinosim:identifier:medication-request-key`) to non-HAI inpatient orders (~108k in the JP p=10000 s500 sample), discharge-Rx (`rxdc-{sha256(structural_key)[:12]}` — was `rxdc-{encounter_id}-{seq:02d}`), and outpatient-Rx (`rxopd-{sha256(structural_key)[:12]}` — was `rxopd-{encounter_id}-{seq:02d}`). `MedicationAdministration.request.reference` (359k in the sample) resolves through the same widened `_resolve_mr_id` derivation so cross-references stay byte-consistent with the parent MR's `.id` by construction. Rename: `_resolve_antibiotic_mr_id` → `_resolve_mr_id` (drop the `startswith(ABX_ORDER_ID_PREFIX)` guard); two new siblings `_resolve_dc_rx_id` / `_resolve_opd_rx_id` share the same `derive_opaque_id` foundation with prefix retained per Issue #445 intent. `_build_medication_request_identifiers` drops the `is_antibiotic_mr: bool` parameter — every MR now unconditionally carries the structural-key identifier. Visible surface effects on the JP p=10000 s500 sample: (a) the 8-char drug-slug truncation (`-Aminophy` / `-Meropene` / `-Ampicill` / etc., 576 records in the ESC-D*-\* / STOP-D*-\* codepath — Issue #853's motivating symptom) no longer appears in `MedicationRequest.id`; the compound Order.order_id is preserved in `identifier[]` for consumers that need to string-parse it. (b) `MedicationRequest.id` length drops from up to 50 chars (compound) to a fixed 15 (`mr-`) / 17 (`rxdc-`) / 18 (`rxopd-`), giving 46–49 chars of headroom under FHIR R4's 64-char cap. (c) Patient identifier no longer leaks into every `MedicationRequest` / `MedicationAdministration` URL — the FHIR R4 "Resource.id is an opaque logical identifier" intent that PR #357 established for antibiotic MR now holds for every MR. Byte output changes across the MR and MA NDJSON — MINOR-bumpable at next release. `sanitize_id_token(drug_name, 8)` at `clinosim/simulator/daily_loop.py:514` (the CIF-side source of the truncation) is intentionally NOT touched — CIF Order.order_id retains the compound shape as the structural-key input to `derive_opaque_id`; consumers that need the drug slug can recover it from `identifier[]`. Downstream: audit gate `_medication_request_structural_key` at `clinosim/audit/axes/clinical.py:838-839` (`if ABX_ORDER_ID_PREFIX not in structural_key: continue`) still correctly filters antibiotic MR — non-antibiotic order_ids do not contain the antibiotic prefix so the caller's continue-branch fires exactly as before, just with a real string instead of `""`. `clinosim/modules/output/fhir_r4/lib/inline_bb.py` follows the rename (`_resolve_antibiotic_mr_id` → `_resolve_mr_id`). Test coverage: new file `tests/unit/output/test_fhir_medication_non_hai_opaque_id.py` (12 cases pinning opaque .id, deterministic + cross-order-distinct resolver, structural-key round-trip on both US and JP, discharge/outpatient prefix distinction, MA cross-ref byte-consistency). Existing `test_fhir_medication_opaque_id.py` retained with 3 pre-#853 "non-antibiotic unchanged" tests deleted and 1 audit-gate test inverted (their new coverage lives in the sibling file, no duplication). Two integration-adjacent tests fixed: `test_fhir_discharge_medication_request::test_us_output_has_no_jp_identifier_slices` asserts absence of JP-Core slices instead of absence of identifier[] entirely, and `::test_inpatient_and_outpatient_get_distinct_id_prefixes` + `::test_seq_drives_both_id_suffix_and_order_in_rp` assert prefix retention + structural-key round-trip instead of literal compound-id shape. 4474 unit tests pass; ruff dead-code (F401/F841) + format clean; P=200 seed=500 sim + FHIR emit verify: 0 non-opaque MR.id (was 2077), 0 missing structural-key ident (was 2077), 0 dangling MA.request.reference, 0 ids > 64 chars, English single-word `.text` invariant from s88k-fu #852 preserved at 0. This lands #853 in full and puts the Bucket A recipe from Issue #854 in place (`docs/plans/2026-08-25-issue-853-854-non-hai-mr-opaque-id.md` Appendix A) for follow-on per-resource-type PRs (ServiceRequest / Observation / DeviceUseStatement / Procedure / Device).

### Fixed

- **`medicationCodeableConcept.text` JA multi-word extension now fires even when `Order.order_code` is pre-set** (Issue #852 follow-up). PR #856 landed the multi-word JA-dict extension INSIDE the `if not code_value and drug_name_clean:` block in `_resolve_medication_concept` and `_build_medication_admin`. When the disease YAML supplied `Order.order_code` up front (e.g. Magnesium Sulfate = MHLW HOT7 `2355002`, and similarly for Normal saline / Regular insulin / Potassium chloride / Lactated Ringer / Hypertonic Saline / Unfractionated Heparin), `code_value` was truthy at the top of the block, the whole block including the JA extension was skipped, and `.text` fell back to the first whitespace token (`"Magnesium"` / `"Regular"` / `"Potassium"` / `"Lactated"` / `"Hypertonic"` / `"Unfractionated"` / `"Normal"`) even though `drug_names_ja.yaml` carried the multi-word entry. JP p=10000 s500 sample: **6,327 records (165 MR + 6,162 MA)** leaked English single-word `.text` while `coding[0].display` on the same resource was already Japanese (e.g. `硫酸マグネシウム水和物`). Missed by the original PR #856 verification because the P=200 s800 sample did not include drugs with disease-YAML-supplied pre-set codes. Fix: dedent the JA multi-word extension out of the `code_value` gate (hoist `normalized` / `tokens` computation so both blocks can share them). Applied symmetrically to both `_resolve_medication_concept` (MR builder) and `_build_medication_admin` (MA builder). Verified on P=200 seed=500 (which does include Magnesium sulfate at POP-000012 ESC-D3): all 11 English single-word truncation patterns now = 0 on both MR and MA. New: 5 regression tests in `tests/unit/output/test_fhir_medication_text_full_name.py` covering Magnesium/Normal saline/Regular insulin/Unfractionated Heparin with pre-set `order_code`, plus the MA builder path with `mar.code_yj` pre-set — all fail on the pre-fix code, all pass on the post-fix code. 998 existing unit tests still pass.
- **In-hospital new-disease events no longer open a second concurrent inpatient encounter** (issue #848). The population life-event stream can fire a new disease event for a patient who is still admitted for an earlier event (POP-000170 in the JP p=10000 s500 sample developed acute coronary syndrome on hospital day 37 of a 46-day pancreatitis admission). Prior behavior: `run_beta` dispatched the new event as a wholly separate `_simulate_patient` call, and two admissions coexisted for the patient in the same physical hospital — 17 cross-department overlaps + 8 same-department overlaps in the sample. `run_beta` now gates every admission with `_find_active_inpatient_record` (point-in-time; main inpatient loop) or `_find_overlapping_inpatient_record` (period-overlap with a 30-day LOS estimate; readmission loop — needed because it runs after the main loop, so `patient_records` already contains later life-event admissions whose start is after the readmission's scheduled admit time but whose period overlaps). When a gate hits, `_merge_disease_into_active_encounter` records the new disease as an in-hospital complication on the existing encounter: appends to `complications_occurred`, promotes `condition_event.condition_type` to `"mixed"`, appends to `condition_event.ground_truth_diseases`, and adds a `working_diagnoses` entry carrying `disease_id` + `onset_day` (days since admission, clamped to `0` when the readmission dispatch merges an earlier-scheduled readmission into a later-admitting life-event encounter) + `onset_datetime` + `source="in_hospital_complication"`. Full order/lab/vital simulation for the complication is deliberately deferred — the per-disease protocol's LOS pacing and discharge date logic cannot be dropped into the middle of another admission's timeline without a substantial refactor of `_simulate_patient`; the diagnostic fact + working-diagnosis entry preserve the clinical signal (this patient developed X on day N) without fabricating a treatment timeline that would not agree with the pre-simulated existing admission's flow. Narrative side: `NarrativeContext.working_diagnoses` is a new field wired through `build_narrative_context` (structural CIF path) and `NarrativePass` (LLM path); the discharge-summary hospital-course sentence 2 in `template_generator.py` now emits `入院第N日目 <disease>` / `<disease> (onset day N)` when an onset day is present (falls back to the plain disease id for legacy `complications_occurred` entries without a matching `working_diagnoses` record); `replacement_strategy.py::_build_extra_context` exposes both `complications_during_stay` (with hospital-day annotations) and a dedicated `in_hospital_new_diagnoses` key to the LLM prompt so generated narrative can say `入院第30日目に急性心筋梗塞を発症` instead of listing the disease as an admission-day finding. New: `tests/unit/test_engine_inpatient_overlap.py` (21 tests) covers point-in-time active detection, period-overlap detection with 30-day window, merge idempotency, condition-type promotion, working-diagnoses entry structure, and negative-onset-day clamp. Measured impact on the JP p=10000 s500 sample after applying the fix to the existing snapshot as a data patch: **25 → 0** inpatient encounter overlaps; 22 later encounter CIF files + narratives deleted; primary encounters carry the merged disease facts. 4404 existing unit tests still pass; s88k / PR #845 / PR #847 invariants (MHLW oral 85.88% / non-oral-MHLW = 0, four narrative leak metrics 0.00%, outpatient dept resolver POP-000911 = general_surgery, DR normal-contradict = 0) preserved on the regenerated FHIR.
- **`MedicationRequest.dosageInstruction[].patientInstruction` is now route-aware** (Issue #848). Prior emit derived the JA phrase from the frequency label alone and every generated template ended in `"内服してください"` ("take orally") — so a saline IV drip (`route.text="静注"`) shipped with `patientInstruction="毎日1回、指示された時間帯に内服してください"` and the two fields inside one resource disagreed on the route. The mismatch touched **3,592 / 10,886 populated JP `patientInstruction` (33.0 %)** in the JP p=10000 s500 sample; saline (`生理食塩液`) was 100 % wrong at 838 records ("take saline orally"). New `_resolve_patient_instruction_ja(route, freq, freq_per_day)` picks the phrasing template from a route-family table `_PI_ROUTE_FAMILIES_JA` (parenteral IV/SC/IM/drip → `医師の指示のもと、看護師が投与します`; inhalation → `指示された方法で吸入してください`; rectal / suppository → `指示された時間に直腸内に挿入してください`; transdermal patch → `指示された部位に貼付してください`; topical / ointment → `指示された部位に塗布してください`; eye drop → `指示された時間に点眼してください`; nasal → `指示された時間に点鼻してください`; sublingual → `指示された時に舌下に投与してください`; enteral / NG / PEG → `看護師が経管より投与します`; oral → freq-composed `毎日N回、指示された時間帯に内服してください`) and folds a freq-per-day / interval prefix into the oral case only. Timing-only labels (`qhs` / `ac` / `pc` / `qam` / `qpm` / `prn` / `頓服` / `頓用`) still emit their route-independent phrase unchanged. Unknown routes yield the empty string so `patientInstruction` is omitted (FHIR cardinality `0..1`) rather than emitted with a value that would contradict the resource's own `route.text` — matching the alternative Issue #848 recommends. Explicit CIF-authored `Order.patient_instruction` (Issue #476 opt-in) still wins over the derived phrase. New: `tests/unit/output/test_fhir_dosage_patient_instruction_route.py` (16 tests) covering the oral freq composer, each non-oral route family, unknown-route omission, authored-instruction precedence, timing-only labels, and the saline-IV regression case; existing session-88j `test_fhir_p25_reasoncode_and_patientinstruction.py` continues to pass with the expanded `_PI_ROUTE_FAMILIES_JA` markers (`ORAL` / `BY MOUTH` / `INTRAVENOUS` etc. added so pre-localization EN route strings resolve correctly).
- **`medicationCodeableConcept.text` now uses the full multi-word drug name for JA localization** (Issue #852). Prior emit truncated the base name to the first whitespace token before localizing, so multi-word product-family names (`Cefcapene pivoxil`, `Cefditoren pivoxil`, `Magnesium sulfate`, `Normal saline`, `Regular insulin`, `Potassium chloride`, `Lactated Ringer`, `Hypertonic Saline`, `Unfractionated Heparin`, `Calcium/Vitamin D`, `ICS/LABA inhaler`) whose only JA-dict key was the full form never localized — 8,283 (2.3 %) `MedicationAdministration.text` + 1,113 (1.0 %) `MedicationRequest.text` shipped Latin single-word strings (`"Magnesium"` / `"Cefcapene"` / `"Normal"` / `"Regular"` / `"Potassium"` / `"Lactated"` / `"Hypertonic"` / `"Unfractionated"` / `"ICS/LABA"` / `"Calcium/Vitamin"` / `"Cefditoren"`) while `coding[0].display` on the same resource was already Japanese. Fix: after the code_mapping multi-token prefix loop (which is optimized for the JP MHLW YJ table and misses product-family qualifiers), extend `base_name` to the longest multi-word prefix that has a matching entry in `drug_names_ja.yaml`, but only when the prefix begins with the already-chosen first token — the constraint preserves the Issue #775 invariant that `.text` must not carry dose text, since dose / route / freq tails cannot slip in as an unrelated prefix. Applied symmetrically to `MedicationRequest` (`_resolve_medication_concept`) and `MedicationAdministration` (`_build_medication_admin`). Also added missing `ICS/LABA inhaler` → `吸入ステロイド／β2刺激薬配合吸入剤` and `ICS/LABA` → `吸入ステロイド／β2刺激薬配合` entries to `clinosim/locale/shared/drug_names_ja.yaml`. New: `tests/unit/output/test_fhir_medication_text_full_name.py` (10 tests) verifies all 11 flagged drugs localize to JA, the `ICS/LABA` short-form resolves, US output passes through unchanged, and the yaml has the required entries. Existing session-88j `test_fhir_medication_jp_hot_uri.py` (Issue #775 dose-exclusion invariant) continues to pass — the JA-dict extension respects the same first-token boundary that keeps dose out of `.text`.
- **`MedicationAdministration.dosage` (route + text) now backfills from the parent Order** (Issue #851). Prior emit dropped the entire `dosage` element on **23,543 / 359,023 (6.56 %)** of JP p=10000 s500 sample MAs — continue-home-med / sliding-scale / PRN orders had no numeric dose at either MA or Order level, so `_parse_dose_for_mar` yielded no structured `dose_quantity`, and the historic mad-1 emit gate (require `dose` OR `rateQuantity` before emitting the dosage element) discarded the entire block — losing route and free-text description as well. Fix (a): `_build_medication_admin` accepts a new `parent_order: dict | None` parameter; when `mar.dose` is empty or a drug-name fallback (`"Fluticasone/Salmeterol"` in the `dose` slot for the same drug), the builder backfills text + route from the parent Order's structured `dose_quantity` / `dose_unit` / `frequency` / `route` fields. Fix (b): the mad-1 emit gate is relaxed so `dosage` emits whenever it carries at least a route or a meaningful (non-drug-name) text — the eMAR-rendering need outweighs the FHIR R4 mad-1 preference, which is SHOULD not SHALL. Text that merely repeats the drug name is treated as empty so `.dosage.text` never shadows `medicationCodeableConcept.text`. Caller (`inline_bb.py::_bb_medication_administrations`) builds a one-shot `order_id → Order` lookup and passes the matching parent to the builder. New: `tests/unit/output/test_fhir_medication_admin_dosage_backfill.py` (8 tests) covers the Fluticasone/Salmeterol home-med case, composed-text carries freq/route, structured-dose backfill from parent, drug-name-fallback empty treatment, dosage emitted for sliding-scale (route only, no dose), still-omitted when nothing meaningful is available, structured-path unchanged when MA.dose is parseable (`"500mL"`), and no-parent-Order defensive path. 4,414 existing unit tests still pass.
- **Late-admission placed medications now get a day-0 first dose** (Issue #850). `_generate_mar` computed day-0 slots off `admission_time`'s calendar day at the fixed `admin_hours` for the drug (`[8]` for daily; `[0, 8, 16]` for IV default; `[0, 6, 12, 18]` for Q6H; etc.) and rejected every slot that fell before `admission_time`. For a patient admitted at 09:02 to an Enoxaparin `daily` order (only slot `[8]`) or admitted at 16:43 to an IV order (`[0, 8, 16]`), every day-0 slot was rejected. When the encounter's LOS was short enough that day 1's first slot never fired, the order ended up with ZERO MedicationAdministration records — 3 orphan inpatient MedicationRequests (`status="completed"`, 0 linked MA) in the JP p=10000 s500 sample. Fix: on day 0, when every scheduled slot is before `admission_time` and no STAT ad-hoc first dose already applies, insert an ad-hoc first-dose slot at `admission_time + jitter` (same 30–60 min shape as the existing STAT first-dose path, reusing `MAR_STAT_FIRST_DOSE_DELAY_MIN` / `_MAX_EXCLUSIVE`). Guarded on `stat_first_dose_time is None` so STAT orders keep their bundle-mandated first-dose timing unchanged, and gated on `day == 0` so subsequent days use their normal fixed slots. New: `tests/unit/simulator/test_mar_late_admission_first_dose.py` (5 tests) — Enoxaparin daily late admission, IV saline late admission, admit-before-first-slot uses scheduled slot not ad-hoc, STAT unchanged, day 1+ unchanged.
- **DiagnosticReport.conclusionCode now derives from result flags / impression negation** (issue #846). The lab-panel DR emit path read the overall abnormality signal from ``getattr(group, "any_abnormal", False)`` — a field that was never set on the ``_GroupedPanel`` NamedTuple, so every lab DR emitted ``conclusionCode = 17621005`` (Normal) even when its own ``.conclusion`` listed ``参照範囲外: XXX`` and per-value ``[H]`` / ``[L]`` flags. 44.82 % of the 42,903 DRs in the JP p=10000 s500 sample carried this internal contradiction (19,229 Normal-verdict reports with abnormal markers in their own text). Additionally, the imaging-DR fallback path used a naive substring search that flipped ``impression_text`` to Abnormal whenever the text contained any of ``異常`` / ``認め`` / ``consolidation`` / ``fracture`` / ``骨折`` — regardless of negation. Radiology impressions such as ``急性期異常所見を認めず`` ("no acute abnormality found") were classified Abnormal because the search matched ``異常`` and ``認め`` without noticing the ``認めず`` negation (2,857 imaging DRs affected). Fix: ``_build_lab_panel_conclusion`` now returns ``(text, has_abnormal)`` so a single walk over the panel's Observations drives both the free-text summary and the SNOMED verdict — the code and the text cannot disagree within one resource by construction; and ``_derive_imaging_conclusion_code`` checks negation phrases (``認めず`` / ``認めない`` / ``所見なし`` / ``異常なし`` / ``正常`` / ``no acute`` / ``no evidence of`` / ``negative for`` / ``unremarkable`` / ``within normal limits`` / ``normal study``) BEFORE the abnormal-keyword scan, so ``no acute consolidation`` is Normal. When ``orders`` is unavailable to the lab path, ``conclusionCode`` is omitted rather than emitted with a value we cannot back with the resource's own data (FHIR cardinality is ``0..*``). New: ``tests/unit/output/test_fhir_dr_conclusion_code.py`` (17 tests) covers all-normal / single-flag / critical-flag lab cases with both dataclass and dict fixtures, the code↔text single-walk invariant, JA and EN imaging negation phrases, JA and EN abnormal-keyword recognition, and empty-impression Normal defaults. Measured impact on the JP p=10000 s500 sample: Normal-with-abnormal-text drops **19,229 → 0**; residual 495 Abnormal-without-lab-marker reports are the correctly-Abnormal 134 microbiology growth-positives (culture wells emit no ``[H]`` / ``[L]``) plus 361 imaging reports with genuine positive findings (fractures, edema, effusions, masses).
- **Outpatient follow-up department is now resolved per visit** (this PR).
  `outpatient.py::_simulate_outpatient_visit` used to hard-code
  `department_id="internal_medicine"` and `assign_staff("rounds",
  "internal_medicine", ...)` for every outpatient follow-up encounter it
  produced, sending 100 % of them into 内科 regardless of the
  underlying inpatient service (for post-discharge visits) or the
  chronic condition being followed. A new resolver
  `simulator/outpatient_dept.py::resolve_outpatient_department(visit_type,
  code, prior_department_id, hospital_ops)` composes two layers: a
  disease/screening → clinical specialty map (chronic IHD/AFib/HF →
  cardiology; chronic gastro codes → gastroenterology; M81 osteoporosis
  → orthopedics; colonoscopy_screening → gastroenterology; well-child /
  mammography / annual health check / immunization → primary_care;
  everything else, incl. HTN/DM/COPD/CKD, → internal_medicine per
  Japanese primary-care realism) and the existing
  `hospital_ops.resolve_department` (which consults
  `hospital_operations.yaml::department_rollup` — extended here with
  `pediatrics: primary_care`, `obgyn: primary_care`, `dermatology:
  primary_care` so OPD-only specialties that this small community
  hospital does not staff land in 総合診療外来 rather than falling
  through to 内科). Post-discharge follow-ups short-circuit both stages
  and inherit the prior inpatient encounter's `department_id`
  (continuity of care — a trauma / surgical / cardiology / GI patient
  is followed up by the same service, not general internal medicine).
  Callers in `engine.py` (post-discharge / chronic-visit / pediatric-
  visit / health-screening dispatches) now compute the department via
  the resolver and pass it explicitly. Measured on the JP p=10000 s500
  sample: **265 / 775 (34.2%) post-discharge follow-ups** were going to
  internal_medicine when the inpatient stay had been in
  cardiology/orthopedics/gastroenterology/general_surgery, and
  **15,316 chronic + screening encounters** were mis-routed
  (cardiac chronic to internal_medicine, colonoscopy to internal_medicine,
  screening / well-child / immunization to internal_medicine instead of
  primary_care). New: `tests/unit/test_outpatient_dept_resolver.py`
  (22 tests) covers post-discharge inheritance, chronic specialty
  routing, screening dispatch, small-clinic rollup fallback, and
  null-config safety. NB: because `assign_staff("rounds", dept, ...)`
  now picks from a different roster pool for the newly-routed visits,
  the RNG stream inside each affected outpatient encounter shifts
  (per-encounter phase RNG — no cross-encounter contamination), so
  regenerated snapshots will differ byte-for-byte from prior 0.3.0
  output for outpatient follow-up records; inpatient / ED / narrative
  paths are unchanged.

## [0.3.0] - 2026-08-22

### Added (session 88k)

- **MHLW `MedicationUsage_ePrescription` heuristic** at FHIR emit time (PRs #836/#837/#838/#840/#841). `_populate_jp_medication_dosage_ecs_fields` now calls `_resolve_mhlw_usage_code(drug_text, freq, period, period_unit, route_text)` which dispatches through a 5-path resolver: **(1)** route filter — non-oral routes (`_NON_ORAL_ROUTE_MARKERS` = 静注/皮下注/筋注/吸入/舌下/貼付/塗布/点眼/直腸/経腸/etc.) return None so the walker falls to the JP-CLINS dummy uncoded code (spec-legit; MHLW oral CS has no injection/inhalation/etc. code family); **(2)** PRN condition codes via `_DRUG_PRN_MHLW_CODE` (アセトアミノフェン→発熱時、サルブタモール→喘息発作時); **(3)** fixed-interval Q3H via `_HOURLY_CADENCE_MHLW_CODE` (`1028…`); **(4)** daily-cadence meal-context via `_FREQ_CONTEXT_TO_MHLW_CODE` (9 canonical codes) driven by the drug-class → meal-context tables `_DRUG_{QD,BID,TID}_MEAL_CONTEXT` (~50 drugs across statins/PPIs/bisphosphonates/diuretics/antihypertensives/anticoagulants/antibiotics/etc.); **(5)** drug-implied freq when `timing.repeat` is missing entirely via `_DRUG_IMPLIED_FREQ_{QD,BID,TID}` sets. Semantic invariant: MHLW oral code is emitted **only** when `route.text == "経口"`. JP p=10000 s500 sample coverage: **99,252 / 115,599 dosages (85.86%) with a real MHLW code, all clinically correct**; residual 14.14% dummy is MHLW-CS-unmappable routes.
- **`comp-{encounter_id}-imgrpt-{n}` id pattern for imgrpt Composition** (PR #835, Issue #818 fu). Prior `comp-imgrpt-…` prefix sorted after every `comp-ENC-…` id so consumer alphabetic-`id` pagination (e.g. `_count=500`) missed all 4,823 imgrpt records. New pattern interleaves them among the same-encounter documents — a first-500 sample now includes ~37 imgrpt.
- **Non-stub ImagingStudy description + canonical dedup** (PR #834, Issue #822 fu). Non-stub ImagingStudy path now sets `description = order.display_name`; the emit fallback that used to leave `description=""` is closed. Dedup extracted to top of the per-order loop, applied to both stub and non-stub via `_canonicalize_display(name)` (lowercase + `_`/`-`→space + drops `and`/`of`/`with`/`for`) so cosmetic variants like `Chest_Xray_PA_Lateral` and `Chest X-ray PA and Lateral` no longer double-emit.
- **`_resolve_staff_name(staff_id, roster_map, is_ja)` template helper** (PR #831, Issue #819 fu). New `NarrativeContext.roster_map` field, populated by `NarrativePass._load_roster()` from `hospital.json`, threaded through `context.py::build_narrative_context`. 4 template call-sites (nursing shift note / progress-note nurse line / ACP other-staff / NCP ward+physician) now emit resolved names (`加瀬 幸男 医師`) before the LLM sees them — no more raw `DR-CA-002` id leak into narrative text. The FHIR-emit-time `_localize_practitioner_ids_in_text` walker (PR #828) is retained as defence-in-depth.
- **Documentation** (PRs #839, #842): narrative module README (EN + JA) documents the roster/template staff-name resolution + JA token localization + relationship to the composition.py walker; fhir_r4/post_process README (EN + JA) documents the full MHLW usage-code heuristic dispatch chain including the route filter and updated coverage numbers.

### Fixed (session 88k)

- **JA localization of `severity` / `oxygen_device` / `fall_risk_level` enum tokens** in narrative templates (PRs #832, #833). Three admission_hp HPI fallback branches used to embed raw `moderate` / `mild` / `severe` in JA text; `_build_nursing_shift_status` used to embed `酸素投与: nasal_cannula` and `転倒リスク high、` verbatim. All now route through the existing `_localize_severity_ja` / `_localize_oxygen_device_ja` / inline fall-level maps.

### Changed (session 88k)

- **iris4h-ai deploy** (`~/workspace/iris4h-ai/fhir_r4/`) regenerated from patched CIF via `clinosim export-fhir`. Post-regen quality on the JP p=10000 s500 cohort: staff_id / severity / o2_device / fall_lvl narrative leaks all 0.00 % on DocumentReference + Composition; imgrpt Composition present in first-500 alphabetically sorted; ImagingStudy empty description = 0, 3-tuple dup = 0; MedRequest MHLW oral code = 85.86 % (all 経口 route, 100 % clinically correct).

### Refactored (session 83)

- **Test import migration to canonical modules + re-export facade removal** (PR #540, PR #541):
  All test suites migrated to import directly from extracted `_fhir_*` sibling modules instead of the backward-compat re-export facade in `fhir_r4_adapter.py`. This allows deletion of the re-export block and further shrinkage of `fhir_r4_adapter.py`.
  - **PR #540**: 3 test files migrate `_build_discharge_rx` imports from `clinosim.simulator.inpatient._build_discharge_rx` (back-compat alias, deprecated in PR #532) to canonical `clinosim.simulator.discharge_rx.build_discharge_rx`. Back-compat alias removed from both `inpatient.py` and `discharge_rx.py`.
  - **PR #541**: 32 test files migrate 104 symbol references from `clinosim.modules.output.fhir_r4_adapter` facade to canonical modules (`_fhir_common`, `_fhir_inline_bb`, `_fhir_post_process`, etc.). The re-export block (109 symbols with `# noqa: F401`) is removed, and `fhir_r4_adapter.py` shrinks 689 → 543 lines (-146 lines). Module boundary now explicit: adapter holds only orchestration (`convert_cif_to_fhir` + `_build_bundle` + registry), leaf symbols live in canonical modules.
  - Verification: both PRs byte-diff neutral (session 82 protocol: unit + E2E + byte-diff), all CI checks green.

### Added (session 82)

- **New `AGENTS.md`** at repo root (agentmd.dev convention). AI coding
  agents (Claude Code, Codex, Cursor, Gemini CLI, Copilot, …) all
  discover repo-level instructions from a single, tool-agnostic
  filename. `CLAUDE.md` remains as a thin pointer for backward
  compatibility with older sessions. PR #527.
- **Coverage reporting in CI** (unit tests, PR #533): `pytest --cov=clinosim`
  now runs on every PR with `--cov-report=xml`, XML uploaded as a
  workflow artifact (30-day retention), soft floor `--cov-fail-under=80`
  (regression visible in log, doesn't block merge). Codecov integration
  scaffolded (commented) — enable via `CODECOV_TOKEN` secret. Baseline
  coverage: **84%** across `clinosim/`.
- **`docs/development/publishing-to-pypi.md`** — step-by-step runbook
  for both PyPI publishing paths (Trusted Publisher / API token). The
  `release.yml` workflow already builds sdist + wheel + dataset presets
  on tag push; PyPI upload is commented out until a maintainer
  completes one of the paths in the runbook. PR #533.
- **Nightly cron workflow** (`.github/workflows/nightly.yml`, PR #530):
  runs the reproducibility gate (`scripts/reproduce.sh`, byte-diffs the
  output for a fixed seed) and Python 3.11 unit tests once a day. Moves
  these rate-of-change gates off the PR path.
- **Escalation `type: "procedure"` signal** (Issue #460, PR #521): disease
  YAML `drugs.escalation[*]` now accepts an explicit `type` field
  (`"procedure"` or `"medication"`). A new 3-stage classifier
  (`classify_escalation_treatment`) routes each escalation on explicit
  type first, keyword fallback second, default MEDICATION third. Six
  latent misclassify entries (Hemodialysis / Vertebroplasty / Kyphoplasty
  / Catheter-directed thrombolysis) now emit as FHIR `Procedure` instead
  of `MedicationRequest`. Import-time validator raises on legacy
  `code_*: "procedure"|"N/A"` markers and on `type: "procedure"` +
  `route:` co-occurrence.
- **Chronic-medication + discharge-prescription sub-RNG isolation**
  (Issue #439, PR #522): new `chronic_medication_seed(patient_id)` and
  `discharge_prescription_seed(patient_id, encounter_id)` helpers in
  `clinosim/simulator/seeding.py` (AD-16 pattern, sibling of
  `panel_specimen_seed` / `individual_lab_seed`). YAML edits to
  `chronic_medications.yaml` or `drugs.discharge_oral` no longer shift
  unrelated patients' cohorts.
- **`baseline_chronic_medications` immutable field** on `PatientProfile`
  (Issue #433, PR #523): activation-time snapshot of the chronic
  regimen. The discharge chronic loop iterates `baseline ∪
  current_medications`, so a drug held during an AKI admission is
  re-emitted at the next admission when renal function recovers — the
  "chronic drug permanently lost after renal-hold" defect is fixed.
- **`drug_name_ja` threading** through `discharge_prescription.items[]`
  (Issue #440, commit c7f0c31071): 3 writer sites (inpatient / outpatient
  / chronic transcribe) now emit `drug_name_ja` so `_deactivate_to_layer1`
  preserves the JP display on round-trip.
- **Module README coverage gate** (PR #531): 31/31 real modules now ship
  a `README.md`, and a durable unit test
  (`tests/unit/test_module_readme_coverage.py`) will fail any future
  module added under `clinosim/modules/` without one.

### Changed (session 82)

- **CI PR-gate simplification** (PR #530): PR-level check count reduced
  from 13 to 9. Drops the empty `integration_serial` job, drops Python
  3.11 from the unit matrix (moved to nightly), combines `lint` +
  `typecheck` into a single `quality` job, moves `reproducibility` to
  nightly, and adds a `paths` filter to the JP-CLINS gate so docs-only
  PRs skip the JP cohort run.
- **`_build_discharge_rx` extracted** into
  `clinosim/simulator/discharge_rx.py` (PR #532). `inpatient.py`
  shrinks 2560 → 2338 lines. Backward-compat alias
  `_build_discharge_rx = build_discharge_rx` remains for existing test
  imports.
- **`cli.py` split by subcommand family** (PR #534): 1845 → 780 lines.
  Each `_run_*` handler moves to a dedicated sibling module
  (`cli_test_encounter` / `cli_test_disease` / `cli_regenerate` /
  `cli_narrate` / `cli_enumerate` / `cli_export_fhir`), shared print /
  export / debug helpers to `cli_common.py`. Back-compat re-exports
  keep existing test imports working.
- **`fhir_r4_adapter.py` inline `_bb_*` builders extracted** into
  `clinosim/modules/output/_fhir_inline_bb.py` (PR #535): 2382 → 1808
  lines. 11 bundle builders + `_build_order_in_rp_map` moved. The
  `_BUNDLE_BUILDERS` registry stays with `_build_bundle` in the
  adapter.

### Fixed (session 82 — subsumed under Added / Changed above)

Detailed defect-fix notes for the three Issue tickets (#460 / #439 / #433)
are recorded in the corresponding PR bodies (#521 / #522 / #523). All
three preserve deterministic output for pre-existing cohorts — byte-diff
verified on US + JP p=3000 seed=42 (Observation.ndjson identical, no
regression).

### Repo hygiene (session 82)

- `.tar.gz` maintainer artifacts (3 files) untracked, `.gitignore`
  unified (PR #524).
- 13 `docs/session-*.md` snapshots archived under
  `docs/history/session-prompts/` (PR #525); 30 `scratchpad/` audit
  artifacts under `docs/history/scratchpad-archive/` (PR #526); the
  root `scratchpad/` directory is now gitignored.
- Historical `spec.md` (2026-04) + `DES_MIGRATION.md` moved under
  `docs/history/` with an index README (PR #528).
- `test_data/` (5392 files / 200 MB of accumulated LLM narrative eval
  outputs) untracked; `.gitignore` prevents re-add (PR #529).

### Added

- **Synthea comparison adapter** (P1-10):
  [`clinosim eval`](docs/eval.md) can now score a
  [Synthea](https://synthetichealth.github.io/synthea/) `fhir/`
  output directory directly. Point `-d` at the Synthea directory;
  the new `clinosim/eval/synthea_adapter.py` auto-detects the
  per-patient Bundle layout and fans it into per-`ResourceType`
  NDJSON under `<cohort>/../synthea-normalized/` (or the
  `--synthea-normalize` override). Deterministic conversion so scores
  are reproducible. Synthea is an **optional** dependency — nothing
  in clinosim imports it at runtime. Full comparison walk-through at
  `docs/synthea-comparison.md`; 7 unit tests cover the adapter.
- **Clinical contradiction checks** (P1-9): two new checks on the
  `clinical` axis of `clinosim eval` — `condition_lab_coherence`
  (aggregate over 8 canonical pairings: sepsis-lactate, DKA-HCO₃,
  MI-troponin, CKD-creatinine, T2DM-HbA1c, pneumonia-WBC, anemia-Hgb,
  CHF-BNP) and `medication_lab_coherence_warfarin` (PT-INR therapeutic
  band on warfarin patients). Each pairing draws laboratory
  observations within ±7 days of the Condition onset and scores the
  overall violation rate against thresholds PASS ≤ 5% / WARN ≤ 25% /
  FAIL > 25% with per-pairing detail on the report. Full rule catalog
  with clinical rationale + literature source lives at
  `docs/eval-rules.md`; `docs/eval.md` clinical-axis table updated;
  new page wired into the docs site nav under Reference. 5 new unit
  tests. Clinical axis check count 5 → 7.
- **FHIR server ingestion guide** (P1-12):
  [`docs/fhir-server-ingestion.md`](docs/fhir-server-ingestion.md)
  walks through loading a generated cohort into a FHIR R4 server via
  the Bulk Data Access `$import` operation, using HAPI FHIR (Docker)
  as the concrete OSS example and listing InterSystems IRIS for Health,
  Microsoft FHIR Server, and Google Cloud Healthcare API as
  vendor-neutral alternatives. Covers per-file POST for small cohorts,
  `$import` for larger ones, dependency-ordered loading to avoid
  reference-integrity errors, JP Core profile validation notes, and a
  round-trip determinism check. Wired into the docs site nav under
  Guides. Vendor-neutral by design: no code path depends on any
  specific FHIR server product.
- **MkDocs documentation site** (P1-11): `mkdocs.yml` at repo root
  configures a Material-themed site at
  [tomookuyama.github.io/clinosim](https://tomookuyama.github.io/clinosim/)
  organized into Home / Getting started / Concepts / Reference / Guides
  / Development / Governance tabs. Existing `docs/` markdown and
  transcluded root files (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`,
  `MODULES.md`, `DESIGN.md`, ...) are referenced via
  `mkdocs-include-markdown-plugin` so there is no duplication or drift.
  Internal-only subtrees (`audit-cycles/`, `reviews/`, `design-notes/`,
  `superpowers/`) are excluded from the published site; contributors
  read them directly on GitHub. New `docs` optional dependency group in
  `pyproject.toml` (`pip install -e ".[docs]"`) installs the build
  toolchain. New `.github/workflows/docs.yml` builds on every PR and
  deploys to `gh-pages` on master push. README documentation badge +
  link added. GitHub Pages must be enabled manually once at
  Settings → Pages → "Deploy from a branch: gh-pages / (root)".
- **`clinosim eval` public evaluation framework** (P1-8): new package
  `clinosim/eval/` scoring any generated cohort on three axes
  (**structural** / **clinical** / **locale**). 15 checks total
  (5 per axis, severity-weighted). Auto-detects US vs JP from cohort
  content when the layout is flat. Emits JSON (machine-readable) +
  Markdown (human) via `--json` / `--md`; `--strict` exits 1 on any
  FAIL. Distinct from `clinosim audit run` (internal per-Module PR
  gate) — `eval` targets external researchers grading synthetic
  cohorts before use. 16 unit tests + 2 end-to-end tests
  (us-100 + jp-100 presets). Full reference at `docs/eval.md`. First
  real bug the tool caught (US Composition CJK leak from
  hpi_template.onset_pattern) filed as `good first issue` #149.
- **Dataset presets** (P1-6): `datasets/` directory with four named
  presets — `us-100`, `us-1000`, `jp-100`, `jp-1000` — each carrying a
  `spec.yaml` (params) and a dataset card in HuggingFace format. New
  CLI `clinosim dataset list` / `clinosim dataset build <name> -o <dir>`
  subcommand under `clinosim/dataset/` reads the spec and delegates to
  `clinosim generate` so no logic is duplicated. Zenodo integration
  (`.zenodo.json` at repo root) mints a DOI on every tagged release.
  Release workflow extended to build all four presets and attach them
  to the GitHub Release as `clinosim-dataset-<name>-vX.Y.Z.tar.gz`
  starting v0.3.0 onward. 13 unit tests
  (`tests/unit/test_dataset_cli.py`) cover preset discovery, spec
  validation, and CLI wiring; end-to-end smoke tested via
  `clinosim dataset build jp-100`.
- **End-to-end reproducibility gate** (P1-7): `scripts/reproduce.sh`
  runs `clinosim generate` twice per locale (US + JP by default) at
  the same seed and byte-diffs every NDJSON + CIF JSON. Excludes
  wall-clock metadata (`manifest.json` files + `cif/metadata.json`).
  `tests/integration/test_full_reproducibility.py` invokes the script
  as an integration test. New CI `reproducibility` job runs it as a
  hard gate on every push and PR — the SemVer determinism promise now
  has a machine-enforced guarantee. README `Testing → Reproducibility`
  subsection documents the script + environment variable overrides.

### Changed

- **Antibiotic regimen intent metadata moved to FHIR `meta.tag[]`** (Issue #349 Phase 2):
  regimen intent (`empirical` vs `narrowed`) was previously encoded in
  `MedicationRequest.id` suffix (e.g. `...cft-n` for narrowed). This violates
  FHIR R4's specification that `Resource.id` is an opaque identifier, and
  creates a 64-character bottleneck whenever id components grow. Refactored to
  emit intent in proper FHIR fields: `meta.tag[]` with
  `system="urn:clinosim:regimen-intent"` and `code="empirical"|"narrowed"`.
  CIF output (Order.medication_intent) is unchanged; FHIR only. `ABX_NARROW_SUFFIX`
  constant retired; audit gates updated to read `meta.tag[]` instead of id
  patterns. **This is the first phase of a three-phase architectural refactor to
  eliminate compound-key id encoding across all resource types.**

### Fixed

- **Immunization `lot_number` was non-deterministic across runs.**
  `clinosim/modules/immunization/engine.py` used Python's builtin
  `hash()` on strings to synthesize lot numbers; that hash is salted
  per-interpreter (`PYTHONHASHSEED`), so two runs at the same seed
  produced different values like `L591-201506-172` vs `L253-201506-427`.
  Replaced with a `hashlib.sha256`-based helper (`_det_hash`). Uncovered
  by the P1-7 `scripts/reproduce.sh` gate; the byte-diff cascaded from
  FHIR `Immunization.ndjson` into the CIF patient records that store
  the same field, so ~65% of CIF patient files also differed. Both are
  byte-identical now.

### Documentation

- **README positioning** (P0-5): new "Why clinosim?" section up-front
  with three concrete differentiators (physiology-driven coherence /
  JP + US native / YAML-driven extension), a Synthea comparison table
  (nine dimensions + "when to use which"), a sample FHIR Observation
  showing a physiology-derived PT-INR for a warfarin-anticoagulated
  patient, and placeholders for the demo GIF and architecture diagram
  (tracked as good-first-issue backlog).
- Table of Contents updated to include the new sections.
- `README.ja.md` translation of the new sections is intentionally
  deferred to a separate PR (scope discipline).

## [0.2.0] - 2026-07-12

Initial public v0.2 baseline release. Bundles the physiology-driven
generator (session-16-through-46 development) with the packaging /
distribution work that makes it installable.

### Changed

- **Version bumped 0.1.0 → 0.2.0** to align the version string with the
  codebase reality — `CLAUDE.md`, README `[![Status](...v0.2...)]` badge,
  and the "release: v0.2.0" example in the README's Versioning section
  had all been describing v0.2 while `pyproject.toml` still declared
  `0.1.0`. The v0.2 label was the truth; the version string was stale.
- **Removed `requirements.txt`.** It carried a `pip freeze` snapshot
  including a hard-coded `-e /Users/tokuyama/workspace/clinosim` local
  path, which broke `pip install -r requirements.txt` for anyone else.
  Runtime + development dependencies are now single-sourced from
  `pyproject.toml` `[project.dependencies]` and
  `[project.optional-dependencies]` (`dev` / `llm` / `parquet` / `all`).
  Migration: `pip install -e ".[dev]"` (developers) or
  `pip install clinosim` (users, once on PyPI).

### Packaging & Distribution

- `pyproject.toml`: switch to `dynamic = ["version"]` sourced from
  `clinosim/__init__.py::__version__` (single source of truth).
- Add PyPI-facing metadata: `keywords`, `classifiers`, `project.urls`
  (Homepage / Documentation / Source / Issues / Changelog).
- Explicit `[tool.hatch.build.targets.sdist]` manifest so YAML reference
  data and codes / locale files ship in the source tarball.
- README: pip-install instructions (users vs developers) + Versioning &
  Releases section + two prominent disclaimers (personal project /
  synthetic data only).
- New `CHANGELOG.md` (this file), Keep a Changelog format.
- New `tests/unit/test_packaging.py` — asserts version single-source-of-truth
  and console entry point registration.
- New `LICENSE` file at repo root (prior state: `pyproject.toml` declared
  MIT but no LICENSE text shipped).

### Added

- Population-driven, physiology-based synthetic EHR data simulation
  (13-variable hidden physiological state per patient).
- FHIR R4 Bulk Data Export (one NDJSON per resource type + manifest).
- Multi-country: US and JP locale packs (names, addresses, demographics,
  code mappings, insurance).
- 32 inpatient diseases + 46 ED / outpatient conditions.
- Snapshot date support (`--end` flag): partial data for in-progress
  encounters (AD-32).
- Complete AD-55 base data-enrichment set: microbiology, cardiac markers,
  nursing flowsheets, immunization, family history, code status, extended
  SDOH (smoking / alcohol / JP 要介護度).
- Always-on modules: device, HAI, antibiotic, imaging, allergy, document,
  triage, nursing.
- Opt-in JP insurance enrollment (FHIR Coverage, AD-54).
- Session 46: JP Core meta.profile emission for 16 primary resource types
  (100% emission rate).
- Session 46: drug_names_ja +54 entries + 17 silent-code-substitution
  fixes against MHLW YJ Excel authoritative master.
- Two-pass CIF generation (AD-65): structural + narrative separation.
- Canonical patient profile fixture library (AD-66) + `regenerate-goldens`
  CLI + `pytest -m regression` suite.
- Audit-cycle workflow (`docs/audit-cycles/`) + by-design registry
  (22 entries).

### Determinism guarantees

- Every module derives a sub-seed from a master seed (AD-16); no
  `random.random()` or global state.
- Per-order lab RNG isolation (AD-59): specimen rejection / hemolysis /
  technician / noise are per-order sub-RNGs, so a YAML edit cannot shift
  unrelated patients' cohorts.
- Verified across seed=42/100/200/300/400 in session 45's 5-seed chain.

### CI / Automation

- **GitHub Actions CI** (`.github/workflows/ci.yml`) — runs on every
  push to `master` and every PR. Hard gates: unit tests on Python 3.11
  + 3.12, integration tests on 3.12, and `python -m build` +
  `twine check` packaging smoke. Informational (non-blocking) jobs:
  `ruff check` / `ruff format --check`, `mypy clinosim/`. Concurrency
  cancels in-flight runs on newer pushes to the same branch.
  Integration timeout set to 60 min after empirical measurement showed
  CI runners run integration ~2.5x slower than the local baseline.
- README CI status badge pointing at the workflow.
- `Makefile` `lint` / `typecheck` / `format` targets pointed at a
  nonexistent `src/` prefix and failed immediately; corrected to the
  real `clinosim/` layout so the CI jobs (and local `make`) work.
- Add `types-PyYAML>=6.0` and `build>=1.0` to the `dev` extras so
  `mypy clinosim/` gets its yaml stubs and CI can build sdist + wheel
  without extra installs.
- **Release automation** (`.github/workflows/release.yml`) — tag push
  (`v*.*.*`) triggers `python -m build` + `twine check` + GitHub
  Release creation with wheel + sdist attached and release notes
  extracted from `CHANGELOG.md`. PyPI upload step is present but
  commented out until `PYPI_API_TOKEN` / trusted publishing is
  configured on the repository.

### Repository hygiene

- `CONTRIBUTING.md` — entry point covering setup, workflow, DCO
  signoff, and quality expectations. Links to
  `docs/CONTRIBUTING-modules.md` for module-level how-to.
- `CODE_OF_CONDUCT.md` — Contributor Covenant 2.1
  (contact: tomo.okuyama@gmail.com).
- `SECURITY.md` — GitHub Security Advisories as the disclosure
  channel; 90-day coordinated-disclosure target.
- `CITATION.cff` — machine-readable citation metadata (CFF 1.2.0)
  that GitHub renders as the "Cite this repository" button.
- `.github/ISSUE_TEMPLATE/{bug_report,feature_request}.yml` +
  `config.yml` disabling blank issues and routing questions to
  Discussions, security to Advisories, and module how-to to
  `docs/CONTRIBUTING-modules.md`.
- `.github/PULL_REQUEST_TEMPLATE.md` — PR checklist with a mandatory
  determinism-impact statement and DCO reminder.
- `.github/workflows/dco.yml` — hard-gate DCO check: every PR commit
  must carry a `Signed-off-by:` trailer (see `CONTRIBUTING.md#dco`
  for how to sign / retro-sign a branch).
- README `Governance & Community` section indexing all of the above.
