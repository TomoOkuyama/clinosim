# リハビリテーション実施計画書 (Rehabilitation Plan Document) — Design Spec

**Date:** 2026-07-04 (session 36)
**Status:** Approved for implementation
**Branch:** `feature/chain2-rehabilitation-plan` (to be created)
**先行:** admission_care_plan (#138, merged) / nutrition_care_plan (#139, merged) — third
and final chain-2 (厚労省4帳票) sub-project.

## 1. Problem

`TODO.md` "β-JP-1 phase — JP localization + 厚労省必須文書" originally listed
リハビリテーション計画書 as blocked on a new `rehab_inpatient` ward-transfer subsystem
("mandatory for rehab wards. Requires `extensions["procedure"]` rehab sessions.").
Status-audit before implementation (per implementation-rules.md §0.3) found this framing
stale on two counts:

- **`EncounterType.REHAB_INPATIENT` and `EncounterType.ICU` are both aspirational
  scaffolds** — defined in the enum, referenced in duration tables and in downstream
  module allowlists (`document`, `nursing`), but **never actually assigned** anywhere in
  the simulator. `create_inpatient_encounter()` (`modules/encounter/engine.py:43`)
  hardcodes `EncounterType.INPATIENT`; `icu_transferred` is a boolean flag on that same
  INPATIENT encounter, not a distinct encounter. Verified empirically: a JP p=500 cohort
  generation produced zero `rehab_inpatient` / `icu` encounter_type values.
- **`RehabSession` already exists and already fires** — `clinosim/types/procedure.py` +
  `modules/procedure/engine.py:generate_rehab_sessions()` produce per-session PT records
  (`CIFPatientRecord.rehab_sessions`, a typed Base field, not `extensions["procedure"]`)
  whenever `disease_protocol.requires_surgery` is true (9 diseases: hip_fracture,
  acute_appendicitis, acute_cholecystitis, crush_injury_hand, fall_from_height,
  industrial_burn_severe, subdural_hematoma, traffic_accident_severe,
  wrist_fracture_surgical), inside the ordinary `inpatient` encounter
  (`simulator/inpatient.py:261`).

**Scope decision (user-confirmed):** build リハビリテーション計画書 against the
already-firing `RehabSession` data on `inpatient` encounters. Do NOT build the
`rehab_inpatient` ward-transfer subsystem — that remains a separate, much larger,
future TODO.md item if ever prioritized. `encounter_types_supported: [inpatient]` only
(no `icu` / `rehab_inpatient` — using either would itself be a new aspirational-scaffold
violation per implementation-rules.md §9.5, since neither value is ever produced).

## 2. Authoritative source (verified, not fabricated)

- **LOINC 34823-5** = "Physical medicine and rehab Note" (Fully-Specified Name:
  `Note:Find:Pt:{Setting}:Doc:Physical medicine and rehab`; Document Ontology scale
  `Doc`) — verified via loinc.org fetch 2026-07-04. This is a generic PM&R clinical-note
  code, broad enough (per its own LOINC group `LG38987-0`
  "ANYTypeOfService|ANYKindOfNote|ANYSetting") to represent a rehab plan document.
  **Rejected alternatives** (all checked against loinc.org, 2026-07-04):
  - `18776-5` "Plan of care note" — this is the code **already used by
    `admission_care_plan`**, mapped to `ja: "入院診療計画書"`. `_fhir_composition.py:99-137`
    resolves `Composition.type.coding[].display` / `.text` / `.title` via a single
    `code_lookup("loinc", loinc_code, lang)` call — one code has exactly one canonical
    display. Reusing 18776-5 here would make a rehab plan's `Composition.type` render as
    "入院診療計画書" in JP output, an AD-30-class code/display integrity violation. (The
    admission_care_plan design doc's §1 note that this document "would reuse the generic
    18776-5" was a plan that was never carried out and should not be — this spec
    supersedes that note.)
  - `84306-0` "Vocational rehabilitation Plan of care note" — confirmed via loinc.org
    fetch to be specific to **vocational** (return-to-work) rehabilitation, a distinct
    clinical domain from PT/OT/ST inpatient rehab. Not a match.
  - `92564-4` "Physical therapy plan of care panel" — a PANEL (Document Ontology axis
    `Panel`, order/observation grouping), not a `Doc`-type clinical document. Wrong axis
    for a `format_type: composition` document (same class of rejection as the
    看護必要度評価票 LOINC 80346-0 rejection in the nutrition_care_plan design doc — using
    a panel code to represent a narrative/composition document misrepresents it).
  - `ja` display: **"リハビリテーション実施計画書"** — the official MHLW form title (see
    below), following the established convention of giving a generic LOINC code a
    precise JP clinical-term display (cf. `18776-5` → `ja: "入院診療計画書"`).

- **MHLW form 別紙様式21** (`https://www.mhlw.go.jp/bunya/iryouhoken/iryouhoken15/dl/h24_02-07-32.pdf`,
  fetched + `pdftotext -layout` extracted 2026-07-04) — the base 疾患別リハビリテーション
  実施計画書 form (page 1 of 6; pages 2-6 are 別紙様式21の2〜21の5, diagnosis-specific
  variants — recovery-ward / cardiac-rehab / long-term-care specific forms, all excluded
  from this spec's scope, mirroring how admission_care_plan excluded the 別紙２の２
  variant). Confirmed field groups on the base form: header (patient/date/staff),
  原因疾患・合併疾患, 心身機能・構造 evaluation checklist, 基本動作, ADL table, 活動度,
  職業/社会参加, 目標(本人/家族の希望), 方針, リハビリテーション終了の目安・時期,
  本人・家族への説明(署名).

## 3. Scope

### 3a. `RehabSession` wiring into `NarrativeContext`

`NarrativeContext` (`types/document.py`) has no `rehab_sessions` field today. Add one,
mirroring the existing unfiltered `procedures` field exactly (verified in
`narrative/context.py:47` — `procedures` is passed through record-wide, with no
per-encounter filtering; every existing `_build_acp_*` procedure-consuming builder does
its own in-function filtering, e.g. `_build_acp_surgery_schedule` filters by
`category_code`). No new filtering infrastructure needed:

```python
# types/document.py NarrativeContext
rehab_sessions: list[Any] = field(default_factory=list)  # list[RehabSession]

# narrative/context.py build_narrative_context()
rehab_sessions=_o(record, "rehab_sessions", []) or [],
```

### 3b. New dispatch condition: `admission_once_if_rehab_sessions`

Gate: emit only if the patient record has at least one `RehabSession`. This is the
**third** conditional variant of the `admission_once` family (after plain `admission_once`
and `admission_once_los_gt_7`) — exactly the scenario the nutrition_care_plan chain's
final-review deferred TODO ("LOS-gated document_enricher pattern", PR #139) anticipated.
Per that TODO's own recommendation, extract the shared `ClinicalDocument(...)`
construction into a small local helper as part of landing this third branch (mechanical
DRY refactor, no behavior change to the two existing branches — verified by byte-diff):

```python
def _make_doc_stub(
    spec: Any, encounter_id: str, doc_seq: int, dt: datetime,
    pid: str, lang: str, author: str,
) -> ClinicalDocument:
    return ClinicalDocument(
        document_id=f"{DOC_REFERENCE_ID_PREFIX}{encounter_id}-{doc_seq:02d}",
        task_type=spec.type_key,
        loinc_code=spec.loinc_code,
        patient_id=pid,
        encounter_id=encounter_id,
        author_practitioner_id=author,
        authored_datetime=dt.isoformat(),
        period_start=dt.isoformat(),
        period_end=dt.isoformat(),
        language=lang,
        format_type=spec.format_type.value,
        narrative=None,
    )
```

`admission_once` and `admission_once_los_gt_7` both call this with `dt=admission_dt`
(behavior-preserving — confirm via byte-diff on existing goldens). New branch:

```python
elif freq == "admission_once_if_rehab_sessions":
    # MHLW 別紙様式21: rehabilitation plan required only when the patient is
    # actually receiving disease-specific rehab therapy (design spec §1 — this
    # reuses the existing RehabSession data rather than a rehab-ward transfer).
    enc_rehab_sessions = [
        s for s in (_o(record, "rehab_sessions", []) or [])
        if _o(s, "encounter_id", "") == encounter_id
    ]
    if not enc_rehab_sessions:
        continue
    first_session_dt = min(
        _o(s, "session_date", admission_dt) for s in enc_rehab_sessions
    )
    documents.append(_make_doc_stub(
        spec, encounter_id, doc_seq, first_session_dt, pid, lang,
        _pick_document_author(spec, encounter),
    ))
    doc_seq += 1
```

(Note: this branch filters by `encounter_id` — unlike the `NarrativeContext.rehab_sessions`
field in §3a which stays unfiltered per the existing `procedures` precedent. The dispatch
gate needs a real per-encounter boolean; the Stage-2 template builders operate on the
already-scoped `ctx` the same way `_build_acp_surgery_schedule` does today.)

`GENERATION_FREQUENCIES` (registry.py) gains `"admission_once_if_rehab_sessions"` (Layer 7
fail-loud validator requires this, per precedent).

### 3c. Registry additions

- `DocumentType.REHABILITATION_PLAN = "rehabilitation_plan"` in `clinosim/types/document.py`.
- `codes/data/loinc.yaml`: add `34823-5: {en: "Physical medicine and rehab Note", ja: "リハビリテーション実施計画書"}`.
- `document_type_specs.yaml` new entry:

  ```yaml
  rehabilitation_plan:
    loinc_code: "34823-5"
    format_type: composition
    countries_supported: [jp]
    encounter_types_supported: [inpatient]   # icu / rehab_inpatient never fire (design spec §1)
    generation_frequency: admission_once_if_rehab_sessions
    composition_sections:
      - patient_and_diagnosis
      - rehab_team
      - functional_status
      - basic_movement
      - session_frequency
      - goals
      - policy
      - discharge_estimate
      - explanation_consent
    stage2_strategy: template_only
    llm_enabled_sections: []
  ```

- `SUPPORTED_DOCUMENT_TYPES` (`narrative/registry.py`) += `DocumentType.REHABILITATION_PLAN`.
- `LLMTaskType`/`TASK_CATEGORY`/`DOCUMENT_LOINC` sync in `llm_service/engine.py` (N-3
  import-time cross-validator, same requirement as both prior chain-2 docs).

### 3d. `stage2_strategy` decision: `template_only` (no LLM)

Same reasoning as `admission_care_plan` / `nutrition_care_plan`: this is a legally-mandated
reimbursement-linked MHLW form (hallucination risk unacceptable), **and** the two sections
that read as narrative-shaped (`goals`, `policy`) have **zero backing CIF data** — no field
represents a patient/family's stated rehab goals. Unlike `admission_hp.hpi` (grounded in
real disease_protocol/symptom facts), an LLM asked to fill `goals`/`policy` here would
fabricate entirely, which is worse for a legally-binding form than a plain fixed-fallback
phrase. `goals`/`policy` stay MVP fixed fallbacks; §5 records a TODO.md entry to revisit
if/when a patient-goals data model exists.

### 3e. Fact extraction / template rendering (`template_generator.py`, `_build_rp_*` prefix)

| section | source | driven? |
|---|---|---|
| `patient_and_diagnosis` | reuses `_build_acp_diagnosis` (same `ctx.diagnoses` extraction as admission_care_plan) | data |
| `rehab_team` | distinct `therapy_type` values across `ctx.rehab_sessions` (currently always `{"PT"}` — `generate_rehab_sessions` hardcodes `therapy_type="PT"`, OT/ST are unpopulated in `RehabSession` today; render "理学療法(PT)" honestly, not multi-disciplinary text that doesn't match the data); named therapist = fixed fallback "担当者未定" (no therapist staff role exists, mirrors `nutrition_care_plan.dietitian`) | partial |
| `functional_status` | latest (by `session_date`) session's `functional_progress` + `patient_participation` + `pain_score`, each mapped through a small closed-enum JP-phrase dict (mirrors `_localize_display()` convention for enum values — do NOT render `RehabSession.activities` raw strings; those are pre-existing English free text with no JP mapping and rendering them would violate JP-purity, see §5) | data |
| `basic_movement` | latest session's `day_post_op` re-derived into phase (`<=3` early / `<=14` mid / else late — same thresholds `generate_rehab_sessions` uses internally, not stored on `RehabSession` so recomputed here) → fixed JP phrase per phase | data (derived tier) |
| `session_frequency` | `len(ctx.rehab_sessions)`, first/last `session_date`, `duration_minutes` (mode or first value — sessions carry a single fixed duration per country) | data |
| `goals` | fixed fallback (no CIF source — §3d) | fixed |
| `policy` | fixed fallback (no CIF source — §3d) | fixed |
| `discharge_estimate` | extract shared `_estimated_los_days(ctx) -> tuple[int, list[str]]` helper out of `_build_acp_estimated_los` (2nd consumer — canonical single-source per implementation-rules.md §4); render as "リハビリテーション終了の目安：入院後約{N}日" rather than admission_care_plan's LOS phrasing | data |
| `explanation_consent` | fixed fallback signature-block phrase (mirrors `admission_care_plan`/`nutrition_care_plan` pattern) | fixed |

6 of 9 sections are data-driven (higher ratio than both prior chain-2 docs).

### 3f. FHIR output

**No changes** — `_fhir_composition.py` is generic (re-verified for this chain; unaffected).

## 4. Out of scope (explicit, formal TODO.md entries to add alongside this PR)

- **`rehab_inpatient` / `EncounterType.ICU` ward-transfer subsystem** — remains
  unimplemented; this chain deliberately does not build it (§1). If ever prioritized, it
  is a new simulator-level feature (transfer trigger in `inpatient.py` or
  `encounter/engine.py` + disease YAML trigger conditions), not a document-module change.
- **OT/ST therapy types** — `generate_rehab_sessions` (`modules/procedure/engine.py`)
  hardcodes `therapy_type="PT"`; `rehab_team` will only ever show PT until that module
  (out of scope here — procedure module, not document module) is extended.
- **Real patient/family rehab goals data source** — `goals`/`policy` stay fixed fallbacks;
  no CIF field represents patient-stated preferences. Revisit `stage2_strategy` for these
  two sections only if such a data model is ever built.
- **Named rehab therapist / staff role** — `rehab_team`'s named-therapist field stays a
  fixed fallback until a PT/OT/ST staff role exists in the roster (same class of gap as
  `nutrition_care_plan.dietitian`).
- **`RehabSession.activities` free-text localization** — the field holds hardcoded English
  phrases (e.g. "bed exercises") with no JP mapping; this document does not render them
  (uses the derived phase-tier instead). If a future consumer needs the raw activity list
  in JP output, add a proper activity-key → {en, ja} lookup table then (do not hardcode
  ad hoc translations at that call site).

## 5. Testing

Same structure as `admission_care_plan` / `nutrition_care_plan`:

- **Registry validation**: existing Layer 1-9 fail-loud checks apply automatically.
- **Unit**: each `_build_rp_*` section builder — with 1 session, with many sessions
  (frequency/date-range aggregation), with zero sessions (should never be called in
  practice since the dispatch gate requires ≥1, but the shared `_estimated_los_days`
  extraction must not regress `_build_acp_estimated_los`'s existing behavior — add a
  regression unit test pinning admission_care_plan's exact output pre/post refactor).
- **New**: `admission_once_if_rehab_sessions` dispatch test — encounter with
  `requires_surgery=false` disease (no document emitted) and encounter with
  `requires_surgery=true` disease (document emitted), both at the engine-dispatch unit
  level AND in the audit `lift_firing_proof` gate (mirrors the nutrition_care_plan adv-1
  lesson: prove both the positive and negative dispatch cases).
- **`_make_doc_stub` refactor regression**: byte-diff the two existing branches
  (`admission_once`, `admission_once_los_gt_7`) before/after the extraction — must be
  byte-identical (pure mechanical refactor).
- **Integration**: full chain — `document_enricher` → `TemplateNarrativePass` → FHIR
  export for a JP inpatient encounter with `hip_fracture` (requires_surgery=true).
  Assert: `Composition` with LOINC 34823-5, exactly 9 sections, 100% Japanese text
  (jp_language audit axis), zero emission for non-surgical diseases, US cohorts, and
  outpatient/emergency encounters (silent-no-op negative check).
- **audit `lift_firing_proof`**: equality_check — count of `rehabilitation_plan` documents
  == count of JP inpatient encounters with ≥1 `RehabSession` in the cohort.
- **Goldens (AD-66)**: regenerate any of the 6 canonical profiles that hit a
  `requires_surgery=true` disease (check which ones do first — only those show a new
  `rehabilitation_plan` document in their diff; others should show **zero** diff, itself a
  useful negative confirmation of the gate).

## 6. Verification gate

`clinosim audit run -d <JP cohort with ≥1 requires_surgery=true disease>` (4-axis) +
goldens regen (AD-66 Rule 2 categorize + clinical review) + integration tests above.
New-feature PR: byte-diff intentionally broken only for JP inpatient encounters with
`RehabSession` records; must stay byte-identical for US output, JP encounters without
rehab sessions, and all pre-existing JP document types (including
`admission_care_plan`'s `estimated_los` section post-`_estimated_los_days`-extraction —
explicit regression check per §5).
