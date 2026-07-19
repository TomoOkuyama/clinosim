"""Composition FHIR R4 builder (Tier 1 #3 α-min-1 Task 9, extended α-min-2 Task 12,
refactored to two-layer CIF in AD-65 Task 4).

Reads CIF record.documents where format_type='composition'. Emits one
Composition resource per matching ClinicalDocument. Section structure is
derived from doc["narrative"]["sections"] (dict[section_title, section_text])
— the flat ClinicalDocument.sections field was removed in AD-65 Task 1; the
narrative subtree is merged in by CIFReader (Task 4) before builders run.
A stub whose narrative is still None (Stage 2 narrative pass hasn't run for
this doc yet) is skipped with a warning rather than emitting an empty
Composition.

α-min-1 COMPOSITION doc types (Task 9):
  ADMISSION_HP (LOINC 34117-2), DISCHARGE_SUMMARY (LOINC 18842-5)

α-min-2 COMPOSITION doc types (Task 12 — automatically dispatched via format_type
string match; no engine code changes required):
  ADMISSION_NURSING_ASSESSMENT (LOINC 78390-2)
  NURSING_DISCHARGE_SUMMARY    (LOINC 34745-0)
  OUTPATIENT_SOAP              (LOINC 34131-3)
  ED_NOTE                      (LOINC 34878-9)

Section rendering (doc["narrative"]["sections"] dict → Composition.section[])
is otherwise unchanged; TemplateNarrativeGenerator (Task 6 α-min-1 + Task 8
α-min-2, invoked by TemplateNarrativePass Task 3) is the source of sections
dict content.

JP section.title locale mapping is deferred to β-JP-1 per α-min-1 adv-1 Lens 3
I-3 TODO (section titles remain as English snake_case keys).

No-drop invariant (CIF → FHIR):
  document_id         -> Composition.id (comp- prefix)
  loinc_code          -> Composition.type.coding[LOINC]
  encounter_id        -> Composition.encounter
  patient_id          -> Composition.subject
  author_practitioner_id -> Composition.author[]
  authored_datetime   -> Composition.date
  language            -> Composition.language
  narrative.sections  -> Composition.section[*] (title + text.div)

Canonical constant ownership:
- COMPOSITION_ID_PREFIX: clinosim.modules.document (writer-owner), imported here.
"""

from __future__ import annotations

import logging
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import resolve_lang
from clinosim.modules.document import COMPOSITION_ID_PREFIX, DOC_REFERENCE_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext, _escape_html

logger = logging.getLogger(__name__)

__all__ = [
    "COMPOSITION_ID_PREFIX",
    "_bb_compositions",
]

# session 59 #278:enc → free-text-doc-id 優先度用 LOINC 定数。
# module-scope(function 内では N806 lint violation)。
_HOSPITAL_COURSE_LOINC = "8648-8"
_PROGRESS_NOTE_LOINC = "11506-3"


# C2-27 (session 42 cycle 2): map section titles (as produced by document
# enrichers / narrative pass) to LOINC section codes. Codes verified via the
# LOINC search (loinc.org), matching HL7 recommendations for CCD document
# sections. Titles not listed here remain title-only until either the enricher
# starts emitting a canonical title or the code is verified.
_SECTION_LOINC: dict[str, str] = {
    # SOAP outpatient / progress notes
    "subjective": "10164-2",  # History of Present illness (subj narrative)
    "objective": "8716-3",  # Vital signs (objective) — narrower approx
    "assessment": "51848-0",  # Evaluation note (assessment)
    "plan": "18776-5",  # Plan of care note
    # Admission H&P / progress
    "chief_complaint": "10154-3",  # Chief complaint
    "hpi": "10164-2",  # History of present illness
    "past_medical_history": "11348-0",  # History of past illness
    "medications_at_home": "10160-0",  # History of medication use
    "physical_exam": "29545-1",  # Physical findings
    "triage_details": "56816-2",  # Vital signs assessment (triage)
    # Discharge summary
    "admission_summary": "10154-3",  # (reused, admission complaint)
    "hospital_course": "8648-8",  # Hospital course
    "discharge_diagnoses": "11535-2",  # Hospital discharge diagnosis
    "discharge_medications": "10183-2",  # Hospital discharge medications
    # Nursing sections
    "nursing_history": "34117-2",  # History and physical (H&P)
    # Session 58 Chain #10: 45391-8 is unknown in the fhir-jp-validator's LOINC
    # 2.82 cache (148 v4 errors). Substitute with the plan-of-care catch-all
    # (18776-5) that clinosim already emits successfully across many section
    # keys — ADL / functional / basic-movement notes fit under the rehab plan
    # of care semantically.
    "adl_assessment": "18776-5",  # Plan of care note (was 45391-8, unknown in LOINC 2.82)
    "risk_assessments": "75326-9",  # Assessment plan
    "nursing_diagnosis": "51848-0",  # Evaluation note (approx)
    "admission_status": "8648-8",  # Hospital course
    "nursing_interventions_provided": "10184-0",  # Interventions
    # Session 58 Chain #10: 42346-6 is unknown in the fhir-jp-validator's
    # LOINC 2.82 cache (135 v4 errors). Substitute with 18776-5 (Plan of care
    # note) — patient education / consent is part of the plan-of-care family
    # in CCDA.
    "patient_education": "18776-5",  # Plan of care note (was 42346-6)
    "discharge_readiness": "8650-4",  # Hospital discharge readiness
    # Ward-info & plan sections
    "ward_and_room": "42349-1",  # Reason for visit (approx)
    "other_staff": "51897-7",  # Care team member
    "diagnosis": "29308-4",  # Diagnosis
    "symptoms": "10187-3",  # Review of systems (approx)
    "ward_and_physician": "42349-1",  # Reason for visit
    "dietitian": "51897-7",  # Care team member
    "nutrition_risk": "61144-2",  # Diet and nutrition Narrative (C4-04 cycle 4: 9279-1 was Respiratory rate — wrong LOINC)  # noqa: E501
    "nutrition_assessment": "61144-2",  # (same)
    # Rehab
    "patient_and_diagnosis": "29308-4",  # Diagnosis
    "rehab_team": "51897-7",  # Care team member
    "functional_status": "18776-5",  # Plan of care note (was 45391-8, unknown)
    "basic_movement": "18776-5",  # (same)
    # CY2-C (session 42 cycle 3): residual auto-derived section titles that
    # appeared in cycle 2's 8% uncoded remainder. Codes verified via LOINC
    # search.
    "ed_workup": "51852-2",  # Workup panel (ED assessment)
    "disposition": "68609-7",  # Discharge disposition (ED disposition)
    "allergies": "48765-2",  # Allergies and adverse reactions
    "social_history": "29762-2",  # Social history
    "family_history": "10157-6",  # History of family member disease
    "physical_examination": "29545-1",  # Physical findings (reuse of physical_exam)
    "assessment_and_plan": "51847-2",  # Assessment and plan note
    "care_plan": "18776-5",  # Plan of care note (reuse of plan)
    "treatment_plan": "18776-5",  # (reused)
    "test_schedule": "18776-5",  # (falls under plan)
    "surgery_schedule": "18776-5",  # (falls under plan)
    "estimated_los": "8648-8",  # Hospital course (LOS estimate)
    "special_nutrition_management": "61144-2",  # Diet and nutrition Narrative
    "other_plans": "18776-5",  # Plan of care (catch-all)
    "discharge_instructions": "8653-8",  # Hospital discharge instructions
    "follow_up": "18776-5",  # Plan of care (follow-up)
    "nutrition_goals": "61144-2",  # Diet nutrition goals
    "nutrition_supply": "61144-2",  # (same)
    "dysphagia_diet": "61144-2",  # (same)
    "dietary_content": "61144-2",  # (same)
    # C4-19 (session 43 cycle 4): residual unmapped titles from cycle 4
    # baseline (546 sections in JP p=10000). Bind to the closest LOINC where
    # the CCDA / narrative theme corresponds; uncertain titles fall back to
    # a plan-of-care catch-all (18776-5) matching how care_plan / follow_up
    # already map above.
    "nutrition_counseling": "61144-2",  # Diet and nutrition Narrative
    "other_issues": "51852-2",  # Provider unspecified Progress note (catch-all narrative)
    "reassessment_timing": "18776-5",  # Plan of care (schedule)
    "discharge_evaluation": "8650-4",  # Hospital discharge readiness
    "session_frequency": "18776-5",  # Plan of care
    "goals": "18776-5",  # Plan of care (goals section of care plan)
    "policy": "18776-5",  # Plan of care (policy = clinical plan)
    "discharge_estimate": "8648-8",  # Hospital course (estimated LOS/discharge)
    "explanation_consent": "18776-5",  # Plan of care (was 42346-6, unknown)
}


def _bb_compositions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one Composition per ClinicalDocument with format_type='composition'.

    Skips (with a warning) any stub whose narrative subtree is still None —
    i.e. the Stage 2 narrative pass has not (yet) generated content for this
    document_id. This is expected for documents produced between `generate`
    and `narrate` runs, not a data-quality defect.

    session 59 #278:pre-compute encounter_id → free-text DocumentReference
    id map so JP-CLINS eDS `hospitalCourseSection.entry` slice can point
    at a real per-encounter DocumentReference (e.g. progress note 11506-3
    from the same admission). Prefer LOINC 8648-8(Hospital course)/
    11506-3(Progress note)を優先、その他 free-text は fallback。
    """
    raw_docs = _o(ctx.record, "documents", []) or []
    lang = resolve_lang(ctx.country)

    # First pass: encounter_id → primary free-text doc id.
    # Priority: 8648-8 (Hospital course) > 11506-3 (Progress note) > any
    # other free-text doc from the same encounter (last-wins fallback).
    # LOINC constants live at module scope (`_HOSPITAL_COURSE_LOINC` /
    # `_PROGRESS_NOTE_LOINC`) — moved out of function body to satisfy
    # N806 (session 59 #278 lint fix).
    enc_to_free_text: dict[str, str] = {}
    for doc in raw_docs:
        if _o(doc, "format_type", "") != "free_text":
            continue
        enc = _o(doc, "encounter_id", "") or ""
        doc_id = _o(doc, "document_id", "") or ""
        if not enc or not doc_id:
            continue
        loinc = _o(doc, "loinc_code", "") or ""
        current = enc_to_free_text.get(enc, "")
        # Prefer 8648-8 > 11506-3 > any; last-wins otherwise.
        if not current:
            enc_to_free_text[enc] = doc_id
        elif loinc == _HOSPITAL_COURSE_LOINC:
            enc_to_free_text[enc] = doc_id
        # Only overwrite with 11506-3 if current is not already the higher-priority code.
        elif loinc == _PROGRESS_NOTE_LOINC:
            # Check if current is already 8648-8; look up its LOINC by matching doc_id
            # in raw_docs. Cheap since we've already iterated once — small N per patient.
            current_loinc = ""
            for d2 in raw_docs:
                if _o(d2, "document_id", "") == current:
                    current_loinc = _o(d2, "loinc_code", "") or ""
                    break
            if current_loinc != _HOSPITAL_COURSE_LOINC:
                enc_to_free_text[enc] = doc_id

    out: list[dict[str, Any]] = []
    for doc in raw_docs:
        if _o(doc, "format_type", "") != "composition":
            continue
        narrative = _o(doc, "narrative", None)
        if not narrative:
            logger.warning(
                "composition stub %s has no narrative (Stage 2 pass not run for this document) — skipping",
                _o(doc, "document_id", ""),
            )
            continue
        sections = _o(narrative, "sections", {}) or {}
        out.append(_build_composition(doc, sections, lang, enc_to_free_text))
    return out


def _build_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    enc_to_free_text: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build one FHIR R4 Composition resource from a ClinicalDocument + its sections.

    P2-13 PR2a: dispatches to the JP-CLINS-conformant builder when
    ``lang == "ja"`` and the LOINC code is 18842-5 (discharge summary).
    PR2b (session 47): 57133-1 (referral note) dispatches to the eReferral
    builder. Otherwise the existing generic builder is used (US path
    unchanged).
    """
    if lang == "ja":
        loinc = _o(doc, "loinc_code", "")
        if loinc == "18842-5":
            return _build_jp_clins_discharge_summary_composition(doc, sections, lang, enc_to_free_text or {})
        if loinc == "57133-1":
            return _build_jp_clins_referral_note_composition(doc, sections, lang)
        # P2-13 PR3(session 47):JP-eCheckup General
        if loinc == "53576-5":
            return _build_jp_eCheckup_general_composition(doc, sections, lang)
    return _build_composition_generic(doc, sections, lang)


def _build_composition_generic(doc: Any, sections: dict[str, str], lang: str) -> dict[str, Any]:
    """Locale-neutral Composition builder — used by non-JP-CLINS paths.

    ``sections`` is the already-resolved ``doc["narrative"]["sections"]`` dict
    (extracted by ``_bb_compositions`` so this function stays narrative-shape
    agnostic and testable in isolation).
    """
    loinc_code = _o(doc, "loinc_code", "")
    loinc_display = code_lookup("loinc", loinc_code, lang) if loinc_code else ""

    doc_id = _o(doc, "document_id", "")
    author_id = _o(doc, "author_practitioner_id", "")
    # FHIR R4 Composition.date 1..1 dateTime; empty string is invalid.
    # Sentinel "2000-01-01T00:00:00" matches engine.py:172 admission_dt fallback
    # so FHIR consumers see the same epoch value as the encounter.
    authored_dt = _o(doc, "authored_datetime", "") or "2000-01-01T00:00:00"
    patient_id = _o(doc, "patient_id", "")
    encounter_id = _o(doc, "encounter_id", "")
    language = _o(doc, "language", "en")

    # Strip DOC_REFERENCE_ID_PREFIX ("doc-") before prepending COMPOSITION_ID_PREFIX
    # ("comp-") so production ids ("doc-{enc}-{seq}") become "comp-{enc}-{seq}" instead
    # of "comp-doc-{enc}-{seq}" (double-prefix defect, I-3 fix).
    enc_part = doc_id[len(DOC_REFERENCE_ID_PREFIX) :] if doc_id.startswith(DOC_REFERENCE_ID_PREFIX) else doc_id
    comp_id = f"{COMPOSITION_ID_PREFIX}{enc_part}"
    # C2-34 (session 42 cycle 2): Composition.identifier (0..1) for cross-system
    # document tracking. Session 58 Chain #10 (v4 §Composition.identifier URI):
    # JP-CLINS eDS / eReferral profiles fix `Composition.identifier.system`
    # to `http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier`
    # (StructureDefinition-JP-Composition-{eDS,eReferral}.json). US / generic
    # output keeps the clinosim namespace URI (no profile constraint). The
    # decision follows the caller's `lang` — JP-CLINS builders pass "ja",
    # generic / US pass "en".
    identifier_system = _JP_COMPOSITION_IDENTIFIER_SYSTEM if lang == "ja" else "urn:clinosim:composition-id"
    res: dict[str, Any] = {
        "resourceType": "Composition",
        "id": comp_id,
        "identifier": {
            "system": identifier_system,
            "value": comp_id,
        },
        "status": "final",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": loinc_display or loinc_code,
                }
            ],
            "text": loinc_display or loinc_code,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": authored_dt,
        # FHIR R4 Composition.author cardinality 1..*; empty [] is non-conformant.
        # Production fallback: inpatient.py:184 sets attending_id=DR-001 so this
        # branch should never fire in production. Placeholder surfaces failures via
        # reference integrity audit (dangling Practitioner/UNKNOWN) rather than
        # silently emitting [] (non-conformant) or hiding the bug.
        # TODO(Task 10/15): document enricher must always populate author_practitioner_id.
        "author": [{"reference": f"Practitioner/{author_id}"}]
        if author_id
        else [{"reference": "Practitioner/UNKNOWN"}],  # noqa: E501
        "title": loinc_display or loinc_code,
        # C5-27 (session 43 cycle 5): Composition.confidentiality (0..1 code)
        # per HL7 CDA / FHIR ConfidentialityCode. `N` = Normal (default JP
        # 医療情報 practice). All clinical documents are Normal unless
        # explicit privacy tag is set.
        "confidentiality": "N",
        "language": language,
    }

    if encounter_id:
        res["encounter"] = {"reference": f"Encounter/{encounter_id}"}
        # CY7-11 (Chain-7): Composition.event — the clinical event(s) the
        # composition documents. For discharge summary / progress note /
        # H&P etc., this is the encounter the doc summarizes, with the
        # encounter period.
        _period_start = _o(doc, "period_start", "") or authored_dt
        _period_end = _o(doc, "period_end", "") or ""
        _event: dict[str, Any] = {"period": {}}
        if _period_start:
            _event["period"]["start"] = _period_start
        if _period_end:
            _event["period"]["end"] = _period_end
        _event["detail"] = [{"reference": f"Encounter/{encounter_id}"}]
        if _event["period"]:
            res["event"] = [_event]

    # CY7-12 (Chain-7): Composition.custodian — managing hospital.
    res["custodian"] = {"reference": "Organization/hospital-main"}

    # C3-02 (session 42 cycle 3): Composition.attester — JP EHR legal
    # signature (電子署名). Attester = the document author (attending
    # physician) with mode=legal. FHIR R4 Composition.attester is 0..*;
    # populate when author_practitioner_id is known.
    if author_id and author_id != "UNKNOWN":
        res["attester"] = [
            {
                "mode": "legal",
                "time": authored_dt,
                "party": {"reference": f"Practitioner/{author_id}"},
            }
        ]

    # Build section[] from doc["narrative"]["sections"] (passed in as `sections`)
    # C2-27 (session 42 cycle 2): resolve LOINC section codes from the
    # canonical mapping. Sections with a known LOINC code get `section.code`
    # populated for interop; unknown titles retain title-only (documented
    # deferral).
    section_entries: list[dict[str, Any]] = []
    for section_title, section_text in sections.items():
        entry: dict[str, Any] = {
            "title": section_title,
            "text": {
                "status": "generated",
                "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{_escape_html(section_text)}</div>",
            },
        }
        loinc_section = _SECTION_LOINC.get(section_title)
        if loinc_section:
            lang = _o(doc, "language", "en")
            entry["code"] = {
                "coding": [
                    {
                        "system": get_system_uri("loinc"),
                        "code": loinc_section,
                        "display": code_lookup("loinc", loinc_section, lang) or section_title,
                    }
                ]
            }
        section_entries.append(entry)
    if section_entries:
        res["section"] = section_entries

    return res


# ============================================================
# P2-13 PR2a:JP-CLINS 退院時サマリー用 Composition builder
# ============================================================

_JP_CLINS_DS_PROFILE = "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
_JPFHIR_DOC_TYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"

# Session 58 Chain #10: JP-CLINS eDS / eReferral pin
# `Composition.identifier.system` to this URI (spec `fixedUri`, verified via
# `clinical-information-sharing#1.12.0/package/StructureDefinition-JP-Composition-
# {eDischargeSummary,eReferral}.json`). Same URI as session 57 identifier
# slices on Observation / Condition / AI / MR.
_JP_COMPOSITION_IDENTIFIER_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"

# Session 58 Chain #9: JP-CLINS eDS Composition required elements.
# Extension URL for `Composition.extension:version` (spec `fixedUri` on the
# slice discriminator). Verified via `clinical-information-sharing#1.12.0/
# package/StructureDefinition-JP-Composition-eDischargeSummary.json`.
_JP_EDS_VERSION_EXTENSION_URL = "http://hl7.org/fhir/StructureDefinition/composition-clinicaldocument-versionNumber"
# `Composition.category.coding` fixed system + fixed code per spec.
# doc-subtypecodes CS authoritative display (spec:
# `clinical-information-sharing#1.12.0/package/CodeSystem-jp-codeSystem-
# documentSubTypeCode.json`) → DISCHARGE = "退院時文書"。旧値 "退院時サマリー"
# は jpfhir-doc-typecodes CS(下記 `_JP_EDS_TYPE_DISPLAY_JA`)の display で
# あり、doc-subtypecodes CS とは別軸。session 58 Chain #9 (#267) で 1 定数を
# 兼用したため drift、v5 validation で 126+126 errors として顕在化(#279)。
_JPFHIR_DOC_SUBTYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-subtypecodes"
_JP_EDS_CATEGORY_CODE = "DISCHARGE"
_JP_EDS_CATEGORY_DISPLAY_JA = "退院時文書"
# jpfhir-doc-typecodes CS 18842-5 の JP display(`code_lookup` fallback +
# `Composition.title` に流用)。code_lookup が YAML から取得できる限り使わ
# れないが、YAML 破損時の safety net。
_JP_EDS_TYPE_DISPLAY_JA = "退院時サマリー"
# Section title-vs-display split (also used by Chain #8's eDS/eReferral
# builders; consolidated here for module scope).
_JP_SECTION_TITLE_SUFFIX = "セクション"


def _section_title_from_section_display(display: str) -> str:
    """Return the JP-CLINS `section.title` form for a section display —
    strip trailing `セクション` (spec `title.fixedString` / `patternString`
    is the short form; `code.coding.display.patternString` is long).
    Non-JP inputs pass through unchanged.
    """
    if isinstance(display, str) and display.endswith(_JP_SECTION_TITLE_SUFFIX):
        return display[: -len(_JP_SECTION_TITLE_SUFFIX)]
    return display


# session 53 iris4h-ai feedback D:JP-CLINS 実 canonical URL は
# `.../CodeSystem/document-section`(resource id `jp-codeSystem-clins-
# document-section` を path に含めない)。iris4h-ai の
# clinical-information-sharing#1.12.0/package/
# CodeSystem-jp-codeSystem-clins-document-section.json `.url` fixedUri
# を直接引用(session 51 rule)。従来の id-in-URL 版は HAPI で 1272 warn。
_JPFHIR_DOC_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"

# JP-CLINS 退院時サマリー section キー → jpfhir-doc-section 番号 code.
# Session 58 Chain #9: expanded from 5 admission-side to 10 required slices
# (5 admission + 5 discharge) so `Composition.section:structuredSection.section`
# min=10 is satisfied AND every required child slice (hospitalCourseSection,
# detailsOnDischargeSection, diagnosesOnDischargeSection,
# medicationOnDischargeSection, instructionOnDischargeSection) is present.
#
# Section-key names are the narrative-sections dict keys that
# `TemplateNarrativeGenerator` (Task 6 α-min-1 / Task 8 α-min-2) emits into
# `doc["narrative"]["sections"]`. When a discharge section key is absent
# on a specific ClinicalDocument (older narrative pass version), the builder
# emits the slice with an empty div — the slice is present with min=1 which
# is what the spec requires; per-slice `text` content is optional.
_JP_DS_SECTION_CODE: dict[str, str] = {
    # Admission side (5 slices — spec `patternString` for title)
    "admission_reason": "312",  # reasonForAdmissionSection / 入院理由
    "admission_details": "322",  # detailsOnAdmissionSection / 入院時詳細
    "admission_diagnoses": "342",  # diagnosesOnAdmissionSection / 入院時診断
    "chief_complaint": "352",  # chiefComplaintsSection / 主訴
    "present_illness": "360",  # presentIllnessSection / 現病歴
    # Discharge side (5 slices — session 58 Chain #9 additions)
    "hospital_course": "333",  # hospitalCourseSection / 入院中経過
    "discharge_details": "324",  # detailsOnDischargeSection / 退院時詳細
    "discharge_diagnoses": "344",  # diagnosesOnDischargeSection / 退院時診断
    "medication_on_discharge": "444",  # medicationOnDischargeSection / 退院時投薬指示
    "instruction_on_discharge": "424",  # instructionOnDischargeSection / 退院時方針指示
}


# Session 58 Chain #9 follow-up (#267): section slices with a required `entry`
# reference. Values are `("resource_type", "id_template")`; the template
# receives `encounter_id` and `doc_id` (comp-prefixed) as keyword args and
# returns the reference string. The reference targets track the JP-CLINS spec
# `type.targetProfile` on each `.entry` element (verified against
# `clinical-information-sharing#1.12.0/package/StructureDefinition-JP-
# Composition-eDischargeSummary.json`).
_JP_DS_SECTION_ENTRY_REFERENCES: dict[str, tuple[str, str]] = {
    # detailsOnAdmissionSection.entry min=1 max=1 → JP_Encounter
    "admission_details": ("Encounter", "Encounter/{encounter_id}"),
    # detailsOnDischargeSection.entry min=1 max=1 → JP_Encounter
    "discharge_details": ("Encounter", "Encounter/{encounter_id}"),
    # diagnosesOnDischargeSection.entry min=1 → JP_Condition (primary dx)
    "discharge_diagnoses": ("Condition", "Condition/cond-{encounter_id}-primary"),
    # session 59 #278:hospitalCourseSection.entry min=1 → JP_DocumentReference
    # 同一 encounter の progress note(LOINC 11506-3)or hospital course
    # note(LOINC 8648-8)などの free-text DocumentReference id を precompute
    # で解決。id は `_bb_compositions` が構築する enc_to_free_text map から
    # `{free_text_doc_id}` として供給。map hit しない場合は never-fabricate
    # rule に従い entry を emit しない。
    "hospital_course": ("DocumentReference", "DocumentReference/{free_text_doc_id}"),
}


def _build_jp_clins_discharge_summary_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    enc_to_free_text: dict[str, str] | None = None,
) -> dict[str, Any]:
    """JP-CLINS eDischargeSummary v1.12.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eDischargeSummary]
      - type.coding[0].system = doc-typecodes(LOINC coding は US 互換の
        ため secondary として併存)
      - section は 1-level nested tree:300 構造情報 → 必須 5 子 section
        (312/322/342/352/360)。section.code.system は JP-CLINS 定義の
        document-section CodeSystem(URL:
        `http://jpfhir.jp/fhir/clins/CodeSystem/document-section`、LOINC
        section code ではない)。
    """
    # 共通 field(id / subject / date / author / encounter / attester /
    # custodian / confidentiality 等)は汎用 builder を再利用し、type と
    # section のみ上書きする。
    comp = _build_composition_generic(doc, sections, lang)

    # meta.profile 追加(既に含まれていれば skip)
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_CLINS_DS_PROFILE not in profs:
        profs.append(_JP_CLINS_DS_PROFILE)

    # (Chain #9) `meta.lastUpdated` min=1 — reuse authoredOn / date. Emit
    # only when a source datetime exists so we never fabricate.
    if not meta.get("lastUpdated"):
        ts = comp.get("date") or _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    # `type` field:jpfhir doc-typecodes を primary。
    # Session 57 v3 fix: eDS profile constrains type.coding to max=1, so
    # emit only the doc-typecodes coding — the LOINC copy (previously
    # emitted for interop) violated the profile slicing on 129 resources.
    # The LOINC value is preserved via type.text so downstream consumers
    # can still recover the same code as text.
    disp = code_lookup("jpfhir-doc-typecodes", "18842-5", lang) or _JP_EDS_TYPE_DISPLAY_JA
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "18842-5", "display": disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # (Chain #9) `Composition.extension:version` min=1 — 文書バージョン番号。
    # The extension slice is discriminated by URL; value[x] is `valueString`
    # per spec `valueString`. clinosim emits "1" (initial issue) since no
    # revision history is tracked; downstream systems can update in place.
    exts = comp.setdefault("extension", [])
    if not any(isinstance(e, dict) and e.get("url") == _JP_EDS_VERSION_EXTENSION_URL for e in exts):
        exts.append({"url": _JP_EDS_VERSION_EXTENSION_URL, "valueString": "1"})

    # (Chain #9) `Composition.category` min=1 max=1 — fixed to DISCHARGE
    # under the doc-subtypecodes CodeSystem.
    comp["category"] = [
        {
            "coding": [
                {
                    "system": _JPFHIR_DOC_SUBTYPECODES_SYSTEM,
                    "code": _JP_EDS_CATEGORY_CODE,
                    "display": _JP_EDS_CATEGORY_DISPLAY_JA,
                }
            ]
        }
    ]

    # (Chain #9) `Composition.author` min=2 — 文書作成責任者 (Practitioner)
    # + 文書作成機関 (Organization). Generic builder already sets
    # author[0]=Practitioner from doc.author_practitioner_id. Append an
    # Organization reference. Uses the clinosim facility placeholder id;
    # downstream FHIR consumers resolve against `Organization/hospital-main`
    # (defined by the facility bundle).
    authors = comp.setdefault("author", [])
    if not isinstance(authors, list):
        authors = []
        comp["author"] = authors
    if not any(isinstance(a, dict) and str(a.get("reference", "")).startswith("Organization/") for a in authors):
        authors.append({"reference": "Organization/hospital-main"})

    # (Chain #9) section tree — 300 parent + 10 required child sections.
    # yaml carries `構造情報セクション` (long form, matches spec `patternString`);
    # `_section_title_from_section_display` derives the short-form title
    # per spec `title.fixedString` (Chain #8 pattern).
    parent_disp = code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    parent_title = _section_title_from_section_display(parent_disp)
    # Chain #9 follow-up (#267 / session 59 #278): pre-compute the ids the
    # entry references need. session 59 で hospital_course の deferral を
    # 解消 — `_bb_compositions` が enc → free-text DocumentReference id map
    # を precompute し `enc_to_free_text` として渡す。map hit しない場合は
    # `free_text_doc_id` を空文字で埋め、下の never-fabricate guard で drop。
    _enc_id = _o(doc, "encounter_id", "") or ""
    _free_text_doc_id = (enc_to_free_text or {}).get(_enc_id, "")
    _entry_ctx = {"encounter_id": _enc_id, "free_text_doc_id": _free_text_doc_id}

    child_sections: list[dict[str, Any]] = []
    for key, code in _JP_DS_SECTION_CODE.items():
        disp_c = code_lookup("jpfhir-doc-section", code, lang) or key
        title_c = _section_title_from_section_display(disp_c)
        text_val = sections.get(key, "") or ""
        # Chain #9: section.code.text max=0 — drop `text` from `code`.
        section_obj: dict[str, Any] = {
            "title": title_c,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": code,
                        "display": disp_c,
                    }
                ],
            },
            # Session 57 Chain 8: JP-CLINS pins `text.status` to `additional`.
            "text": {
                "status": "additional",
                "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
            },
        }
        # Chain #9 follow-up (#267): required `.entry` reference on
        # detailsOnAdmission / hospitalCourse / detailsOnDischarge /
        # diagnosesOnDischarge slices. Only emit when the referenced resource
        # id is derivable (encounter_id / document_id present); a missing
        # source leaves the entry off so we never fabricate a broken
        # reference.
        entry_spec = _JP_DS_SECTION_ENTRY_REFERENCES.get(key)
        if entry_spec is not None:
            _, ref_template = entry_spec
            try:
                ref = ref_template.format(**_entry_ctx)
            except KeyError:
                ref = ""
            # Reject broken references — any format substitution that ended up
            # empty leaves the string looking like `Encounter/` or
            # `Condition/cond--primary`. Both are dead references so we drop
            # the entry rather than emit garbage.
            # session 59 #278: `DocumentReference/` (empty free_text_doc_id
            # fallback) too — same never-fabricate guard.
            if ref.endswith("/") or "//" in ref or "cond--primary" in ref:
                ref = ""
            if ref:
                section_obj["entry"] = [{"reference": ref}]
        child_sections.append(section_obj)
    # Parent structuredSection — Chain #9: drop `code.text` (max=0) and use
    # title-short / display-long split.
    comp["section"] = [
        {
            "title": parent_title,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": "300",
                        "display": parent_disp,
                    }
                ],
            },
            "section": child_sections,
        }
    ]
    return comp


# ============================================================
# P2-13 PR2b:JP-CLINS 診療情報提供書用 Composition builder
# ============================================================

_JP_CLINS_REFERRAL_PROFILE = "http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral"

# JP-CLINS eReferral の必須 section 構造:
#   920 紹介元 / 910 紹介先 / 300 構造情報
#     └ 950 紹介目的 / 340 傷病名・主訴 / 360 現病歴
# トップレベルは 920 + 910 を並列に配置、300 構造情報の下に 3 個の
# 子 section(950/340/360)を nest する。
# section キー → jpfhir 番号 code の対応:
_JP_REFERRAL_TOP_LEVEL: dict[str, str] = {
    "referring_institution": "920",
    "referral_destination": "910",
}
_JP_REFERRAL_STRUCTURAL_CHILDREN: dict[str, str] = {
    "referral_purpose": "950",
    "diagnoses_and_complaint": "340",
    "present_illness_ref": "360",
}


# session 59 #289 sibling of eDS Chain #9:JP-CLINS eReferral は eDS と同
# 5 top-level 制約を持つ(extension:version min=1 / category min=1 /
# author min=2 / meta.lastUpdated min=1 / event.code min=1)。CONSULT
# は authoritative doc-subtypecodes CS "他科コンサルト"(spec:
# clinical-information-sharing#1.12.0/package/CodeSystem-jp-codeSystem-
# documentSubTypeCode.json)。
_JP_ER_CATEGORY_CODE = "CONSULT"
_JP_ER_CATEGORY_DISPLAY_JA = "他科コンサルト"
# event.code は min=1 だが coding は不要、text-only CodeableConcept で満た
# せる。narrative 用に定型文字列を pin。
_JP_ER_EVENT_CODE_TEXT_JA = "他医療機関紹介"


def _build_jp_clins_referral_note_composition(doc: Any, sections: dict[str, str], lang: str) -> dict[str, Any]:
    """JP-CLINS eReferral v1.12.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eReferral]
      - type.coding[0].system = doc-typecodes(LOINC coding は interop 用に
        secondary として併存)
      - section は 2-level tree:
          top-level:920 紹介元, 910 紹介先, 300 構造情報
          300 の下:950 紹介目的, 340 傷病名・主訴, 360 現病歴
        section.code.system は JP-CLINS document-section CodeSystem
        (URL: `http://jpfhir.jp/fhir/clins/CodeSystem/document-section`)固定。
      - session 59 #289:eDS Chain #9 の 5 top-level 制約を eReferral にも適用。
    """
    comp = _build_composition_generic(doc, sections, lang)

    # meta.profile 追加(既に含まれていれば skip)
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_CLINS_REFERRAL_PROFILE not in profs:
        profs.append(_JP_CLINS_REFERRAL_PROFILE)

    # #289:meta.lastUpdated min=1(Chain #9 pattern)。builder-set 済なら尊重、
    # 未 set なら authored_datetime へ fallback。
    if not meta.get("lastUpdated"):
        ts = _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    # `type` field:57133-1 (eReferral / referral note)
    # Session 57 v3 fix: eReferral profile constrains type.coding to a
    # single doc-typecodes coding. LOINC copy removed; the LOINC value is
    # preserved via type.text.
    disp = code_lookup("jpfhir-doc-typecodes", "57133-1", lang) or "診療情報提供書"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "57133-1", "display": disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # #289 (Chain #9 pattern):Composition.extension:version min=1。
    # 文書 revision 番号は未 tracking のため "1"(initial issue)を pin。
    exts = comp.setdefault("extension", [])
    if not any(isinstance(e, dict) and e.get("url") == _JP_EDS_VERSION_EXTENSION_URL for e in exts):
        exts.append({"url": _JP_EDS_VERSION_EXTENSION_URL, "valueString": "1"})

    # #289 (Chain #9 pattern):Composition.category min=1 max=1 — fixed to
    # CONSULT("他科コンサルト")under doc-subtypecodes CS(authoritative
    # display verified in spec CodeSystem file)。
    comp["category"] = [
        {
            "coding": [
                {
                    "system": _JPFHIR_DOC_SUBTYPECODES_SYSTEM,
                    "code": _JP_ER_CATEGORY_CODE,
                    "display": _JP_ER_CATEGORY_DISPLAY_JA,
                }
            ]
        }
    ]

    # #289 (Chain #9 pattern):Composition.author min=2 — 文書作成責任者
    # (Practitioner)+ 文書作成機関(Organization)。generic builder は既に
    # Practitioner を author[0] に置くので Organization reference を追加。
    authors = comp.setdefault("author", [])
    if not isinstance(authors, list):
        authors = []
        comp["author"] = authors
    if not any(isinstance(a, dict) and str(a.get("reference", "")).startswith("Organization/") for a in authors):
        authors.append({"reference": "Organization/hospital-main"})

    # #289:Composition.event.code min=1(coding は不要、text で満たす)。
    # generic builder が既に event[0]{period,detail} を set 済のため、既存
    # event[0] に code を追加。event 未 set の場合も安全に追加。
    events = comp.setdefault("event", [])
    if not events:
        events.append({})
    events[0].setdefault(
        "code",
        {"text": _JP_ER_EVENT_CODE_TEXT_JA},
    )

    def _one_section(section_code: str, text_val: str) -> dict[str, Any]:
        # Session 58 Chain #8: title = short form, display = long form.
        # Session 58 Chain #9: `code.text` max=0 → omit.
        disp_c = code_lookup("jpfhir-doc-section", section_code, lang) or section_code
        title_c = _section_title_from_section_display(disp_c)
        return {
            "title": title_c,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": section_code,
                        "display": disp_c,
                    }
                ],
            },
            # Session 57 Chain 8 (v2 feedback §【中優先 8】): JP-CLINS eReferral
            # pins Composition.section[*].text.status to fixedCode "additional".
            "text": {
                "status": "additional",
                "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
            },
        }

    # Top-level 920 + 910
    top_sections: list[dict[str, Any]] = []
    for key, code in _JP_REFERRAL_TOP_LEVEL.items():
        top_sections.append(_one_section(code, sections.get(key, "") or ""))

    # 300 structural, nesting 950 / 340 / 360
    struct_children: list[dict[str, Any]] = []
    for key, code in _JP_REFERRAL_STRUCTURAL_CHILDREN.items():
        struct_children.append(_one_section(code, sections.get(key, "") or ""))
    # Session 58 Chain #8 + #9: yaml carries the canonical long form; title is
    # derived by stripping `セクション`; `code.text` is dropped (max=0 per spec).
    struct_parent_disp = code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    struct_parent_title = _section_title_from_section_display(struct_parent_disp)
    top_sections.append(
        {
            "title": struct_parent_title,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": "300",
                        "display": struct_parent_disp,
                    }
                ],
            },
            "section": struct_children,
        }
    )
    comp["section"] = top_sections
    return comp


# ============================================================
# P2-13 PR3:JP-eCheckup General 健診結果報告書用 Composition builder
# ============================================================

_JP_ECHECKUP_GENERAL_PROFILE = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral"
_JPFHIR_ECHECKUP_SECTION_SYSTEM = "http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code"

# eCheckup General の section キー + 健診種別 → jpfhir eCheckup 番号 code(sub-PR-D)
# checkup_type("occupational"/"specific"/"regional_union")と section key
# (checkup_lab_results / checkup_questionnaire)の組で dispatch する。
_JP_ECHECKUP_SECTION_CODE_MATRIX: dict[str, dict[str, str]] = {
    "occupational": {
        "checkup_lab_results": "01031",  # 事業者健診検査結果セクション
        "checkup_questionnaire": "01032",  # 事業者健診問診結果セクション
    },
    "specific": {
        "checkup_lab_results": "01011",  # 特定健診検査結果セクション
        "checkup_questionnaire": "01012",  # 特定健診問診結果セクション
    },
    "regional_union": {
        "checkup_lab_results": "01021",  # 広域連合保健事業検査結果セクション
        "checkup_questionnaire": "01022",  # 広域連合保健事業問診結果セクション
    },
}

# 既存 test 互換 alias。checkup_type 未指定時は事業者健診として dispatch。
_JP_ECHECKUP_SECTION_CODE: dict[str, str] = _JP_ECHECKUP_SECTION_CODE_MATRIX["occupational"]


def _build_jp_eCheckup_general_composition(doc: Any, sections: dict[str, str], lang: str) -> dict[str, Any]:
    """JP-eCheckup General v1.7.0 準拠 Composition を emit する(JP-only、opt-in)。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eCheckupGeneral]
      - type.coding[0].system = doc-typecodes(53576-5)、LOINC coding も併存
      - section は flat 2 個(事業者健診の必須 2 section:01031 検査結果、
        01032 問診結果)。section.code.system は eCheckup 固有 CodeSystem。
    """
    comp = _build_composition_generic(doc, sections, lang)

    # meta.profile 追加
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_ECHECKUP_GENERAL_PROFILE not in profs:
        profs.append(_JP_ECHECKUP_GENERAL_PROFILE)

    # `type` field:53576-5 を doc-typecodes と LOINC 両方で emit
    disp = code_lookup("jpfhir-doc-typecodes", "53576-5", lang) or "検診・健診報告書"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "53576-5", "display": disp},
            {
                "system": get_system_uri("loinc"),
                "code": "53576-5",
                "display": code_lookup("loinc", "53576-5", lang) or disp,
            },
        ],
        "text": disp,
    }
    comp["title"] = disp

    # section:2 個 flat(nesting なし)
    # sub-PR-D:doc.checkup_type から健診種別を dispatch(未設定なら
    # occupational 事業者健診にfallback)
    checkup_type = _o(doc, "checkup_type", "") or "occupational"
    section_code_map = _JP_ECHECKUP_SECTION_CODE_MATRIX.get(
        checkup_type, _JP_ECHECKUP_SECTION_CODE_MATRIX["occupational"]
    )
    section_entries: list[dict[str, Any]] = []
    for key, code in section_code_map.items():
        disp_c = code_lookup("jpfhir-eCheckup-section", code, lang) or key
        text_val = sections.get(key, "") or ""
        # Session 58 Chain #8 / #9: eCheckup section entries follow the same
        # code.text=absent / title-vs-display convention as eDS / eReferral.
        title_c = _section_title_from_section_display(disp_c)
        section_entries.append(
            {
                "title": title_c,
                "code": {
                    "coding": [
                        {
                            "system": _JPFHIR_ECHECKUP_SECTION_SYSTEM,
                            "code": code,
                            "display": disp_c,
                        }
                    ],
                },
                # Session 57 Chain 8 (v2 feedback §【中優先 8】): JP-CLINS
                # eDischargeSummary / eReferral / eCheckup pin
                # Composition.section[*].text.status to fixedCode "additional"
                # (see fhir-jp-validator/tx-server-build/.../clinical-information-sharing#1.12.0
                # StructureDefinition-JP-Composition-*.json). generic
                # Composition (_build_composition_generic below) keeps
                # "generated" per base FHIR default.
                "text": {
                    "status": "additional",
                    "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
                },
            }
        )
    comp["section"] = section_entries
    return comp
