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
