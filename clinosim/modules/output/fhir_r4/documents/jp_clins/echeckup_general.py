"""JP-eCheckup General v1.7.0 Composition builder (健診結果報告書).

Extracted from ``composition.py::_build_jp_echeckup_general_composition``
(full-review Phase B4, CRITICAL C5c). Same lazy-import pattern as the
discharge-summary / eReferral splits — the builder reuses
``_build_composition_generic`` from composition.py through a function-body
import so module load stays
cycle-free.

The section-code matrix (3 checkup types × 2 section keys) is loaded
from ``codes/data/mhlw-echeckup-section-codes.yaml`` through the
same ``@cache`` loader that lived in composition.py; the yaml authority
is unchanged (hardcoded-review Phase A3).
"""

from __future__ import annotations

from functools import cache
from typing import Any

from clinosim.codes import data_table, get_system_uri
from clinosim.codes import display as registry_display
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative.registry import document_loinc
from clinosim.modules.output.fhir_r4.lib.common import _escape_html

# ---------------------------------------------------------------------------
# JP-eCheckup constants (verbatim from composition.py).
# ---------------------------------------------------------------------------
_JP_ECHECKUP_GENERAL_PROFILE = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral"
_JPFHIR_ECHECKUP_SECTION_SYSTEM = get_system_uri("jpfhir-eCheckup-section")
_JPFHIR_DOC_TYPECODES_SYSTEM = get_system_uri("jpfhir-doc-typecodes")


# ---------------------------------------------------------------------------
# Section-code matrix loader (yaml-backed; authority at
# ``codes/data/mhlw-echeckup-section-codes.yaml``, hardcoded-review A3).
# ---------------------------------------------------------------------------


@cache
def _jp_echeckup_section_code_matrix() -> dict[str, dict[str, str]]:
    """Load the jpfhir eCheckup section-code matrix from yaml."""
    raw = data_table("mhlw-echeckup-section-codes")
    out: dict[str, dict[str, str]] = {}
    for checkup_type, section_map in (raw.get("sections", {}) or {}).items():
        if isinstance(section_map, dict):
            out[str(checkup_type)] = {str(k): str(v) for k, v in section_map.items()}
    return out


@cache
def _jp_echeckup_report_codes() -> dict[str, dict[str, str]]:
    """Per checkup type, the report category and program service codes
    (``mhlw-echeckup-section-codes.yaml`` ``report_codes``, Issue #3153)."""
    raw = data_table("mhlw-echeckup-section-codes").get("report_codes") or {}
    return {str(k): {str(a): str(b) for a, b in (v or {}).items()} for k, v in raw.items()}


@cache
def _jp_echeckup_version_extension() -> dict[str, str]:
    """The composition-clinicaldocument-versionNumber extension's URL and
    value (``mhlw-echeckup-section-codes.yaml``, Issue #3153)."""
    raw = data_table("mhlw-echeckup-section-codes").get("version_extension") or {}
    return {"url": str(raw["url"]), "valueString": str(raw["value"])}


def _coded(system_key: str, code: str, lang: str) -> dict[str, Any]:
    """A one-coding CodeableConcept of ``code`` in ``system_key``."""
    display = registry_display(system_key, code, lang) or code
    return {"coding": [{"system": get_system_uri(system_key), "code": code, "display": display}], "text": display}


_JP_ECHECKUP_SECTION_CODE_MATRIX: dict[str, dict[str, str]] = _jp_echeckup_section_code_matrix()

# 既存 test 互換 alias。checkup_type 未指定時は事業者健診として dispatch。
_JP_ECHECKUP_SECTION_CODE: dict[str, str] = _JP_ECHECKUP_SECTION_CODE_MATRIX["occupational"]


def _build_jp_echeckup_general_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    country: str,
    roster_map: dict[str, dict] | None = None,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    """JP-eCheckup General v1.7.0 準拠 Composition を emit する(JP-only、opt-in)。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eCheckupGeneral]
      - type.coding[0].system = doc-typecodes(53576-5)、LOINC coding も併存
      - section は flat 2 個(事業者健診の必須 2 section:01031 検査結果、
        01032 問診結果)。section.code.system は eCheckup 固有 CodeSystem。
    """
    # Lazy imports break the composition.py ↔ echeckup_general.py cycle.
    from clinosim.modules.output.fhir_r4.documents.composition import (
        _build_composition_generic,
        _derive_section_entries,
    )

    comp = _build_composition_generic(doc, sections, lang, country=country, roster_map=roster_map)

    # meta.profile 追加
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_ECHECKUP_GENERAL_PROFILE not in profs:
        profs.append(_JP_ECHECKUP_GENERAL_PROFILE)

    # meta.lastUpdated min=1 (Issue #3153): the authored time, as for the
    # discharge summary / referral letter; omitted without one.
    if not meta.get("lastUpdated"):
        ts = comp.get("date") or _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    # Composition.extension:version min=1 (Issue #3153).
    version_ext = _jp_echeckup_version_extension()
    exts = comp.setdefault("extension", [])
    if not any(isinstance(e, dict) and e.get("url") == version_ext["url"] for e in exts):
        exts.append(dict(version_ext))

    # `type`: the profile allows one coding, doc-typecodes 53576-5 with the
    # fixed display 検診・健診報告書 (Issue #3153: the LOINC copy broke
    # type.coding max=1 and the fixed system).
    disp = registry_display("jpfhir-doc-typecodes", document_loinc("health_checkup_report"), lang) or t(
        "fhir_emit_text.checkup_report_type", "ja"
    )
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": document_loinc("health_checkup_report"), "display": disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # Composition.author 2..2 (Issue #3155): the reporting physician
    # (JP_Practitioner_eCheckupGeneral, from the generic builder) and the
    # institution (JP_Organization_eCheckupGeneral), which is also the
    # custodian — as in the IG's sample Bundle.
    authors = comp.setdefault("author", [])
    if not any(str(a.get("reference", "")).startswith("Organization/") for a in authors if isinstance(a, dict)):
        authors.append({"reference": "Organization/hospital-main"})
    comp["custodian"] = {"reference": "Organization/hospital-main"}

    # section:2 個 flat(nesting なし)
    # sub-PR-D:doc.checkup_type から健診種別を dispatch(未設定なら
    # occupational 事業者健診にfallback)
    checkup_type = _o(doc, "checkup_type", "") or "occupational"
    if checkup_type not in _JP_ECHECKUP_SECTION_CODE_MATRIX:
        checkup_type = "occupational"
    section_code_map = _JP_ECHECKUP_SECTION_CODE_MATRIX[checkup_type]

    # category (checkup-report-category) and event.code
    # (checkup-programService-code), each min=1 max=1 (Issue #3153).
    report_codes = _jp_echeckup_report_codes()[checkup_type]
    comp["category"] = [_coded("jpfhir-eCheckup-report-category", report_codes["report_category"], lang)]
    service = _coded("jpfhir-eCheckup-program-service", report_codes["program_service"], lang)
    for event in comp.get("event") or []:
        event["code"] = [service]
    section_entries: list[dict[str, Any]] = []
    for key, code in section_code_map.items():
        disp_c = registry_display("jpfhir-eCheckup-section", code, lang) or key
        text_val = sections.get(key, "") or ""
        # The eCheckup section title is fixed to the section code's display
        # itself (事業者健診検査結果セクション, Issue #3153) — unlike eDS /
        # eReferral, whose titles drop the セクション suffix.
        title_c = disp_c
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
                # Chain 8: JP-CLINS pins section[*].text.status = "additional".
                "text": {
                    "status": "additional",
                    "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
                },
            }
        )
        # Issue #3154: the results section references the checkup's
        # eCheckup Observations (composition-section-entry-types.yaml).
        refs = _derive_section_entries(key, _o(doc, "encounter_id", "") or "", encounter_index)
        if refs:
            section_entries[-1]["entry"] = refs
    comp["section"] = section_entries
    return comp
