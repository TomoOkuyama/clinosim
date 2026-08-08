# 栄養管理計画書 (Nutrition Care Plan Document) — Design Spec

**Date:** 2026-07-03 (session 33)
**Status:** Approved for implementation
**Branch:** `feature/chain2-nutrition-care-plan` (to be created)
**先行:** admission_care_plan (#138, merged) — second chain-2 (厚労省4帳票) sub-project.

## 1. Problem

`TODO.md` "β-JP-1 phase — JP localization + 厚労省必須文書" lists 4 MHLW-mandated
documents. 入院診療計画書 (admission care plan) is done (#138). Of the remaining 3
(看護必要度評価票 / 栄養管理計画書 / リハビリテーション計画書), LOINC tractability was
investigated for all three before choosing:

- **看護必要度評価票** ("看護必要度D表" in TODO.md — this wording is a misnomer; the
  official MHLW term is 「重症度、医療・看護必要度に係る評価票」with A/B/C 項目, not a
  "D表". No defensible LOINC document-type code exists (verified: LOINC 80346-0
  "Nursing physiologic assessment panel" is a generic US nursing physical exam
  panel, not equivalent — using it would misrepresent the document). This is a
  Japan-domestic DPC/reimbursement instrument with no international LOINC
  analog. Deferred (would need a local, non-LOINC code system + a new
  QuestionnaireResponse rendering path built from the current infrastructure
  stub — larger, architecturally novel scope).
- **栄養管理計画書** — **chosen**. LOINC **80791-7** "Nutrition and dietetics Plan
  of care note" is an excellent, specific match (verified via web search against
  loinc.org / findacode.com).
- **リハビリテーション計画書** — no rehab-specific "Plan of care note" LOINC code
  found (closest: 34823-5 "Physical medicine and rehab Note", not a plan-of-care
  variant); would reuse the generic 18776-5 already used by admission_care_plan.
  Also requires a new rehab `ProcedureRecord` subsystem. Deferred.

## 2. Authoritative source (verified, not fabricated)

- **LOINC 80791-7** = "Nutrition and dietetics Plan of care note" — verified via
  web search against loinc.org. `ja` display: "栄養管理計画書" (the JP clinical term
  for the document this code represents — same convention as 18776-5 → "入院診療計画書").
- **MHLW form 別紙23** (fetched via 日本栄養士会 mirror
  `https://www.dietitian.or.jp/assets/data/medical-fee/0000196315_292.pdf`,
  `pdftotext -layout` extracted 2026-07-03) — confirmed fields:

  | # | 別紙23 field (JP) | section key | MVP data source |
  |---|---|---|---|
  | 1 | 病棟／担当医師名／入院日 | `ward_and_physician` | `Encounter.ward_id` / `attending_physician_id` / `admission_datetime` (same fields as admission_care_plan) |
  | 2 | 担当管理栄養士名 | `dietitian` | no dietitian staff role exists — fixed fallback (mirrors admission_care_plan's `other_staff` "担当なし" pattern) |
  | 3 | 入院時栄養状態に関するリスク | `nutrition_risk` | **derived from `PatientProfile.bmi`**: BMI<18.5 → 低栄養リスク; 18.5-25 → リスク低; >25 → 過栄養傾向(standard, widely-used simplified screening threshold — not fabricated, but a coarse proxy, not a validated instrument like MUST/GLIM) |
  | 4 | 栄養状態の評価と課題 | `nutrition_assessment` | MVP fixed fallback |
  | 5 | 栄養管理計画 目標 | `nutrition_goals` | MVP fixed fallback |
  | 6 | 栄養補給に関する事項 (エネルギー/たんぱく質/補給方法/嚥下調整食/食事内容/留意事項) | `nutrition_supply` + `dysphagia_diet` + `dietary_content` | `nutrition_supply`: **derived from `PatientProfile.weight_kg`** via standard estimation formulas (25–30 kcal/kg/day energy, 1.0–1.2 g/kg/day protein — standard initial-planning rule-of-thumb, not a personalized dietitian assessment); route fixed to 経口 (oral) MVP default. `dysphagia_diet` + `dietary_content`: MVP fixed fallback |
  | 7 | 栄養食事相談に関する事項 (入院時指導/相談/退院時指導) | `nutrition_counseling` | MVP fixed fallback (collapses the 3 sub-items into one section for MVP — no per-item data source exists) |
  | 8 | その他栄養管理上解決すべき課題 | `other_issues` | MVP fixed fallback |
  | 9 | 栄養状態の再評価の時期 | `reassessment_timing` | MVP fixed fallback (e.g. "入院後1週間を目安に再評価") |
  | 10 | 退院時及び終了時の総合的評価 | `discharge_evaluation` | MVP fixed fallback — genuinely unknowable at plan-creation time (this document is created at/near admission per MHLW workflow; the discharge evaluation is filled in later in real practice, and this system has no revise-at-discharge mechanism for this doc type, mirroring the `other_plans` cross-doc-content constraint documented in the admission_care_plan design) |

  This MVP covers **12 composition sections** (`ward_and_physician` maps to 3
  MHLW header fields consolidated into 1 section, `nutrition_supply` +
  `dysphagia_diet` + `dietary_content` split the "栄養補給に関する事項" block into 3
  sections for clearer per-section data provenance). Of these, **3 are
  genuinely data-driven** (`ward_and_physician`, `nutrition_risk`,
  `nutrition_supply`); **9 are MVP fixed fallbacks** pending future subsystems
  (dietitian staff role, real nutrition assessment/counseling data, discharge
  revision mechanism). This is a lower real-data-coverage ratio than
  admission_care_plan — **an explicit, user-confirmed tradeoff** (see TODO.md
  deferred entries in §4), not a scope gap discovered after the fact.

## 3. Scope

### 3a. New dispatch condition: `admission_once_los_gt_7`

MHLW mandates this document for admissions **> 7 days**. No existing
`GENERATION_FREQUENCIES` value expresses a LOS-conditional admission-time
document (existing values: `admission_once`, `daily`, `daily_3shift`,
`discharge_once`, `encounter_once`). Unlike admission_care_plan (zero engine.py
changes), this chain requires **one new branch** in
`clinosim/modules/document/engine.py`'s `document_enricher` dispatch loop,
mirroring the existing `daily` branch's LOS-skip pattern:

```python
elif freq == "admission_once_los_gt_7":
    # MHLW mandate: nutrition care plan required only for admissions > 7 days.
    if los_days <= 7:
        continue
    documents.append(ClinicalDocument(
        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
        task_type=spec.type_key,
        loinc_code=spec.loinc_code,
        patient_id=pid,
        encounter_id=encounter_id,
        author_practitioner_id=_pick_document_author(spec, encounter),
        authored_datetime=admission_dt.isoformat(),
        period_start=admission_dt.isoformat(),
        period_end=admission_dt.isoformat(),
        language=lang,
        format_type=spec.format_type.value,
        narrative=None,
    ))
    doc_seq += 1
```

`GENERATION_FREQUENCIES` (registry.py) gains `"admission_once_los_gt_7"` — the
existing Layer 7 fail-loud validator already requires this (an unregistered
frequency value raises `ValueError` at YAML load, per the α-min-3 precedent).

### 3b. Registry additions

- `DocumentType.NUTRITION_CARE_PLAN = "nutrition_care_plan"` in `types/document.py`.
- `codes/data/loinc.yaml`: add `80791-7: {en: "Nutrition and dietetics Plan of care note", ja: "栄養管理計画書"}`.
- `document_type_specs.yaml` new entry:

  ```yaml
  nutrition_care_plan:
    loinc_code: "80791-7"
    format_type: composition
    countries_supported: [jp]
    encounter_types_supported: [inpatient, icu]
    generation_frequency: admission_once_los_gt_7
    composition_sections:
      - ward_and_physician
      - dietitian
      - nutrition_risk
      - nutrition_assessment
      - nutrition_goals
      - nutrition_supply
      - dysphagia_diet
      - dietary_content
      - nutrition_counseling
      - other_issues
      - reassessment_timing
      - discharge_evaluation
    stage2_strategy: template_only
  ```

- `SUPPORTED_DOCUMENT_TYPES` (`narrative/registry.py`) += `DocumentType.NUTRITION_CARE_PLAN`.
- `LLMTaskType`/`TASK_CATEGORY`/`DOCUMENT_LOINC` sync in `llm_service/engine.py`
  (mandatory per the N-3 import-time cross-validator — same requirement
  discovered during the admission_care_plan chain).

### 3c. Fact extraction / template rendering

All in `template_generator.py`, mirroring the `_build_acp_*` naming/structure
convention (`_build_ncp_*` prefix):

| section | source |
|---|---|
| `ward_and_physician` | `Encounter.ward_id` + `attending_physician_id` + `admission_datetime` (reuses the exact fields admission_care_plan's `ward_and_room`/`other_staff` already established) |
| `dietitian` | fixed fallback "担当なし" (no dietitian role) |
| `nutrition_risk` | `_o(ctx.patient, "bmi", None)` → 3-tier threshold (< 18.5 / 18.5–25 / > 25) |
| `nutrition_assessment` | fixed fallback |
| `nutrition_goals` | fixed fallback |
| `nutrition_supply` | `_o(ctx.patient, "weight_kg", None)` → `round(weight * 27.5)` kcal (midpoint of 25–30) + `round(weight * 1.1, 1)` g protein (midpoint of 1.0–1.2); route fixed "経口" |
| `dysphagia_diet` | fixed fallback "なし" |
| `dietary_content` | fixed fallback |
| `nutrition_counseling` | fixed fallback |
| `other_issues` | fixed fallback |
| `reassessment_timing` | fixed fallback ("入院後1週間を目安に再評価") |
| `discharge_evaluation` | fixed fallback ("退院時に評価予定") |

### 3d. FHIR output

**No changes** — `_fhir_composition.py` is generic (verified in the
admission_care_plan chain; unaffected by this addition).

## 4. Out of scope (explicit, formal TODO.md entries to add alongside this PR)

- Real dietitian staff role / CareTeam participant — `dietitian` section stays
  a fixed fallback until a dietitian role exists in the staff roster.
- Real nutrition assessment/goals/counseling content — no CIF data source;
  8 of 12 sections are MVP fixed fallbacks (see §2 table). Revisit when/if a
  richer nutrition-assessment data model is built.
- Discharge-time revision of this document (the `discharge_evaluation` field
  is only ever the fixed "pending" placeholder — this system has no mechanism
  to re-render a Stage-1 stub at a later encounter phase for this doc type).
- 看護必要度評価票 and リハビリテーション計画書 — remain deferred per §1's LOINC/scope
  findings, tracked as separate TODO.md entries.
- `nutrition_risk`'s BMI-threshold heuristic is a coarse screening proxy, not
  a validated malnutrition-assessment instrument (e.g. GLIM criteria, which
  MHLW's own guidance references) — acceptable for a synthetic-data MVP, but
  should not be read as clinically authoritative if this pattern is reused
  elsewhere.

## 5. Testing

Same structure as the admission_care_plan chain (registry validation / unit
builder tests / engine dispatch verification / audit `lift_firing_proof`
extension / full-chain integration test / golden regen), plus:

- **New**: `admission_once_los_gt_7` dispatch test — LOS=5 (no document
  emitted) and LOS=10 (document emitted) both at the engine-dispatch unit
  level AND in the audit `lift_firing_proof` gate (mirrors the admission_care_plan
  adv-1 lesson: prove BOTH the positive and negative dispatch cases, not just
  the positive one).
- `nutrition_risk` / `nutrition_supply` unit tests across a range of BMI/weight
  values spanning all 3 risk tiers and verifying the kcal/protein arithmetic.
- Golden regen: check which of the 3 canonical JP inpatient/ICU profiles have
  LOS > 7 days (only those will show a new `nutrition_care_plan` document in
  their golden diff — the others should show **zero** diff, which is itself a
  useful negative confirmation of the LOS gate).

## 6. Verification gate

Same as admission_care_plan: `clinosim audit run -d <JP cohort>` (4-axis) +
goldens regen (AD-66 Rule 2 categorize + clinical review) + integration tests.
New-feature PR — byte-diff intentionally broken for JP inpatient/ICU cohorts
with LOS > 7 (new content); must stay byte-identical for US output, JP
cohorts with LOS ≤ 7, and all pre-existing JP document types.
