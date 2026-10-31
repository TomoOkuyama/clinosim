"""JP-eCheckup General v1.7.0 Composition builder (健診結果報告書).

Extracted from ``composition.py::_build_jp_echeckup_general_composition``
(full-review Phase B4, CRITICAL C5c). Same lazy-import pattern as the
discharge-summary / eReferral splits — the builder reuses
``_build_composition_generic`` + ``_section_title_from_section_display``
from composition.py through a function-body import so module load stays
cycle-free.

The section-code matrix (3 checkup types × 2 section keys) is loaded
from ``codes/data/mhlw-echeckup-section-codes.yaml`` through the
same ``@cache`` loader that lived in composition.py; the yaml authority
is unchanged (hardcoded-review Phase A3).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.output.fhir_r4.lib.common import _escape_html

# ---------------------------------------------------------------------------
# JP-eCheckup constants (verbatim from composition.py).
# ---------------------------------------------------------------------------
_JP_ECHECKUP_GENERAL_PROFILE = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral"
_JPFHIR_ECHECKUP_SECTION_SYSTEM = "http://jpfhir.jp/fhir/eCheckup/CodeSystem/section-code"
_JPFHIR_DOC_TYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"


# ---------------------------------------------------------------------------
# Section-code matrix loader (yaml-backed; authority at
# ``codes/data/mhlw-echeckup-section-codes.yaml``, hardcoded-review A3).
# ---------------------------------------------------------------------------


@cache
def _jp_echeckup_section_code_matrix() -> dict[str, dict[str, str]]:
    """Load the jpfhir eCheckup section-code matrix from yaml."""
    path = Path(__file__).resolve().parents[5] / "codes" / "data" / "mhlw-echeckup-section-codes.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, dict[str, str]] = {}
    for checkup_type, section_map in (raw.get("sections", {}) or {}).items():
        if isinstance(section_map, dict):
            out[str(checkup_type)] = {str(k): str(v) for k, v in section_map.items()}
    return out


_JP_ECHECKUP_SECTION_CODE_MATRIX: dict[str, dict[str, str]] = _jp_echeckup_section_code_matrix()

# 既存 test 互換 alias。checkup_type 未指定時は事業者健診として dispatch。
_JP_ECHECKUP_SECTION_CODE: dict[str, str] = _JP_ECHECKUP_SECTION_CODE_MATRIX["occupational"]


def _build_jp_echeckup_general_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    *,
    roster_map: dict[str, dict] | None = None,
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
        _section_title_from_section_display,
    )

    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map)

    # meta.profile 追加
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_ECHECKUP_GENERAL_PROFILE not in profs:
        profs.append(_JP_ECHECKUP_GENERAL_PROFILE)

    # `type` field:53576-5 を doc-typecodes と LOINC 両方で emit
    disp = registry_display("jpfhir-doc-typecodes", "53576-5", lang) or "検診・健診報告書"
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "53576-5", "display": disp},
            {
                "system": get_system_uri("loinc"),
                "code": "53576-5",
                "display": registry_display("loinc", "53576-5", lang) or disp,
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
        disp_c = registry_display("jpfhir-eCheckup-section", code, lang) or key
        text_val = sections.get(key, "") or ""
        # eCheckup section entries follow the same code.text=absent /
        # title-vs-display convention as eDS / eReferral.
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
                # Chain 8: JP-CLINS pins section[*].text.status = "additional".
                "text": {
                    "status": "additional",
                    "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
                },
            }
        )
    comp["section"] = section_entries
    return comp
