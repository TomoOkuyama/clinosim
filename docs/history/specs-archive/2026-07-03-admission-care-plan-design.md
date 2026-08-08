# 入院診療計画書 (Admission Care Plan Document) — Design Spec

**Date:** 2026-07-03 (session 33)
**Status:** Approved for implementation
**Branch:** `feature/chain2-admission-care-plan` (to be created)
**先行:** N-chain (#135) / β-JP-1 chain 1a (#136) / chain 1b (#137) — narrative pipeline
complete, this is the first "chain 2" (厚労省4帳票) sub-project.

## 1. Problem

`TODO.md` "β-JP-1 phase — JP localization + 厚労省必須文書" lists 4 MHLW-mandated
documents. Of the 4, 入院診療計画書 (admission care plan) is the only one requiring **no
new prerequisite subsystem** — it can be added purely as a 10th `DocumentType` reusing the
existing `NarrativePass` / `DocumentTypeSpec` / generic `_fhir_composition.py` machinery
(verified: `_fhir_composition.py` iterates `sections.items()` generically, no hardcoded
section list — zero FHIR builder changes needed).

The other 3 (看護必要度D表 / 栄養管理計画書 / リハビリテーション計画書) each require a new
prerequisite subsystem (DPC scoring form shape, nutritionist role + NutritionOrder, rehab
ProcedureRecord) and are explicitly out of scope for this chain (remain as separate TODO.md
entries).

## 2. Authoritative source (verified, not fabricated)

- **LOINC 18776-5** = "Plan of care note" — verified via web search against loinc.org /
  findacode.com. No JP-specific LOINC code exists for 入院診療計画書; "Plan of care note"
  is the correct generic match (same convention as existing entries, e.g. 34117-2 "History
  and physical note" → ja "入院時記録").
- **MHLW form 別紙２** (`https://www.mhlw.go.jp/bunya/iryouhoken/iryouhoken15/dl/h24_02-07-40.pdf`,
  fetched + `pdftotext -layout` extracted 2026-07-03) — the standard acute-ward (7:1/10:1)
  admission care plan form. Confirmed 10 core fields (2 conditional fields marked ＊/◇ for
  亜急性期入院医療管理料 patients / functional-assessment patients are out of scope):

  | # | 別紙２ field (JP) | section key |
  |---|---|---|
  | 1 | 病棟（病室） | `ward_and_room` |
  | 2 | 主治医以外の担当者名 | `other_staff` |
  | 3 | 病名（他に考え得る病名） | `diagnosis` |
  | 4 | 症状 | `symptoms` |
  | 5 | 治療計画 | `treatment_plan` |
  | 6 | 検査内容及び日程 | `test_schedule` |
  | 7 | 手術内容及び日程 | `surgery_schedule` |
  | 8 | 推定される入院期間 | `estimated_los` |
  | 9 | 特別な栄養管理の必要性（有・無） | `special_nutrition_management` |
  | 10 | その他（看護計画・リハビリテーション等の計画） | `other_plans` |

  Excluded (別紙２ ＊/◇ conditional fields, subacute-only / functional-assessment-only):
  在宅復帰支援担当者名, 在宅復帰支援計画, 総合的な機能評価.

  A separate variant form (別紙２の２) applies to 療養病棟 (rehab/long-term wards) with a
  different field set — **not** this spec's target, hence `rehab_inpatient` is excluded
  from `encounter_types_supported`.

## 3. Scope

### 3a. Registry additions

- `DocumentType.ADMISSION_CARE_PLAN = "admission_care_plan"` in `clinosim/types/document.py`.
- `codes/data/loinc.yaml`: add `18776-5: {en: "Plan of care note", ja: "入院診療計画書"}`.
- `document_type_specs.yaml` new entry:

  ```yaml
  admission_care_plan:
    loinc_code: "18776-5"
    format_type: composition
    countries_supported: [jp]              # JP-only — first JP-only doc type in the registry
    encounter_types_supported: [inpatient, icu]   # rehab_inpatient uses 別紙２の２, excluded
    generation_frequency: admission_once
    composition_sections:
      - ward_and_room
      - other_staff
      - diagnosis
      - symptoms
      - treatment_plan
      - test_schedule
      - surgery_schedule
      - estimated_los
      - special_nutrition_management
      - other_plans
    stage2_strategy: template_only   # legally-mandated administrative form — no LLM (hallucination risk)
  ```

- `SUPPORTED_DOCUMENT_TYPES` (`narrative/registry.py`) += `DocumentType.ADMISSION_CARE_PLAN`.
- `document/engine.py` document_enricher: `admission_once` frequency dispatch already exists
  (shared with `admission_hp` / `admission_nursing_assessment`) — new spec entry is picked up
  automatically via the existing spec-driven loop, gated by `encounter_types_supported` +
  `countries_supported=[jp]` (no new engine branch).

### 3b. Fact extraction (`narrative/fact_extractor.py` + `section_extractor.py`)

All 10 sections source from **existing CIF fields** — no new CIF schema:

| section | source |
|---|---|
| `ward_and_room` | `Encounter.ward_id` + `Encounter.bed_number` |
| `other_staff` | `Encounter.primary_nurse_id` (same field AD-64 CareTeam uses for the nurse participant; renders "担当なし" if empty — no new name-resolution helper needed, mirrors how CareTeam references the id) |
| `diagnosis` | same extraction as `admission_hp.chief_complaint`/diagnosis facts (`ClinicalDiagnosis`) |
| `symptoms` | `chief_complaint` + HPI facts (existing) |
| `treatment_plan` | disease_protocol treatment description facts (existing extraction reused from assessment_and_plan-adjacent facts) |
| `test_schedule` | lab + imaging orders already in CIF (existing order list) |
| `surgery_schedule` | `ProcedureRecord` filtered by `category_code == "387713003"` (surgical); empty → render "予定なし" |
| `estimated_los` | `disease_protocol.target_los` (required field on every disease protocol per CLAUDE.md) |
| `special_nutrition_management` | **hardcoded "無"** (MVP decision — no NutritionOrder subsystem exists yet; TODO.md entry documents this as a known simplification pending the nutrition subsystem chain) |
| `other_plans` | reuse `admission_nursing_assessment.care_plan` section content (nursing + rehab plan summary) if the stub exists for this encounter, else a short generic placeholder |

### 3c. Template rendering (`narrative/template_generator.py`)

Add `admission_care_plan` section renderers mirroring the existing `admission_nursing_assessment`
style (short structured JP text per section, not prose — this is an administrative form, not
a narrative note). `stage2_strategy: template_only` means no LLM path is wired for this doc
type (consistent with `admission_nursing_assessment` / `nursing_shift_note`).

### 3d. FHIR output

**No changes.** `_fhir_composition.py` builds `Composition.section[]` generically from
`doc["narrative"]["sections"].items()` — verified 2026-07-03 (`passes.py` / `_fhir_composition.py:144-155`).
New doc type flows through automatically once Stage 1 stub + Stage 2 narrative exist.

## 4. Out of scope (explicit)

- 看護必要度D表 / 栄養管理計画書 / リハビリテーション計画書 — separate TODO.md entries,
  each needs a new prerequisite subsystem.
- 在宅復帰支援担当者名 / 在宅復帰支援計画 / 総合的な機能評価 (別紙２ ＊/◇ conditional fields).
- 療養病棟 (別紙２の２) variant — `rehab_inpatient` excluded from `encounter_types_supported`.
- Real nutrition-need derivation — `special_nutrition_management` stays hardcoded "無" until
  a nutrition subsystem chain lands (formal TODO.md entry to be added alongside this PR).
- JP section.title locale mapping (English snake_case keys in `Composition.section[].title`)
  — pre-existing deferred item (β-JP-1 phase, tracked separately), not this chain's scope.

## 5. Testing

- **Registry validation**: existing `registry.py` Layer 1-9 fail-loud checks apply
  automatically to the new spec entry (no new validation code needed).
- **Unit**: fact extraction for each of the 10 sections — surgical procedure present/absent,
  varying disease protocols (target_los rendering), empty primary_nurse_id fallback.
- **Integration**: full chain — `document_enricher` (Stage 1 stub) → `TemplateNarrativePass`
  (Stage 2) → FHIR export, for a JP inpatient + JP ICU encounter. Assert: `Composition`
  resource emitted with LOINC 18776-5, exactly 10 sections, 100% Japanese text (jp_language
  audit axis), zero emission for US cohorts and for outpatient/emergency/rehab_inpatient
  encounters (silent-no-op negative check).
- **audit `lift_firing_proof`**: add an equality_check — count of `admission_care_plan`
  documents == count of eligible JP inpatient+icu admissions in the cohort (PR-90 class
  silent-no-op defense, matches the pattern used by every prior doc-type addition).
- **Goldens (AD-66)**: regenerate the JP inpatient/ICU canonical profile goldens
  (`jp_inpatient_bacterial_pneumonia`, `jp_icu_sepsis_hai_clabsi`, `jp_inpatient_copd_exacerbation`)
  in the same commit as any generation-logic change; categorize + clinically review the diff
  per AD-66 Rule 2 before commit.

## 6. Verification gate

`clinosim audit run -d <JP cohort>` (4-axis) + goldens regen + the integration tests above.
This is a new-feature PR: byte-diff is intentionally broken for JP inpatient/ICU cohorts
(new document content). It MUST stay byte-identical for US output and for all pre-existing
JP document types, since this spec adds a new, isolated spec entry + fact-extraction/template
functions and touches no shared code path — verify with a byte-diff run before merge as a
regression check on that claim.
