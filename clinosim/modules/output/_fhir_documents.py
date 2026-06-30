"""FHIR R4 DocumentReference resource builder (FA-1 documents).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.

Stage 1 default (Task 10): _bb_document_references reads record.documents
(populated by document_enricher POST_ENCOUNTER, Task 8) where
format_type='free_text' (PROGRESS_NOTE, ADMISSION_HP).

Legacy Stage 2 path (preserved for narrate subcommand): _build_document_reference
is invoked by fhir_r4_adapter.py:225-260 walk loop when narrative_docs_dir
is set via --narrative-version arg. The two paths can coexist:
  - Default run: only Stage 1 fires (record.documents path)
  - --narrative-version run: legacy walk also fires, emitting duplicate ids
    that match _bb_document_references (both use DOC_REFERENCE_ID_PREFIX +
    document_id). The FHIR writer's de-dup guard (written_ids set, first-write
    wins) prevents actual duplicates in the output file. Task 15 will
    deprecate the legacy path entirely.
"""

from __future__ import annotations

import base64
from typing import Any

from clinosim.codes import (
    get_system_uri,
)
from clinosim.codes import (
    lookup as code_lookup,
)
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document import DOC_REFERENCE_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext, _sha1_b64

__all__ = [
    "_bb_document_references",
    "_build_document_reference",
]


# === Stage 1 default: record.documents path (Task 10) ===

def _bb_document_references(ctx: BundleContext) -> list[dict[str, Any]]:
    """Bundle builder: emit DocumentReference for record.documents where format_type='free_text'.

    COMPOSITION format docs are handled by _fhir_composition.py; this builder
    skips them. QUESTIONNAIRE_RESPONSE is infrastructure-stub (Task 7) and
    not yet emitted.

    Called by _BUNDLE_BUILDERS registry (fhir_r4_adapter.py) after ImagingStudy
    and before Composition, per spec §2.2 ordering.
    """
    raw_docs = _o(ctx.record, "documents", []) or []
    patient_id = _o(_o(ctx.record, "patient", {}), "patient_id", "")
    country = ctx.country or "us"
    out: list[dict[str, Any]] = []
    for doc in raw_docs:
        if _o(doc, "format_type", "") == "free_text":
            resource = _build_dref_from_clinical_doc(doc, patient_id, country)
            if resource:
                out.append(resource)
    return out


def _build_dref_from_clinical_doc(doc: Any, patient_id: str, country: str) -> dict[str, Any] | None:
    """Build DocumentReference from Task 8 ClinicalDocument (Stage 1 path).

    Returns None if text is empty (FHIR R4 requires attachment content) or if
    loinc_code is missing (no meaningful type coding possible).
    """
    text = _o(doc, "text", "") or ""
    if not text:
        return None

    loinc_code = _o(doc, "loinc_code", "")
    if not loinc_code:
        return None

    lang = _o(doc, "language", "") or ("ja" if country.upper() == "JP" else "en")
    type_display = code_lookup("loinc", loinc_code, lang) or loinc_code

    resource_id = _o(doc, "document_id", "") or (
        f"{DOC_REFERENCE_ID_PREFIX}{_o(doc, 'encounter_id', 'unknown')}-{_o(doc, 'task_type', 'note')}"
    )

    # base64-encode the content
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

    resource: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": resource_id,
        "status": "current",
        "docStatus": "final" if _o(doc, "text_source", "none") != "template" else "preliminary",
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
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": _o(doc, "authored_datetime", "") or _o(doc, "generated_at", ""),
        "content": [
            {
                "attachment": {
                    "contentType": _o(doc, "content_type", "text/plain; charset=utf-8"),
                    "language": lang,
                    "data": encoded,
                    "title": type_display,
                    "size": len(text.encode("utf-8")),
                    "hash": _sha1_b64(text),
                }
            }
        ],
    }

    # Author (Practitioner reference)
    author_id = _o(doc, "author_practitioner_id", "")
    if author_id:
        resource["author"] = [{"reference": f"Practitioner/{author_id}"}]

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


# === LEGACY: Stage 2 narrate-walk path (preserved — Task 15 will deprecate) ===

def _build_document_reference(
    doc: dict[str, Any],
    patient_id: str,
    country: str,
) -> dict[str, Any] | None:
    """Build a FHIR R4 DocumentReference resource from a narrative CIF document.

    LEGACY path — preserved for fhir_r4_adapter.py:225-260 narrate-walk loop
    (fires only when --narrative-version / narrative_docs_dir is set).
    Task 15 will deprecate this in favour of _bb_document_references.

    The narrative CIF format is defined by ClinicalDocument in
    clinosim/types/clinical.py and written by document_generator.py.
    """

    text = doc.get("text", "") or ""
    if not text:
        # Empty stubs (Stage 1 only, no Stage 2 run) are not emitted —
        # per FHIR R4 spec, DocumentReference requires at least one
        # content.attachment, and an empty attachment would be useless
        # to downstream consumers.
        return None

    loinc_code = doc.get("loinc_code", "")
    if not loinc_code:
        return None
    lang = doc.get("language") or ("ja" if country == "JP" else "en")
    type_display = code_lookup("loinc", loinc_code, lang) or loinc_code

    # DocumentReference.id must be unique; ClinicalDocument.document_id
    # already follows doc-<encounter_id>-<task_type>[-suffix]
    resource_id = doc.get("document_id") or (
        f"doc-{doc.get('encounter_id','unknown')}-{doc.get('task_type','note')}"
    )

    # base64 encode the content
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")

    resource: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": resource_id,
        "status": "current",
        "docStatus": "final" if doc.get("text_source") != "template" else "preliminary",
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
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": doc.get("authored_datetime", "") or doc.get("generated_at", ""),
        "content": [
            {
                "attachment": {
                    "contentType": doc.get(
                        "content_type", "text/plain; charset=utf-8"
                    ),
                    "language": lang,
                    "data": encoded,
                    "title": type_display,
                    "size": len(text.encode("utf-8")),
                    "hash": _sha1_b64(text),
                }
            }
        ],
    }

    # Author (Practitioner reference)
    author_id = doc.get("author_practitioner_id", "")
    if author_id:
        resource["author"] = [{"reference": f"Practitioner/{author_id}"}]

    # Encounter context
    enc_id = doc.get("encounter_id", "")
    if enc_id:
        context: dict[str, Any] = {"encounter": [{"reference": f"Encounter/{enc_id}"}]}
        period_start = doc.get("period_start", "")
        period_end = doc.get("period_end", "")
        if period_start and period_end:
            context["period"] = {"start": period_start, "end": period_end}
        elif period_start:
            context["period"] = {"start": period_start}

        # Related procedure (for operative / procedure notes).
        # Procedure.id in the FHIR export is encounter-scoped: "<enc_id>-<base_procedure_id>"
        # (see _build_procedure). Apply the same scoping here so the reference resolves.
        related_proc = doc.get("related_procedure_id", "")
        if related_proc:
            scoped_proc_id = (
                f"{enc_id}-{related_proc}" if enc_id and not related_proc.startswith(enc_id)
                else related_proc
            )
            context["related"] = [
                {"reference": f"Procedure/{scoped_proc_id}"}
            ]
        resource["context"] = context

    return resource
