"""FHIR R4 DocumentReference resource builder (FA-1 documents,
refactored to two-layer CIF in AD-65 Task 4).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.

Stage 1 (Task 10 / Task 15): _bb_document_references reads record.documents
(populated by document_enricher POST_ENCOUNTER, Task 8) where
format_type='free_text'. This is the sole DocumentReference emit path; the
legacy narrate-walk path was removed in Task 15 (narrate subcommand
deprecated, document_generator.py deleted).

AD-65 Task 4: the flat ClinicalDocument.text field was removed in Task 1;
content now lives at doc["narrative"]["text"], merged in by CIFReader
(Task 4) before builders run. A stub whose narrative is still None (Stage 2
narrative pass hasn't run for this doc yet) is skipped with a warning
rather than emitting an empty-attachment DocumentReference.

α-min-1 FREE_TEXT doc types (Task 10 / Task 15):
  PROGRESS_NOTE (LOINC 11506-3)

α-min-2 FREE_TEXT doc types (Task 12 — automatically dispatched via
format_type string match; no engine code changes required):
  NURSING_SHIFT_NOTE (LOINC 34746-8)
  ED_TRIAGE_NOTE     (LOINC 54094-8)

COMPOSITION format docs (ADMISSION_HP, DISCHARGE_SUMMARY, ADMISSION_NURSING_
ASSESSMENT, NURSING_DISCHARGE_SUMMARY, OUTPATIENT_SOAP, ED_NOTE) are handled
by _fhir_composition.py; this builder skips them. QUESTIONNAIRE_RESPONSE is
infrastructure-stub (Task 7) and not yet emitted.
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from clinosim.codes import (
    get_system_uri,
)
from clinosim.codes import (
    lookup as code_lookup,
)
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import resolve_lang
from clinosim.modules.document import DOC_REFERENCE_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext, _sha1_b64

logger = logging.getLogger(__name__)

__all__ = [
    "_bb_document_references",
]


# === Stage 1 default: record.documents path (Task 10) ===

def _bb_document_references(ctx: BundleContext) -> list[dict[str, Any]]:
    """Bundle builder: emit DocumentReference for record.documents where format_type='free_text'.

    COMPOSITION format docs are handled by _fhir_composition.py; this builder
    skips them. QUESTIONNAIRE_RESPONSE is infrastructure-stub (Task 7) and
    not yet emitted.

    Called by _BUNDLE_BUILDERS registry (fhir_r4_adapter.py) after ImagingStudy
    and before Composition, per spec §2.2 ordering.

    Skips (with a warning) any stub whose narrative subtree is still None —
    i.e. the Stage 2 narrative pass has not (yet) generated content for this
    document_id. This is expected for documents produced between `generate`
    and `narrate` runs, not a data-quality defect.
    """
    raw_docs = _o(ctx.record, "documents", []) or []
    patient_id = _o(_o(ctx.record, "patient", {}), "patient_id", "")
    country = ctx.country or "us"

    # C5-30 (Chain 1 close-out): pre-compute relatesTo chains. Group free-text
    # docs by (encounter_id, loinc_code) and sort by authored_datetime; each
    # DR after the first in its group `appends` the immediately-prior DR
    # (progress note day N appends day N-1; nursing record N appends N-1).
    # Requires the whole doc set up-front so it must run before per-doc emit.
    doc_id_to_prior: dict[str, str] = _build_prior_doc_chain(raw_docs)

    out: list[dict[str, Any]] = []
    for doc in raw_docs:
        if _o(doc, "format_type", "") != "free_text":
            continue
        narrative = _o(doc, "narrative", None)
        if not narrative:
            logger.warning(
                "document reference stub %s has no narrative (Stage 2 pass not "
                "run for this document) — skipping",
                _o(doc, "document_id", ""),
            )
            continue
        resource = _build_dref_from_clinical_doc(doc, narrative, patient_id, country)
        if resource:
            prior = doc_id_to_prior.get(resource["id"], "")
            if prior:
                resource["relatesTo"] = [{
                    "code": "appends",
                    "target": {"reference": f"DocumentReference/{prior}"},
                }]
            out.append(resource)
    return out


def _build_prior_doc_chain(raw_docs: list[Any]) -> dict[str, str]:
    """Return {doc_id -> immediately-prior doc_id in same (encounter, loinc) group}.

    Only free-text docs with populated narrative participate. Groups sort by
    authored_datetime ascending so a later entry `appends` an earlier one.
    """
    groups: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for doc in raw_docs:
        if _o(doc, "format_type", "") != "free_text":
            continue
        if not _o(doc, "narrative", None):
            continue
        enc_id = _o(doc, "encounter_id", "") or ""
        loinc = _o(doc, "loinc_code", "") or ""
        doc_id = _o(doc, "document_id", "") or (
            f"{DOC_REFERENCE_ID_PREFIX}{enc_id or 'unknown'}-{_o(doc, 'task_type', 'note') or 'note'}"
        )
        authored = _o(doc, "authored_datetime", "") or ""
        groups.setdefault((enc_id, loinc), []).append((authored, doc_id))

    prior: dict[str, str] = {}
    for _key, entries in groups.items():
        # Sort by authored_datetime then doc_id for deterministic tie-break.
        entries.sort(key=lambda t: (t[0] or "", t[1] or ""))
        for i in range(1, len(entries)):
            prior[entries[i][1]] = entries[i - 1][1]
    return prior


def _build_dref_from_clinical_doc(
    doc: Any, narrative: Any, patient_id: str, country: str
) -> dict[str, Any] | None:
    """Build DocumentReference from a ClinicalDocument stub + its narrative.

    ``narrative`` is the already-resolved ``doc["narrative"]`` subtree
    (extracted by ``_bb_document_references`` so this function stays
    narrative-presence agnostic and testable in isolation).

    Returns None if text is empty (FHIR R4 requires attachment content) or if
    loinc_code is missing (no meaningful type coding possible).
    """
    text = _o(narrative, "text", "") or ""
    if not text:
        return None

    loinc_code = _o(doc, "loinc_code", "")
    if not loinc_code:
        return None

    lang = _o(doc, "language", "") or resolve_lang(country)
    type_display = code_lookup("loinc", loinc_code, lang) or loinc_code

    resource_id = _o(doc, "document_id", "") or (
        f"{DOC_REFERENCE_ID_PREFIX}{_o(doc, 'encounter_id', 'unknown')}-{_o(doc, 'task_type', 'note')}"
    )

    # base64-encode the content
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

    resource: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": resource_id,
        # CY7-09 (Chain-7): DocumentReference.masterIdentifier — the
        # authoritative unique document instance identifier (FHIR R4 spec
        # recommends OID or UUID). Deterministic OID under clinosim namespace
        # so re-generation is stable (AD-16 byte-determinism).
        "masterIdentifier": {
            "system": "urn:clinosim:documentreference-master",
            "value": resource_id,
        },
        # C4-05 (session 43 cycle 4): DocumentReference.identifier 0..* for
        # cross-system document tracking (JP Core recommends). Uses the same
        # id under a clinosim namespace URI — deterministic + unique across
        # the export, mirrors Composition.identifier (C2-34).
        "identifier": [{
            "system": "urn:clinosim:documentreference-id",
            "value": resource_id,
        }],
        "status": "current",
        # Stage 1 (template) output IS production; "preliminary" would imply draft.
        # Stage 2 (LLM-augmented, β-JP-1) will re-evaluate this when llm_service is wired.
        "docStatus": "final",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": type_display,
                }
            ],
            "text": type_display,
        },
        "category": [
            {
                "coding": [
                    {
                        "system": get_system_uri("us-core-documentreference-category"),
                        "code": "clinical-note",
                        "display": "Clinical Note",
                    }
                ]
            }
        ],
        # C5-28 (session 43 cycle 5): DocumentReference.securityLabel
        # (0..* CodeableConcept). Mirrors Composition.confidentiality "N".
        # Uses HL7 v3-Confidentiality valueset (system + code).
        "securityLabel": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                        "code": "N",
                        "display": "Normal",
                    }
                ],
            }
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": _o(doc, "authored_datetime", "") or _o(narrative, "generated_at", ""),
        "content": [
            {
                "attachment": {
                    "contentType": _o(doc, "content_type", "text/plain; charset=utf-8"),
                    "language": lang,
                    "data": encoded,
                    "title": type_display,
                    "size": len(text.encode("utf-8")),
                    "hash": _sha1_b64(text),
                },
                # C4-06 (session 43 cycle 4): DocumentReference.content.format
                # 0..1 IHE XDS format code. Non-standardized here — plain-text
                # narrative in UTF-8 corresponds to IHE PCC "medical summary" =
                # "urn:ihe:iti:xds:2017:mimeTypeSufficient" (uses contentType).
                # Source: profiles.ihe.net/ITI/TF/Volume3/ch-4.2 XDS metadata
                # attribute formatCode.
                "format": {
                    "system": "urn:oid:1.3.6.1.4.1.19376.1.2.3",
                    "code": "urn:ihe:iti:xds:2017:mimeTypeSufficient",
                    "display": "MIME type sufficient (contentType is authoritative)",
                },
            }
        ],
    }

    # Author (Practitioner reference)
    author_id = _o(doc, "author_practitioner_id", "")
    if author_id:
        resource["author"] = [{"reference": f"Practitioner/{author_id}"}]

    # CY7-10 (Chain-7): DocumentReference.custodian — the managing hospital.
    # 100% of clinosim documents are custodied by hospital-main Organization.
    resource["custodian"] = {"reference": "Organization/hospital-main"}

    # Encounter context
    enc_id = _o(doc, "encounter_id", "")
    if enc_id:
        context: dict[str, Any] = {"encounter": [{"reference": f"Encounter/{enc_id}"}]}
        period_start = _o(doc, "period_start", "")
        period_end = _o(doc, "period_end", "")
        if period_start and period_end:
            context["period"] = {"start": period_start, "end": period_end}
        elif period_start:
            context["period"] = {"start": period_start}
        resource["context"] = context

    return resource


