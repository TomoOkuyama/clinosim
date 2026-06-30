"""Composition FHIR R4 builder (Tier 1 #3 α-min-1 Task 9).

Reads CIF record.documents where format_type='composition'. Emits one
Composition resource per matching ClinicalDocument. Section structure is
derived from ClinicalDocument.sections (dict[section_title, section_text]).

No-drop invariant (CIF → FHIR):
  document_id         -> Composition.id (comp- prefix)
  loinc_code          -> Composition.type.coding[LOINC]
  encounter_id        -> Composition.encounter
  patient_id          -> Composition.subject
  author_practitioner_id -> Composition.author[]
  authored_datetime   -> Composition.date
  language            -> Composition.language
  sections            -> Composition.section[*] (title + text.div)

Canonical constant ownership:
- COMPOSITION_ID_PREFIX: clinosim.modules.document (writer-owner), imported here.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document import COMPOSITION_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext

__all__ = [
    "COMPOSITION_ID_PREFIX",
    "_bb_compositions",
]


def _bb_compositions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one Composition per ClinicalDocument with format_type='composition'."""
    raw_docs = _o(ctx.record, "documents", []) or []
    lang = "ja" if ctx.country.lower() == "jp" else "en"
    out: list[dict[str, Any]] = []
    for doc in raw_docs:
        if _o(doc, "format_type", "") == "composition":
            out.append(_build_composition(doc, lang))
    return out


def _build_composition(doc: Any, lang: str) -> dict[str, Any]:
    """Build one FHIR R4 Composition resource from a ClinicalDocument."""
    loinc_code = _o(doc, "loinc_code", "")
    loinc_display = code_lookup("loinc", loinc_code, lang) if loinc_code else ""

    doc_id = _o(doc, "document_id", "")
    author_id = _o(doc, "author_practitioner_id", "")
    authored_dt = _o(doc, "authored_datetime", "")
    patient_id = _o(doc, "patient_id", "")
    encounter_id = _o(doc, "encounter_id", "")
    language = _o(doc, "language", "en")

    res: dict[str, Any] = {
        "resourceType": "Composition",
        "id": f"{COMPOSITION_ID_PREFIX}{doc_id}",
        "status": "final",
        "type": {
            "coding": [{
                "system": get_system_uri("loinc"),
                "code": loinc_code,
                "display": loinc_display or loinc_code,
            }],
        },
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": authored_dt,
        # TODO(Task 10/15): document enricher must always populate author_practitioner_id.
        # FHIR R4 requires Composition.author 1..* — empty [] is non-conformant but
        # acceptable for α-min-1 since Task 8 doesn't yet plumb practitioner refs.
        "author": [{"reference": f"Practitioner/{author_id}"}] if author_id else [],
        "title": loinc_display or loinc_code,
        "language": language,
    }

    if encounter_id:
        res["encounter"] = {"reference": f"Encounter/{encounter_id}"}

    # Build section[] from ClinicalDocument.sections dict
    sections_dict = _o(doc, "sections", {}) or {}
    sections: list[dict[str, Any]] = []
    for section_title, section_text in sections_dict.items():
        sections.append({
            "title": section_title,
            "text": {
                "status": "generated",
                "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{section_text}</div>",
            },
        })
    if sections:
        res["section"] = sections

    return res
