"""JP-CLINS eReferral v1.13.0 Composition builder (診療情報提供書).

Extracted verbatim from ``composition.py::_build_jp_clins_referral_note_
composition`` (full-review Phase B3, CRITICAL C5b). Same lazy-import
pattern as the discharge-summary split: the builder reuses
``_build_composition_generic`` and ``_section_title_from_section_display``
from composition.py through a function-body import so module load stays
cycle-free.

JP-CLINS eReferral section-tree constraints (920 紹介元 / 910 紹介先 /
300 構造情報 → 950 / 340 / 360) are preserved as-is. The 910 destination
is drawn deterministically from ``external_organizations.yaml`` per
Issue #924.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import display as registry_display
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import uses_jp_clins_profile
from clinosim.modules.output.fhir_r4.documents.referral_orgs import (
    format_referral_destination_text,
    pick_external_hospital,
)
from clinosim.modules.output.fhir_r4.lib.common import _escape_html

# ---------------------------------------------------------------------------
# JP-CLINS eReferral constants (verbatim from composition.py).
# ---------------------------------------------------------------------------
_JP_CLINS_REFERRAL_PROFILE = "http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral"

# JP-CLINS eReferral の必須 section 構造:
#   920 紹介元 / 910 紹介先 / 300 構造情報
#     └ 950 紹介目的 / 340 傷病名・主訴 / 360 現病歴
_JP_REFERRAL_TOP_LEVEL: dict[str, str] = {
    "referring_institution": "920",
    "referral_destination": "910",
}
_JP_REFERRAL_STRUCTURAL_CHILDREN: dict[str, str] = {
    "referral_purpose": "950",
    "diagnoses_and_complaint": "340",
    "present_illness_ref": "360",
}

# 920 (referralFromOrganization) self-pin — see composition.py's
# original docstring for the Issue #924 self-loop fix rationale.
_JP_ER_REFERRING_FROM_REF: list[dict[str, str]] = [{"reference": "Organization/hospital-main"}]

# #289 Chain #9 pattern: category + event-code constants.
_JP_ER_CATEGORY_CODE = "CONSULT"
_JP_ER_CATEGORY_DISPLAY_JA = "他科コンサルト"
_JP_ER_EVENT_CODE_TEXT_JA = "診療情報提供書発行"

# Shared system URIs (re-declared locally; mirror composition.py's
# module-level defs so this file is self-contained).
_JPFHIR_DOC_TYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_JPFHIR_DOC_SUBTYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-subtypecodes"
_JPFHIR_DOC_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"
_JP_EDS_VERSION_EXTENSION_URL = "http://hl7.org/fhir/StructureDefinition/composition-clinicaldocument-versionNumber"


def _build_jp_clins_referral_note_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    roster_map: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """JP-CLINS eReferral v1.13.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eReferral]
      - type.coding[0].system = doc-typecodes(LOINC coding は interop 用に
        secondary として併存)
      - section は 2-level tree:
          top-level:920 紹介元, 910 紹介先, 300 構造情報
          300 の下:950 紹介目的, 340 傷病名・主訴, 360 現病歴
        section.code.system は JP-CLINS document-section CodeSystem
        (URL: `http://jpfhir.jp/fhir/clins/CodeSystem/document-section`)固定。
      - #289:eDS Chain #9 の 5 top-level 制約を eReferral にも適用。
    """
    # Lazy imports break the composition.py ↔ referral_note.py cycle.
    from clinosim.modules.output.fhir_r4.documents.composition import (
        _build_composition_generic,
        _section_title_from_section_display,
    )

    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map)

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
    # v3 fix: eReferral profile constrains type.coding to a
    # single doc-typecodes coding. LOINC copy removed; the LOINC value is
    # preserved via type.text.
    disp = registry_display("jpfhir-doc-typecodes", "57133-1", lang) or "診療情報提供書"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "57133-1", "display": disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # #289 (Chain #9 pattern):Composition.extension:version min=1。
    exts = comp.setdefault("extension", [])
    if not any(isinstance(e, dict) and e.get("url") == _JP_EDS_VERSION_EXTENSION_URL for e in exts):
        exts.append({"url": _JP_EDS_VERSION_EXTENSION_URL, "valueString": "1"})

    # #289 (Chain #9 pattern):Composition.category min=1 max=1 — CONSULT
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

    # #289 (Chain #9 pattern):Composition.author min=2.
    authors = comp.setdefault("author", [])
    if not isinstance(authors, list):
        authors = []
        comp["author"] = authors
    if not any(isinstance(a, dict) and str(a.get("reference", "")).startswith("Organization/") for a in authors):
        authors.append({"reference": "Organization/hospital-main"})

    # #330 custodian pin.
    comp["custodian"] = {"reference": "Organization/hospital-main"}

    # #289:event.code min=1 (coding max=0, text-only).
    events = comp.setdefault("event", [])
    if not events:
        events.append({})
    events[0].setdefault(
        "code",
        [{"text": _JP_ER_EVENT_CODE_TEXT_JA}],
    )

    # Section builder helper (nested inside the function in the original
    # composition.py; kept nested here to preserve exactly matching
    # closure semantics / behavior).
    def _one_section(
        section_code: str,
        text_val: str,
        entry_refs: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        disp_c = registry_display("jpfhir-doc-section", section_code, lang) or section_code
        title_c = _section_title_from_section_display(disp_c)
        section_obj: dict[str, Any] = {
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
            "text": {
                "status": "additional",
                "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
            },
        }
        if entry_refs:
            section_obj["entry"] = entry_refs
        return section_obj

    # Issue #924: 920 self-pin / 910 external-catalog sample.
    pid = _o(doc, "patient_id", "") or ""
    eid = _o(doc, "encounter_id", "") or ""
    external_dest = pick_external_hospital(pid, eid, country="JP") if uses_jp_clins_profile(lang) else None

    top_entry_by_code: dict[str, list[dict[str, str]]] = {
        "920": _JP_ER_REFERRING_FROM_REF,
        "910": ([{"reference": f"Organization/{external_dest['id']}"}] if external_dest else _JP_ER_REFERRING_FROM_REF),
    }
    top_text_by_key: dict[str, str] = {
        "referring_institution": sections.get("referring_institution", "") or "",
        "referral_destination": (
            format_referral_destination_text(external_dest, lang="ja")
            if external_dest
            else (sections.get("referral_destination", "") or "")
        ),
    }
    top_sections: list[dict[str, Any]] = []
    for key, code in _JP_REFERRAL_TOP_LEVEL.items():
        top_sections.append(_one_section(code, top_text_by_key.get(key, ""), top_entry_by_code.get(code)))

    # 300 structural, nesting 950 / 340 / 360
    struct_children: list[dict[str, Any]] = []
    for key, code in _JP_REFERRAL_STRUCTURAL_CHILDREN.items():
        struct_children.append(_one_section(code, sections.get(key, "") or ""))
    struct_parent_disp = registry_display("jpfhir-doc-section", "300", lang) or "構造情報セクション"
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
