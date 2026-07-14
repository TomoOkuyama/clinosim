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


# C2-27 (session 42 cycle 2): map section titles (as produced by document
# enrichers / narrative pass) to LOINC section codes. Codes verified via the
# LOINC search (loinc.org), matching HL7 recommendations for CCD document
# sections. Titles not listed here remain title-only until either the enricher
# starts emitting a canonical title or the code is verified.
_SECTION_LOINC: dict[str, str] = {
    # SOAP outpatient / progress notes
    "subjective": "10164-2",           # History of Present illness (subj narrative)
    "objective": "8716-3",             # Vital signs (objective) — narrower approx
    "assessment": "51848-0",           # Evaluation note (assessment)
    "plan": "18776-5",                 # Plan of care note
    # Admission H&P / progress
    "chief_complaint": "10154-3",      # Chief complaint
    "hpi": "10164-2",                  # History of present illness
    "past_medical_history": "11348-0", # History of past illness
    "medications_at_home": "10160-0",  # History of medication use
    "physical_exam": "29545-1",        # Physical findings
    "triage_details": "56816-2",       # Vital signs assessment (triage)
    # Discharge summary
    "admission_summary": "10154-3",    # (reused, admission complaint)
    "hospital_course": "8648-8",       # Hospital course
    "discharge_diagnoses": "11535-2",  # Hospital discharge diagnosis
    "discharge_medications": "10183-2",# Hospital discharge medications
    # Nursing sections
    "nursing_history": "34117-2",      # History and physical (H&P)
    "adl_assessment": "45391-8",       # Functional status assessment
    "risk_assessments": "75326-9",     # Assessment plan
    "nursing_diagnosis": "51848-0",    # Evaluation note (approx)
    "admission_status": "8648-8",      # Hospital course
    "nursing_interventions_provided": "10184-0", # Interventions
    "patient_education": "42346-6",    # Patient education plan
    "discharge_readiness": "8650-4",   # Hospital discharge readiness
    # Ward-info & plan sections
    "ward_and_room": "42349-1",        # Reason for visit (approx)
    "other_staff": "51897-7",          # Care team member
    "diagnosis": "29308-4",            # Diagnosis
    "symptoms": "10187-3",             # Review of systems (approx)
    "ward_and_physician": "42349-1",   # Reason for visit
    "dietitian": "51897-7",            # Care team member
    "nutrition_risk": "61144-2",       # Diet and nutrition Narrative (C4-04 cycle 4: 9279-1 was Respiratory rate — wrong LOINC)
    "nutrition_assessment": "61144-2", # (same)
    # Rehab
    "patient_and_diagnosis": "29308-4",# Diagnosis
    "rehab_team": "51897-7",           # Care team member
    "functional_status": "45391-8",    # Functional status assessment
    "basic_movement": "45391-8",       # (same)
    # CY2-C (session 42 cycle 3): residual auto-derived section titles that
    # appeared in cycle 2's 8% uncoded remainder. Codes verified via LOINC
    # search.
    "ed_workup": "51852-2",            # Workup panel (ED assessment)
    "disposition": "68609-7",          # Discharge disposition (ED disposition)
    "allergies": "48765-2",            # Allergies and adverse reactions
    "social_history": "29762-2",       # Social history
    "family_history": "10157-6",       # History of family member disease
    "physical_examination": "29545-1", # Physical findings (reuse of physical_exam)
    "assessment_and_plan": "51847-2",  # Assessment and plan note
    "care_plan": "18776-5",            # Plan of care note (reuse of plan)
    "treatment_plan": "18776-5",       # (reused)
    "test_schedule": "18776-5",        # (falls under plan)
    "surgery_schedule": "18776-5",     # (falls under plan)
    "estimated_los": "8648-8",         # Hospital course (LOS estimate)
    "special_nutrition_management": "61144-2", # Diet and nutrition Narrative
    "other_plans": "18776-5",          # Plan of care (catch-all)
    "discharge_instructions": "8653-8",# Hospital discharge instructions
    "follow_up": "18776-5",            # Plan of care (follow-up)
    "nutrition_goals": "61144-2",      # Diet nutrition goals
    "nutrition_supply": "61144-2",     # (same)
    "dysphagia_diet": "61144-2",       # (same)
    "dietary_content": "61144-2",      # (same)
    # C4-19 (session 43 cycle 4): residual unmapped titles from cycle 4
    # baseline (546 sections in JP p=10000). Bind to the closest LOINC where
    # the CCDA / narrative theme corresponds; uncertain titles fall back to
    # a plan-of-care catch-all (18776-5) matching how care_plan / follow_up
    # already map above.
    "nutrition_counseling": "61144-2",   # Diet and nutrition Narrative
    "other_issues": "51852-2",           # Provider unspecified Progress note (catch-all narrative)
    "reassessment_timing": "18776-5",    # Plan of care (schedule)
    "discharge_evaluation": "8650-4",    # Hospital discharge readiness
    "session_frequency": "18776-5",      # Plan of care
    "goals": "18776-5",                  # Plan of care (goals section of care plan)
    "policy": "18776-5",                 # Plan of care (policy = clinical plan)
    "discharge_estimate": "8648-8",      # Hospital course (estimated LOS/discharge)
    "explanation_consent": "42346-6",    # Patient education (consent / explanation)
}


def _bb_compositions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one Composition per ClinicalDocument with format_type='composition'.

    Skips (with a warning) any stub whose narrative subtree is still None —
    i.e. the Stage 2 narrative pass has not (yet) generated content for this
    document_id. This is expected for documents produced between `generate`
    and `narrate` runs, not a data-quality defect.
    """
    raw_docs = _o(ctx.record, "documents", []) or []
    lang = resolve_lang(ctx.country)
    out: list[dict[str, Any]] = []
    for doc in raw_docs:
        if _o(doc, "format_type", "") != "composition":
            continue
        narrative = _o(doc, "narrative", None)
        if not narrative:
            logger.warning(
                "composition stub %s has no narrative (Stage 2 pass not run "
                "for this document) — skipping",
                _o(doc, "document_id", ""),
            )
            continue
        sections = _o(narrative, "sections", {}) or {}
        out.append(_build_composition(doc, sections, lang))
    return out


def _build_composition(doc: Any, sections: dict[str, str], lang: str) -> dict[str, Any]:
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
            return _build_jp_clins_discharge_summary_composition(doc, sections, lang)
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
    enc_part = doc_id[len(DOC_REFERENCE_ID_PREFIX):] if doc_id.startswith(DOC_REFERENCE_ID_PREFIX) else doc_id
    comp_id = f"{COMPOSITION_ID_PREFIX}{enc_part}"
    res: dict[str, Any] = {
        "resourceType": "Composition",
        "id": comp_id,
        # C2-34 (session 42 cycle 2): Composition.identifier (0..1) for
        # cross-system document tracking. Uses the same id under a clinosim
        # namespace URI — deterministic + unique across the export.
        "identifier": {
            "system": "urn:clinosim:composition-id",
            "value": comp_id,
        },
        "status": "final",
        "type": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": loinc_code,
                "display": loinc_display or loinc_code,
            }],
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
        "author": [{"reference": f"Practitioner/{author_id}"}] if author_id else [{"reference": "Practitioner/UNKNOWN"}],
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
        res["attester"] = [{
            "mode": "legal",
            "time": authored_dt,
            "party": {"reference": f"Practitioner/{author_id}"},
        }]

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
            entry["code"] = {"coding": [{
                "system": get_system_uri("loinc"),
                "code": loinc_section,
                "display": code_lookup("loinc", loinc_section, lang) or section_title,
            }]}
        section_entries.append(entry)
    if section_entries:
        res["section"] = section_entries

    return res


# ============================================================
# P2-13 PR2a:JP-CLINS 退院時サマリー用 Composition builder
# ============================================================

_JP_CLINS_DS_PROFILE = (
    "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/"
    "JP_Composition_eDischargeSummary"
)
_JPFHIR_DOC_TYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_JPFHIR_DOC_SECTION_SYSTEM = (
    "http://jpfhir.jp/fhir/clins/CodeSystem/jp-codeSystem-clins-document-section"
)

# JP-CLINS 退院時サマリー section キー → jpfhir-doc-section 番号 code
_JP_DS_SECTION_CODE: dict[str, str] = {
    "admission_reason":    "312",
    "admission_details":   "322",
    "admission_diagnoses": "342",
    "chief_complaint":     "352",
    "present_illness":     "360",
}


def _build_jp_clins_discharge_summary_composition(
    doc: Any, sections: dict[str, str], lang: str
) -> dict[str, Any]:
    """JP-CLINS eDischargeSummary v1.12.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eDischargeSummary]
      - type.coding[0].system = doc-typecodes(LOINC coding は US 互換の
        ため secondary として併存)
      - section は 1-level nested tree:300 構造情報 → 必須 5 子 section
        (312/322/342/352/360)。section.code.system は
        jp-codeSystem-clins-document-section(LOINC section code ではない)。
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

    # `type` field:jpfhir doc-typecodes を primary、LOINC を secondary(interop 用)
    disp = code_lookup("jpfhir-doc-typecodes", "18842-5", lang) or "退院時サマリー"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM,
             "code": "18842-5", "display": disp},
            {"system": get_system_uri("loinc"),
             "code": "18842-5", "display": code_lookup("loinc", "18842-5", lang) or disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # section: 300 parent + 5 child sections
    parent_disp = code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    child_sections: list[dict[str, Any]] = []
    for key, code in _JP_DS_SECTION_CODE.items():
        disp_c = code_lookup("jpfhir-doc-section", code, lang) or key
        text_val = sections.get(key, "") or ""
        child_sections.append({
            "title": disp_c,
            "code": {
                "coding": [{
                    "system": _JPFHIR_DOC_SECTION_SYSTEM,
                    "code": code,
                    "display": disp_c,
                }],
                "text": disp_c,
            },
            "text": {
                "status": "generated",
                "div": (
                    f'<div xmlns="http://www.w3.org/1999/xhtml">'
                    f"{_escape_html(text_val)}</div>"
                ),
            },
        })
    comp["section"] = [{
        "title": parent_disp,
        "code": {
            "coding": [{
                "system": _JPFHIR_DOC_SECTION_SYSTEM,
                "code": "300",
                "display": parent_disp,
            }],
            "text": parent_disp,
        },
        "section": child_sections,
    }]
    return comp


# ============================================================
# P2-13 PR2b:JP-CLINS 診療情報提供書用 Composition builder
# ============================================================

_JP_CLINS_REFERRAL_PROFILE = (
    "http://jpfhir.jp/fhir/eReferral/StructureDefinition/"
    "JP_Composition_eReferral"
)

# JP-CLINS eReferral の必須 section 構造:
#   920 紹介元 / 910 紹介先 / 300 構造情報
#     └ 950 紹介目的 / 340 傷病名・主訴 / 360 現病歴
# トップレベルは 920 + 910 を並列に配置、300 構造情報の下に 3 個の
# 子 section(950/340/360)を nest する。
# section キー → jpfhir 番号 code の対応:
_JP_REFERRAL_TOP_LEVEL: dict[str, str] = {
    "referring_institution":  "920",
    "referral_destination":   "910",
}
_JP_REFERRAL_STRUCTURAL_CHILDREN: dict[str, str] = {
    "referral_purpose":         "950",
    "diagnoses_and_complaint":  "340",
    "present_illness_ref":      "360",
}


def _build_jp_clins_referral_note_composition(
    doc: Any, sections: dict[str, str], lang: str
) -> dict[str, Any]:
    """JP-CLINS eReferral v1.12.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eReferral]
      - type.coding[0].system = doc-typecodes(LOINC coding は interop 用に
        secondary として併存)
      - section は 2-level tree:
          top-level:920 紹介元, 910 紹介先, 300 構造情報
          300 の下:950 紹介目的, 340 傷病名・主訴, 360 現病歴
        section.code.system は jp-codeSystem-clins-document-section 固定。
    """
    comp = _build_composition_generic(doc, sections, lang)

    # meta.profile 追加(既に含まれていれば skip)
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_CLINS_REFERRAL_PROFILE not in profs:
        profs.append(_JP_CLINS_REFERRAL_PROFILE)

    # `type` field:57133-1 を doc-typecodes と LOINC の両方で emit(interop 用)
    disp = code_lookup("jpfhir-doc-typecodes", "57133-1", lang) or "診療情報提供書"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM,
             "code": "57133-1", "display": disp},
            {"system": get_system_uri("loinc"),
             "code": "57133-1", "display": code_lookup("loinc", "57133-1", lang) or disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    def _one_section(section_code: str, text_val: str) -> dict[str, Any]:
        disp_c = (
            code_lookup("jpfhir-doc-section", section_code, lang) or section_code
        )
        return {
            "title": disp_c,
            "code": {
                "coding": [{
                    "system": _JPFHIR_DOC_SECTION_SYSTEM,
                    "code": section_code,
                    "display": disp_c,
                }],
                "text": disp_c,
            },
            "text": {
                "status": "generated",
                "div": (
                    f'<div xmlns="http://www.w3.org/1999/xhtml">'
                    f"{_escape_html(text_val)}</div>"
                ),
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
    struct_parent_disp = (
        code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    )
    top_sections.append({
        "title": struct_parent_disp,
        "code": {
            "coding": [{
                "system": _JPFHIR_DOC_SECTION_SYSTEM,
                "code": "300",
                "display": struct_parent_disp,
            }],
            "text": struct_parent_disp,
        },
        "section": struct_children,
    })
    comp["section"] = top_sections
    return comp


# ============================================================
# P2-13 PR3:JP-eCheckup General 健診結果報告書用 Composition builder
# ============================================================

_JP_ECHECKUP_GENERAL_PROFILE = (
    "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral"
)
_JPFHIR_ECHECKUP_SECTION_SYSTEM = (
    "http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code"
)

# eCheckup General の section キー + 健診種別 → jpfhir eCheckup 番号 code(sub-PR-D)
# checkup_type("occupational"/"specific"/"regional_union")と section key
# (checkup_lab_results / checkup_questionnaire)の組で dispatch する。
_JP_ECHECKUP_SECTION_CODE_MATRIX: dict[str, dict[str, str]] = {
    "occupational": {
        "checkup_lab_results":   "01031",  # 事業者健診検査結果セクション
        "checkup_questionnaire": "01032",  # 事業者健診問診結果セクション
    },
    "specific": {
        "checkup_lab_results":   "01011",  # 特定健診検査結果セクション
        "checkup_questionnaire": "01012",  # 特定健診問診結果セクション
    },
    "regional_union": {
        "checkup_lab_results":   "01021",  # 広域連合保健事業検査結果セクション
        "checkup_questionnaire": "01022",  # 広域連合保健事業問診結果セクション
    },
}

# 既存 test 互換 alias。checkup_type 未指定時は事業者健診として dispatch。
_JP_ECHECKUP_SECTION_CODE: dict[str, str] = _JP_ECHECKUP_SECTION_CODE_MATRIX["occupational"]


def _build_jp_eCheckup_general_composition(
    doc: Any, sections: dict[str, str], lang: str
) -> dict[str, Any]:
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
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM,
             "code": "53576-5", "display": disp},
            {"system": get_system_uri("loinc"),
             "code": "53576-5", "display": code_lookup("loinc", "53576-5", lang) or disp},
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
        disp_c = (
            code_lookup("jpfhir-eCheckup-section", code, lang) or key
        )
        text_val = sections.get(key, "") or ""
        section_entries.append({
            "title": disp_c,
            "code": {
                "coding": [{
                    "system": _JPFHIR_ECHECKUP_SECTION_SYSTEM,
                    "code": code,
                    "display": disp_c,
                }],
                "text": disp_c,
            },
            "text": {
                "status": "generated",
                "div": (
                    f'<div xmlns="http://www.w3.org/1999/xhtml">'
                    f"{_escape_html(text_val)}</div>"
                ),
            },
        })
    comp["section"] = section_entries
    return comp
