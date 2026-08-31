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

## [0.6.0] - 2026-08-31

**Release theme**: v0.6.0 rolls up substantial data-quality /
clinical-coherence / temporal-consistency fixes across Issues
#909 / #918 / #916 / #911 / #913 / #914 / #957 / #757 (session-93)
plus the pre-existing Unreleased batch from sessions 91-92 covering
#949-#1002. Every `### Fixed`, `### Added`, `### Changed`, and
`### Narrative CIF` / `### LLM prompts` subsection below shipped
between the v0.5.0 tag (2026-08-27) and this release.

**Classification: MINOR.** Multiple entries below (chronic prevalence
tuning, Z-code Condition removal, AVPU/GCS coupling, MedAdmin timing,
antibiotic template, monitoring pipeline) shift cohort statistics or
per-patient RNG shape, so structured CIF and downstream narrative CIF
byte-identity are not preserved across the v0.5.0 → v0.6.0 line.
A fresh `narrate` run is required after upgrade.

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
