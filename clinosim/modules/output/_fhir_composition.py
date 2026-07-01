"""Composition FHIR R4 builder (Tier 1 #3 α-min-1 Task 9, extended α-min-2 Task 12).

Reads CIF record.documents where format_type='composition'. Emits one
Composition resource per matching ClinicalDocument. Section structure is
derived from ClinicalDocument.sections (dict[section_title, section_text]).

α-min-1 COMPOSITION doc types (Task 9):
  ADMISSION_HP (LOINC 34117-2), DISCHARGE_SUMMARY (LOINC 18842-5)

α-min-2 COMPOSITION doc types (Task 12 — automatically dispatched via format_type
string match; no engine code changes required):
  ADMISSION_NURSING_ASSESSMENT (LOINC 78390-2)
  NURSING_DISCHARGE_SUMMARY    (LOINC 34745-0)
  OUTPATIENT_SOAP              (LOINC 34131-3)
  ED_NOTE                      (LOINC 34878-9)

Section rendering (ClinicalDocument.sections dict → Composition.section[]) is
unchanged; TemplateNarrativeGenerator (Task 6 α-min-1 + Task 8 α-min-2) is the
source of sections dict content.

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
  sections            -> Composition.section[*] (title + text.div)

Canonical constant ownership:
- COMPOSITION_ID_PREFIX: clinosim.modules.document (writer-owner), imported here.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document import COMPOSITION_ID_PREFIX, DOC_REFERENCE_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext, _escape_html

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
    res: dict[str, Any] = {
        "resourceType": "Composition",
        "id": f"{COMPOSITION_ID_PREFIX}{enc_part}",
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
                "div": f"<div xmlns='http://www.w3.org/1999/xhtml'>{_escape_html(section_text)}</div>",
            },
        })
    if sections:
        res["section"] = sections

    return res
