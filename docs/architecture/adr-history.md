## Part 9: Japanese narrative localization (2026-04-13)

### AD-42: Code-side unit conversion for Japanese locale

CIF stores lab values in SI units (CRP in mg/L). Japanese clinical convention uses mg/dL for CRP.
Rather than asking the LLM to convert (which was inconsistent), conversion happens in code:

- `hospital_course_extractor.format_lab_trends(trends, language="ja")` applies `_JA_CONVERSION` factors
- `document_generator._initial_labs(record, language="ja")` applies the same conversion
- `_JA_CONVERSION = {"CRP": 0.1}` — multiply mg/L by 0.1 to get mg/dL
- Prompts say "use input units as-is" — no LLM-side conversion

This is extensible: add entries to `_JA_CONVERSION` and `_UNIT_MAP_JA` for other locale-specific units.

### AD-43: Japanese narrative prompt quality rules

All 5 Japanese prompts (`prompts/ja/*.yaml`) enforce:

1. **Staff name suffix**: "医師名には必ず「医師」を付けてください" — prevents inconsistent Dr./no-prefix output
2. **Unit passthrough**: "検査値の単位は入力データのまま使用してください" — prevents LLM from annotating "(換算値)" or showing conversion work
3. **No fabrication**: all prompts prohibit inventing data not present in input (consistent with EN prompts)

### Chronic medication base code fallback

`chronic_medications.yaml` keys are specific ICD codes (e.g., `E11.9`). After discharge,
`_deactivate_to_layer1()` normalizes codes to base form (`E11`). The medication lookup in
`inpatient.py` now falls back to base code:

```python
spec = chronic_meds.get(code) or chronic_meds.get(code.split(".")[0])
```

This matches the existing fallback in `activator.py:326` and prevents medication loss on readmission.

### JP FHIR localization summary

The FHIR R4 adapter applies Japanese localization when `country="JP"`:

| Resource | Field | JP value |
|---|---|---|
| Location | name | `4E病棟`, `4E-01号室` |
| Encounter | type | `入院`, `外来`, `救急` |
| Encounter | serviceType | `内科`, `外科`, etc. |
| Patient | maritalStatus | `既婚`, `未婚` |
| MedicationRequest | dosageInstruction.route | `経口`, `静注`, `皮下注` |
| MedicationRequest | dosageInstruction.timing | `1日1回`, `1日2回`, `6時間毎` |
| Practitioner | qualification | `医師` |

All localization is at FHIR output time (AD-30). CIF remains language-neutral.

---

## Part 10: FHIR standards compliance + occupational injuries (2026-04-19)

### AD-44: Enrichment is language-neutral

A/B test on 8 patients × 2 document types (admission_hp, discharge_summary) confirmed:

| Aspect | A (pre-localized JP) | B (English, LLM translates) |
|--------|---------------------|---------------------------|
| Drug/procedure names | Both correct | Both correct |
| Natural Japanese flow | Slightly mechanical | More natural |
| CRP unit | Correct (mg/dL) | **Wrong** (mg/L leaked) |
| Diagnosis short names | Correct | ICD full names (unnatural) |
| Token usage | 9,219 | 9,231 (≈ identical) |

**Conclusion**: LLM translates free text well, but fails at math (CRP) and code normalization
(ICD display). Keep code_lookup + CRP conversion only. Everything else English.

### AD-45: Occupation model

```
PersonRecord.occupation: str  →  PatientProfile.occupation: str
                                  ↓
                         FHIR Observation (LOINC 11341-5, social-history)
```

Categories: manufacturing, construction, agriculture, healthcare, service, office,
transportation, education, homemaker, student, retired, unemployed, other.

`demographics.yaml` provides:
- `occupation_distribution.working_age` — per-country labor statistics
- `occupation_risk_multipliers` — per-injury-type risk by occupation (e.g. crush_injury_hand × 6.0 for manufacturing)

### AD-46: Multilingual FHIR coding

Condition and Procedure resources emit dual `coding[]` entries:

```json
{
  "coding": [
    {"system": "icd-10", "code": "J44.1", "display": "その他の慢性閉塞性肺疾患"},
    {"system": "icd-10", "code": "J44.1", "display": "Other chronic obstructive pulmonary disease"}
  ],
  "text": "COPD（慢性閉塞性肺疾患）"
}
```

`_build_diagnosis_codeable_concept()` tries `icd-10` → falls back to `icd-10-cm` → `"(display unavailable)"`.
`code.text` uses `_CONDITION_SHORT_NAME` for search-friendly abbreviations (AD-49).

### AD-47: Observation referenceRange + interpretation consistency

Per FHIR R5 Note 5: "The interpretation should be consistent with the reference range when both
are provided."

- Lab interpretation recomputed from value vs normal range (not CIF flag alone)
- Critical flags (H*/L*/critical) → directional LL/HH (not generic AA)
- Vital signs emit two referenceRange entries: `type=normal` and `type=treatment` (critical/panic)
- SpO2: `crit_high=None` (no upper critical — 100% is normal, not HH)

### AD-48: procedure_name removed from CIF

Strict AD-30 compliance: `ProcedureRecord` no longer has `procedure_name` field.
Display is resolved at output time via `code_lookup("k-codes"|"cpt", code, lang)`.
Both `procedure_code_jp` and `procedure_code_us` are stored for multilingual output.
`_resolve_procedure_name(proc_dict, lang)` is the shared helper across all consumers.

### Work-related injury YAMLs

4 inpatient (disease/reference_data/):
- `crush_injury_hand.yaml` (S67.2, ICD)
- `industrial_burn_severe.yaml` (T31.2, ICD)
- `fall_from_height.yaml` (T07, ICD)
- `electrical_injury.yaml` (T75.4, ICD)

2 ED (encounter/reference_data/):
- `eye_foreign_body.yaml` (T15.0, ICD)
- `chemical_exposure.yaml` (T54.9, ICD)

All have `probability` (for ED weighted selection) and age_rates/sex_ratio (for inpatient
incidence). Occupation risk multipliers concentrate events in industrial workers.

---

### AD-61: Lab ServiceRequest emission, panel-aware grouping

**Status:** Accepted (PR1, 2026-06-29)
**Context:** EHR/EMR sample dataset target (Tier 1 #1) requires FHIR
ServiceRequest for lab order lifecycle. JP Core / US Core idiomatic
emission is panel-level (1 SR per CBC, not 1 SR per WBC/Hb/Hct/Plt).
**Decision:** Add `Order.panel_key` 1 field (empty = stand-alone). Order
engine reuses lab_panel_groups.yaml (canonical loader unified in
`order/panel_grouping.py`) to assign panel_key + shared ordered_datetime
to panel members. New `_fhir_service_request.py` builder groups Orders by
`(encounter_id, panel_key, ordered_datetime)` to emit 1 SR per panel
instance; stand-alone Orders emit 1 SR each. JP Core compliance via HL7
v2-0203 PLAC identifier type + dual category coding (SNOMED 108252007 +
v2-0074 LAB).
**Consequences:** rng draw count change for lab orders (per-panel rather
than per-test draw). e2e attribute-based tests unchanged (run_alpha golden
patient FORCED-0001 not affected). Production scale verified at US p=10k
+ JP p=5k (362k+42k SR, 0 dangling refs, audit silent_no_op 7/7 PASS).
ServiceRequest is the foundation for Tier 1 #2-#7 (Imaging / NutritionOrder
/ ADT / DocumentReference / Appointment / CarePlan).

### AD-62: Imaging metadata-only chain with WADO-RS placeholder

**Status:** Accepted (Tier 1 #2, 2026-06-30)
**Context:** Tier 1 #2 EHR/EMR sample dataset extension required imaging
metadata foundation for radiology NLP/IE/CDSS/revenue-cycle/PACS-migration
evaluation. DICOM pixel data generation deferred to external image-gen AI.

**Decision:** Adopt always-on Module pattern (device/hai/antibiotic precedent)
with `ImagingStudyRecord` in `extensions["imaging"]`. Emit 4 FHIR resources:
ServiceRequest (imaging category, SNOMED 363679005 + v2-0074 RAD),
ImagingStudy (with urn:dicom:uid identifier, DCM modality, multi-series),
DiagnosticReport (radiology variant with findings + impression in `text.div` +
`conclusion`), Endpoint (WADO-RS placeholder URL via
`hospital_config.imaging.wado_base_url`). Polymorphic `_fhir_service_request`
dispatches LAB + IMAGING category from one builder.

**Consequences:**
- CIF → FHIR no-drop invariant enforced (emission matrix: every
  `ImagingStudyRecord` maps 1:1 to ImagingStudy + Endpoint + radiology DR
  + imaging SR)
- Future image-gen AI integration point: Endpoint.address substitution +
  urn:dicom:uid lookup
- AD-55 always-on Module count increases to 4 (device, hai, antibiotic,
  imaging). POST_ENCOUNTER order=90 (after antibiotic=85)
- 15-check `lift_firing_proof` (AD-60 audit) verifies non-zero ImagingStudy
  + Endpoint + radiology DR + imaging SR emission and JP locale display
  correctness (modality display / bodySite display / DR.code / conclusion)
- Legacy IMAGING orders (Chest_Xray / CT_abdomen_pelvis without
  `imaging_modality` metadata) are silently skipped by the enricher and
  remain as Order-only records without ImagingStudy (tracked for migration
  in TODO.md)

### AD-63: Document narrative + structured event density foundation

**Status:** Accepted (Tier 1 #3 α-min-1, 2026-07-01)
**Context:** Tier 1 #3 EHR/EMR sample dataset extension required clinical
document density foundation. Pre-chain baseline: DocumentReference = 0 (Stage 1
`generate` only; Stage 2 `narrate` required separate LLM step), Composition = 0,
ClinicalImpression = 0. Target: default Stage 1 template-based emission of the
3 core document types for all inpatient/ICU/rehab encounters. AllergyIntolerance
schema was 3-field (allergen string only); upgrade to 8-field SNOMED-coded schema
(allergen code + reaction manifestation + category + criticality + clinical status +
verification status + onset period + note) per JP Core Allergy profile.

**Decision:** Two new always-on Modules (same `enabled=lambda c: True`
pattern as device/hai/antibiotic/imaging):
- `allergy` (POST_POPULATION order=10): replaces activator.py inline 15% allergy sampling with a
  proper enricher that writes `PersonRecord.allergies: list[Allergy] | None`
  (None = not-yet-enriched sentinel; [] = no allergy after sampling). Produces
  SNOMED-coded `AllergyIntolerance` via new `_fhir_allergy_intolerance.py` builder.
- `document` (order=95): emits `ClinicalDocument` records (free_text for DR + CI,
  composition for Composition) via a `TemplateNarrativeGenerator` 5-step fallback chain.
  LLM-driven generation deferred (Task 15 will wire the existing LLM provider integration).

CIF storage: `CIFPatientRecord.documents` (typed field) stores `list[ClinicalDocument]`;
`extensions["clinical_impressions"]` stores `list[ClinicalImpressionRecord]`. Core type
`ClinicalDocument` gains two fields: `sections: dict[str, str]` (section name → text,
required for Composition.section[] reconstruction) and `format_type: str` (dispatch key
for builder selection: "free_text" vs "composition").

Three new FHIR builders:
- `_fhir_documents.py` (DOC_REFERENCE_ID_PREFIX = "doc-")
- `_fhir_composition.py` (COMPOSITION_ID_PREFIX = "comp-")
- `_fhir_clinical_impression.py` (CLINICAL_IMPRESSION_ID_PREFIX = "ci-")

**Consequences:**
- Stage 1 `generate` now emits 3 document-class FHIR resource types by default,
  closing the EHR sample dataset document-density gap without requiring `narrate`
- Task 15 (same branch) completed the migration: legacy `narrative_generator.py` /
  `document_generator.py` are deleted; activator.py allergy inline sampling is removed.
  No dedup guard needed — no coexistence path remains.
- CIF→FHIR no-drop invariant enforced via `ClinicalDocument.sections` field:
  Composition builder reads sections directly without re-parsing raw_text (Task 8
  fix lesson — "sections authoritative for COMPOSITION; raw_text for FREE_TEXT only")
- AD-55 always-on Module count increases to 6 (device, hai, antibiotic, imaging,
  allergy, document). Stages: allergy (POST_POPULATION order=10) → document (POST_ENCOUNTER order=95)
- 17-check `lift_firing_proof` (AD-60 audit) verifies 4 canonical ID prefixes,
  4 emission gates, 3 ID-prefix format checks, 5 no-drop invariants (spec §3.4)
- Future phases: α-min-3 (outpatient/ED POST_ENCOUNTER gap fix + Practitioner roster expansion),
  β-JP-1 (full JP localization / QuestionnaireResponse / 厚労省必須文書),
  β-2 (手術記録 / MedicationDispense / Procedure density)

### AD-64: Nursing + Outpatient + ED + CareTeam density foundation

**Status:** Accepted (Tier 1 #3 α-min-2, 2026-07-01)
**Context:** α-min-1 (AD-63) established the Stage 1 document emission infrastructure for
inpatient encounters only. Three major gaps remained: (1) CareTeam = 0 across all encounter
types, (2) nursing domain documents = 0 (no nursing-domain always-on Module), (3) outpatient /
emergency encounter documents = 0 (no outpatient SOAP / ED note / triage note). The EHR/EMR
sample dataset target requires nurse-authored document density and primary team allocation for
all encounter types.

**Decision:** Three new always-on POST_ENCOUNTER Modules (same `enabled=lambda c: True` pattern
as device/hai/antibiotic/imaging precedents):

1. **`triage` (POST_ENCOUNTER order=93)**: ED-only enricher. Samples JTAS (JP) / ESI (US) triage
   level, arrival_mode (ambulance/walk-in), and acuity_score from `triage_protocols.yaml`.
   Writes `EncounterRecord.triage_data` (new field). Consumed by document_enricher for
   `ED_TRIAGE_NOTE` LOINC 54094-8 dispatch.

2. **`nursing_assignment` (POST_ENCOUNTER order=94)**: Inpatient/ICU/rehab enricher. Assigns a
   primary nurse from the StaffRoster for the encounter's ward. Writes
   `EncounterRecord.primary_nurse_id` (new field). Consumed by `_fhir_care_team.py` builder
   for CareTeam.participant[1]. **Naming note**: the module directory is `modules/nursing/` but
   the enricher function is `nursing_enricher` (POST_ENCOUNTER). The existing POST_RECORDS nursing
   module (`observation/nursing.py`) handles NEWS2/GCS/Braden/Morse — these are DIFFERENT modules
   registered in DIFFERENT stages under the same directory.

3. **`_fhir_care_team.py` builder**: New FHIR builder registered via `register_bundle_builder()`
   as `_bb_care_teams`. Emits one CareTeam resource per encounter (ALL encounter types). Two-name
   scope: participant[0] = attending physician, participant[1] = primary nurse (when assigned).
   CareTeam ID = `careteam-{encounter_id}` (CARE_TEAM_ID_PREFIX canonical constant).

4. **6 new DocumentType specs** in `document_type_specs.yaml`:
   - `admission_nursing_assessment` (78390-2, Composition, admission_once, inpatient)
   - `nursing_shift_note` (34746-8, DocumentReference free_text, daily, inpatient)
   - `nursing_discharge_summary` (34745-0, Composition, discharge_once, inpatient)
   - `outpatient_soap` (34131-3, Composition, encounter_once, outpatient)
   - `ed_note` (34878-9, Composition, encounter_once, emergency)
   - `ed_triage_note` (54094-8, DocumentReference free_text, encounter_once, emergency)

   `DocumentTypeSpec.encounter_types_supported` field (introduced in α-min-2 Task 10) controls
   dispatch per encounter_type. α-min-1 specs now carry explicit `[inpatient, icu, rehab_inpatient]`
   allowlists (Task 10 data-quality fix: prevents leaking inpatient docs into outpatient/ED).

5. **46 encounter YAML narrative extensions**: All 46 encounter YAML files received a `narrative:`
   block with outpatient_soap / ed_note / ed_triage templates for outpatient_soap + ED encounter
   types. 5 priority conditions have detailed narrative; 41 use baseline template text.

6. **Task 8 LOINC verification**: 3 of 6 candidate LOINC codes were corrected via NLM
   verification (ADMISSION_NURSING_ASSESSMENT 34820-1→78390-2, OUTPATIENT_SOAP 11488-4→34131-3,
   ED_NOTE 51841-6→34878-9). All codes registered in `codes/data/loinc.yaml` (EN + JA bilingual).

**Consequences:**
- CIF → FHIR no-drop invariant: CareTeam (1:1 with Encounter) + 3 nursing document types
  (1:1 with inpatient encounters) enforced via lift_firing_proof equality_checks 18-25
- AD-55 always-on Module count increases to 8 (device, hai, antibiotic, imaging, triage,
  nursing_assignment, allergy, document). POST_ENCOUNTER ordering: 70/80/85/90/93/94/95
- **Known production gap**: outpatient.py + emergency.py do NOT invoke POST_ENCOUNTER enrichers
  (only inpatient.py does). OUTPATIENT_SOAP / ED_NOTE / ED_TRIAGE_NOTE produce 0 resources in
  production. Dispatch logic is correct (verified by audit proof checks 22-25); fix requires
  adding `run_stage(POST_ENCOUNTER, ...)` to outpatient.py + emergency.py (targeted for α-min-3).
- **Naming collision guard**: `modules/nursing/` contains both `nursing_enricher` (POST_ENCOUNTER
  order=94, primary_nurse assignment) and `nursery_enricher` (POST_RECORDS observation).
  Always specify the enricher name when referencing. `nursing_assignment` = POST_ENCOUNTER.
  `nursing` (observation) = POST_RECORDS.
- **CareTeam 2-name scope**: β-JP-1 will expand to 6-name multi-disciplinary team
  (pharmacist / nutritionist / rehab / MSW / charge nurse). AD-64 scope = physician + nurse only.
- 25-check `lift_firing_proof` (17 α-min-1 + 8 α-min-2). silent_no_op PASS both US + JP cohorts.
  Clinical axis PASS: 158,811 US / 16,046 JP CareTeam, 0 unknown_attending.
- Production cohort: US p=10k (158,811 CareTeam + 46,558 DR + 17,946 Composition) +
  JP p=5k (16,046 CareTeam + 7,416 DR + 970 Composition). DQR:
  `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md`

### AD-65: Structural + Narrative CIF file separation (two-pass generation)

**Status:** Accepted (Tier 1 #3 α-min-2b, 2026-07-02, session 28)

**Context:**
- clinosim's initial architecture (`clinosim/modules/output/SPEC.md`) defines a three-stage
  pipeline: structural CIF Stage 1 (immutable) / narrative Stage 2 (separate version dir) /
  Stage 3 (adapter merge).
- α-min-1 Task 15 (commit `2c09b6a099`) removed the legacy narrative subsystem
  (`document_generator.py` 951 lines, `narrative_generator.py` 205 lines) and folded narrative
  generation into `document_enricher`. At the time, this closure of Stage 1 default-emission gaps
  was correct; however, as a long-term Stage 2 replacement architecture, it was a premature
  deletion, causing drift from the `clinosim/modules/output/SPEC.md` Stage 2 design.
- Session 27 Clinical Integrity review uncovered three Critical narrative bugs. The inline-only
  pattern requires full cohort regeneration to fix them, destroying development velocity.
- User explicitly indicated (session 27→28): the original design assumed structural CIF and
  narrative CIF as separate files = restoration of the SPEC.md original design.

**Decision:**
1. Refactor `ClinicalDocument` to stub-only: metadata + author + encounter binding, with
   `narrative: ClinicalDocumentNarrative | None` field (new type). Narrative content
   (text/sections/facts_used) population is forbidden in Stage 1.
2. Restore two-pass CIF generation pipeline (SPEC.md original design intent, fully restored).
3. Reinstate `clinosim narrate` CLI verb (template mode as fallback; LLM actual invocation deferred
   to β-JP-1).
4. Establish Bedrock prompt-cache-friendly walk order contract: `NarrativePass` base class
   guarantees `(doc_type, language)` group serial iteration.
5. Extend `NarrativeContext` with three enhancements: `NarrativeSpine` (scenario anchoring),
   `materialized_facts` (fact-first generation), `section_facts` (COMPOSITION section extraction).
6. Fix silent CLI override (Bug D): `-p` explicit values no longer silently overridden by
   `recommended_population`.
7. Add dev iteration facility: `test-disease --format` + `test-encounter --format` +
   `--output` flag + standalone `narrate` verb enable narrative bug verification cycle to
   10–30 seconds (vs. 5–50 min full generate).

**Consequences:**
- Narrative bug verification: `narrate --tasks <task>` (~30 sec) + structural via `test-disease
  --format all` (~10 sec) = 100× faster development cycle.
- FHIR builders now exclusively access narrative content via `doc.narrative.*` → single source
  of truth (prevents `document_enricher` and Stage 2 pass from conflicting).
- β-JP-1 can implement `LLMNarrativePass` as drop-in subclass of `NarrativePass` base class,
  inheriting Bedrock walk-order contract without modification.
- All 39 existing e2e goldens require full regeneration (no backwards compatibility).
- Five new AD-65 rules added to `CLAUDE.md` (prevents next-session drift: two-pass invariant,
  stub-only enricher, narrative post-simulation, walk order, FHIR builder wrapper).

**Alternatives considered:**
- **Approach A** (Inline populate + writer split): Lower silent-no-op risk; weaker Stage 2
  replacement symmetry → rejected.
- **Approach B** (Explicit two-pass without auto-invoke): Larger UX change → rejected in favor
  of inline default (preserves `clinosim generate` user experience).
- **Approach C** (Flat field + physical split without wrapper): Weaker defense-in-depth → rejected
  in favor of `ClinicalDocumentNarrative` wrapper type.

**Related ADRs:** AD-30 / AD-55 / AD-56 / AD-60 / AD-63 / AD-64

---

### AD-66 · Canonical patient profile fixture library for narrative regression

**Date:** 2026-07-03 (α-min-2c chain)

**Status:** Accepted

**Context:**
The AD-65 two-pass CIF architecture enables template narrative output to be
compared against a canonical baseline. β-JP-1 will introduce `LLMNarrativePass`
which produces non-deterministic LLM output. To detect narrative regression
(template drift, LLM drift, semantic changes), we need a canonical set of
deterministic patient profiles + expected narrative outputs to diff against.

**Decision:**
Ship 6 canonical patient profile YAML fixtures in `tests/fixtures/patient_profiles/`,
each accompanied by a `<profile>.golden.json` file containing the expected
template narrative output at seed 42. A `pytest -m regression` suite
subprocess-invokes `clinosim test-disease --patient-profile <id>` and byte-diffs
the generated narrative against the golden.

Introduce a new `PatientProfile` Pydantic type in `clinosim/types/config.py`
with `.to_forced_scenario()` transform, and a `clinosim regenerate-goldens`
CLI subcommand for bootstrap + re-generation.

Scope-in for α-min-2c: 6 disease-based inpatient/ICU profiles only.
Scope-out (deferred to β-JP-1 or later): ED/outpatient encounter profiles
(requires symmetric `test-encounter --patient-profile` extension), LLM
semantic diff mechanism, GitHub Actions CI integration, clinical review loop.

**Consequences:**

Positive:
- β-JP-1 unblocked — deterministic canonical patients for template vs LLM narrative regression
- Adding new profiles is a documented workflow (regenerate + review + commit)
- Determinism enforced at seed 42 via existing AD-16 discipline

Negative:
- Additional maintenance burden when template narrative logic changes
  (all goldens need regeneration)
- Fixture library is separate from disease YAMLs (contributors need to
  understand both)

Neutral:
- 6 profiles × ~10-76 documents/profile × N sections = ~100-500 KB of golden
  JSON checked into git (acceptable)

**Alternatives considered:**

- **Input + narrative expectations in single YAML**: rejected — LLM output
  cannot be represented as expected substrings without semantic diff engine
  (deferred to β-JP-1 scope)
- **Input + reference golden narrative embedded (base64 in YAML)**: rejected
  — YAML would grow to 100-500 lines/profile, git diff becomes noisy, LLM
  parallel storage difficult
- **Integrated into existing AD-60 `audit run` framework**: rejected —
  fixture regression is per-profile deterministic byte-diff, not cohort
  statistics; overloading audit purpose

**Related ADRs:** AD-16 / AD-56 / AD-63 / AD-65

**Related documents:**
- Spec: `docs/superpowers/specs/2026-07-03-tier1-3-alpha-min-2c-fixture-library-design.md`
- Plan: `docs/superpowers/plans/2026-07-03-tier1-3-alpha-min-2c-fixture-library-plan.md`

---

### AD-67 · Severity single source of truth (disease YAML canonical, hybrid c2)

**Date:** 2026-07-06 (session 38, FP-SEV-MODEL)

**Status:** Accepted

**Context:**

Three disconnected severity systems coexisted: (A) locale `demographics.yaml`
per-disease `severity_beta` continuous draw (the only live inpatient source, also
load-bearing for the hospitalization gate), (B) disease-YAML `severity.distribution`
+ `modifiers` (present in all 30 diseases with clinical-literature citations but read
by zero code — dead), (C) encounter-YAML `severity_distribution` for the ED path.
The float→category boundary was hardcoded (`inpatient.py`, `> 0.7`/`> 0.3`) and the
minimum was defined twice (`severity_minimum` float + `minimum_severity` str, clamped
separately). System B being dead meant the authored, comorbidity-aware severity
distributions never reached the FHIR output — the largest C1 (silent-drop) instance
in the FHIR-completeness goal.

**Decision:**

Disease-YAML `severity.distribution` × `modifiers` is the single canonical severity
source (hybrid **c2**). A new `clinosim/modules/disease/severity.py` owns severity
sampling and the canonical category↔score boundary (`SEVERITY_SCORE_RANGES`,
`category_from_score`). `sample_severity(protocol, person, rng)` samples a category
from the distribution × person-derived comorbidity modifiers (age/comorbidity), clamps
to `minimum_severity`, and maps the category to a uniform continuous score; the score
still feeds the population-time hospitalization gate and re-derives the same category.
`population/engine.py` calls it (new population→disease dependency); `inpatient.py`
uses `category_from_score`; `emergency.py` shares the categorical primitive. Locale
`severity_beta`/`severity_minimum` are retired (incidence-only). Import-time
`_validate_severity_block` fails loud on malformed distribution / unknown modifier
condition / bad minimum / non-positive multiplier (silent-no-op defense).

Modifier conditions were enumerated from the 30 YAMLs (66 distinct), partitioned into
EVALUABLE (person-derived, ~34: age/comorbidity/BMI/smoking) and RESERVED_INTRINSIC
(disease sub-type / scenario-specific, ~32: `anterior_wall_MI`, `gcs_below_8`, etc.),
which are KNOWN (validation does not raise) but skipped this chain.

**Consequences:**

Positive:
- The authored, comorbidity-aware severity distributions now drive generation
  (e.g. acute_mi severe rate ~0.11 → ~0.5 for the older/comorbid MI cohort).
- Single owner for the category↔score boundary and the minimum (no duplicate clamp).
- Silent-no-op defense extended to the disease-YAML severity block.

Negative / neutral:
- New-feature-class change: inpatient cohort composition (hospitalization rate /
  severity mix) shifts toward disease-YAML distributions; goldens regenerate
  (profile goldens are forced-severity so byte-unchanged; cohort output shifts).
- Disease-intrinsic modifiers deferred (scenario-flag mechanism) — TODO.

**Related ADRs:** AD-16 / AD-55 / AD-57 (scenario flags sibling pattern)

**Related documents:**
- Spec: `docs/superpowers/specs/2026-07-06-severity-single-source-c2-design.md`
- Plan: `docs/superpowers/plans/2026-07-06-severity-single-source-c2.md`
- Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` (FP-SEV-MODEL)

---

### AD-68 · archetype_modifiers wiring (dead YAML activation, sibling to AD-67)

**Date:** 2026-07-06 (session 38, FP-YAML-2b)

**Status:** Accepted

**Context:**

`archetype_modifiers` (23 disease YAMLs) was silently dropped at load (`extra="ignore"`)
and never read; `select_archetype` applied its own hardcoded `immune_reactivity` /
`treatment_sensitivity` heuristics instead. The YAML block is a superset (adds age,
comorbidities, disease factors) — a C1 (silent-drop) instance and the same
dead-authored-YAML class AD-67 addressed for severity.

**Decision:**

Wire `archetype_modifiers` into `select_archetype` (owner: `clinical_course/engine.py`),
replacing the hardcoded profile modifiers. `_eval_archetype_condition` evaluates each
modifier's condition — expression form (`<var> <op> <number>` for age / immune_reactivity /
treatment_sensitivity via a strict regex, NOT eval()) and named form (reusing
`disease.severity._evaluate_condition` for the overlapping comorbidity vocabulary;
disease-intrinsic conditions are reserved/skipped). `_apply_archetype_modifiers` adds the
effect deltas to the archetype probabilities before the single `rng.choice` (no new rng
draw). `DiseaseProtocol` gains `archetype_modifiers`; `_validate_archetype_modifiers`
fails loud at load when an effect targets an archetype the disease doesn't define
(silent-phantom guard), a condition is unknown, or a delta is non-numeric.

NOTE: `plateau` is a legitimate per-disease archetype NAME (defined in those diseases'
`course_archetypes`), not a typo for `plateau_then_recovery` — validation enforces
per-disease self-consistency (effect keys ⊆ the disease's own archetypes) rather than a
fixed canonical set.

**Consequences:**

Positive: the authored per-disease archetype adjustments (age/comorbidity → deterioration
share) now drive course selection; single silent-no-op-guarded path.
Negative/neutral: new-feature-class change (archetype distribution shifts, goldens
regenerate; profile goldens use forced-archetype so byte-unchanged). Disease-intrinsic
conditions deferred (shared scenario-flag mechanism with AD-67's reserved set).

**Related ADRs:** AD-16 / AD-67 (severity sibling)

**Related documents:**
- Spec: `docs/superpowers/specs/2026-07-06-archetype-modifiers-wiring-design.md`
- Plan: `docs/superpowers/plans/2026-07-06-archetype-modifiers-wiring.md`
- Registry: `docs/design-notes/2026-07-06-fix-point-registry.md` (FP-YAML-2)

---

### AD-69 · DiseaseProtocol extra="forbid" (author-time silent-drop defense)

**Date:** 2026-07-06 (session 38, FP-YAML-3)

**Status:** Accepted

**Context:** `DiseaseProtocol` used Pydantic's default `extra="ignore"`, so any
top-level YAML key not matching a model field was silently dropped at load. This was
the root cause of a whole class of C1 (silent-drop) defects — `diagnostic_difficulty`
placed top-level (fell back to 0.3), `archetype_modifiers` (23 files unread),
`severity.distribution` never read — and left new typos undetectable.

**Decision:** After resolving every orphan key (diagnostic_difficulty nested,
archetype_modifiers wired, and 4 unread keys — differential_diagnosis / rehabilitation /
precipitants / prerequisite — deleted), turn on `model_config = ConfigDict(extra="forbid")`
on `DiseaseProtocol` so an unrecognized top-level key raises at load. `EncounterConditionProtocol`
already uses `extra="allow"` (returns the raw dict); `PatientProfile` already uses forbid —
this brings the disease protocol into line. Also removed the vestigial `readmission`
model field (0 YAML, 0 readers).

**Consequences:** Byte-diff identical to master (deleted keys were never consumed) —
a refactor-class change. New disease-YAML authors must add a model field for any new
top-level key (or it fails loud).

**Dead-field triage (session 39, registry FP-YAML-3 follow-up):** of the 3
declared-but-unconsumed fields, only `reference_ranges` was removed — it duplicated the
live locale-side lab reference ranges (locale is the single source of truth, AD-30), so
the disease-YAML copy was pure drift. Its model field + 23×3 YAML blocks (banner + body,
1184 lines) were deleted byte-cleanly (all-deletions diff; the 6 profile goldens are
byte-identical). The other two were **retained as future-wiring seeds, not deleted**,
because both are authored clinical content with a documented downstream plan:
`drug_interactions` (real interaction pairs + clinical actions) seeds the planned FHIR
`DetectedIssue` resource (`docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`),
and `expected_vital_distributions` is a candidate verification target for the cohort-level
completeness audit axis (FP-COMPLETENESS-GATE). Deleting them would have destroyed authored
seeds for planned features. One follow-up remains (registry FP-YAML-3): the raw-dict
consumption path in `order/engine.py` bypasses Pydantic (not covered by forbid).

**Related ADRs:** AD-67 / AD-68 (the severity + archetype activations this unblocks/hardens)

**Related documents:** `docs/design-notes/2026-07-06-fix-point-registry.md` (FP-YAML-3);
`docs/design-guides/data-model-and-completeness-conventions.md` §2


---

### AD-70 · JP-CLINS lab coding: JLAC10 primary + LOINC secondary (international interoperability)

**Date:** 2026-07-26 (session 68, migration PR 4)

**Status:** Accepted

**Context:**

JP-CLINS 検体検査 migration (PR #396–#404) established JLAC10 as the primary coding system
for 1,898 CoreLabo analytes (session 67 axis 100% completion). The architecture decision for
secondary coding systems arose: should LOINC be retained as secondary coding alongside JLAC10
primary, or removed entirely for JP-only purism?

Three options were considered:

- **Option A (JP purism):** Remove LOINC secondary coding entirely; emit JLAC10 primary only.
  Rationale: JP-CLINS is JP-specific data exchange standard; LOINC is redundant in domestic JP
  context. Removes ~0.5 KB FHIR overhead per exam instance.

- **Option B (interoperability):** Retain dual coding — JLAC10 as primary (discriminator + Fixed
  coding), LOINC as secondary. Rationale: allows downstream international-facing systems (cloud EHR,
  research integrations, academic medical data pipelines) to normalize into LOINC without losing
  JLAC10 traceability; supports the implicit contract that "any JP clinic can export to
  international viewer if needed."

- **Option C (branching):** Country-flag-based dispatch — `_fhir_observations.py` checks
  `country == "JP"` and omits LOINC for JP only. Rationale: keeps US output optimally compact,
  gives JP the choice.

**Decision:** **Option B** — retain dual coding (JLAC10 primary + LOINC secondary).

**Rationale:**

1. **Binding constraint:** JP Core `JP_Observation_LabResult.code` is defined with binding
   strength `example` (FHIR terms: weakest binding, "recommended but not required"). This means
   both **single-system coding** (JLAC10 only) and **multi-system coding** (JLAC10 + LOINC) are
   spec-compliant.

2. **International interoperability:** LOINC is the de facto global lab code standard. Dual coding
   enables downstream systems (research DBs, cloud EHR platforms, international healthcare
   networks) to accept clinosim export without custom mapping code. Removing LOINC forces those
   systems to maintain JLAC10→LOINC mapping tables externally, increasing integration friction.

3. **Metadata cost is acceptable:** Each lab Observation adds ~30–50 bytes (LOINC coding[] slice +
   system + code + display). At p=100 JP dataset, this is ~90–150 KB cumulative — negligible
   within the multi-GB export footprint. The `example` binding level does not impose a penalty
   for additional codings.

4. **Traceability and reversibility:** Retaining LOINC enables full round-trip mapping (JLAC10↔LOINC)
   without data loss. Removing it forecloses downstream reverse-mapping if a use case later
   requires it.

5. **Alignment with FA-1 principle (AD-56):** Adapters (FHIR builders) are single-responsibility
   (emit what CIF provides); CIF stores codes language-neutrally (AD-30). The dual-coding choice
   is a **FHIR presentation choice**, not a data-model choice — perfectly aligned with separating
   data from adapter.

**Consequences:**

Positive:
- Downstream systems can integrate clinosim export without custom mapping.
- JP and US outputs remain 100% identical (no branching logic to maintain).
- Future JP-CLINS profile evolution (if binding ever strengthens to `required`) is forward-compatible.

Negative/neutral:
- Slight FHIR size increase (~0.2–0.5% of per-dataset NDJSON).
- Authoring burden on LOINC code coverage (already complete; PR #396 ensured all 20 CoreLabo
  analytes have LOINC codes in `codes/data/loinc.yaml`).

Alternative deferred:
- If JP-CLINS 2.1 / JP FHIR profiles ever restrict binding to `required` + explicitly forbid
  non-JLAC10 coding, this ADR will be revisited and option A/C re-evaluated (with a separate
  migration chain to remove LOINC secondary). Until then, `example` binding is the governing
  constraint.

**Related ADRs:** AD-30 (CIF language-neutral) / AD-31 (Bulk Data compliance) / AD-56 (adapter
single responsibility) / AD-58 (output adapter registration pattern)

**Related documents:**
- Migration PRs: #396 (dispatcher refactor) / #398 (shared pkg loader) / #400 (analyte classifier)
  / #402 (CoreLabo emit) / #404 (Uncoded + LocalCode + sanitize)
- Session notes: `project_session_67_end_state.md` (axis completion, decision B adoption)
