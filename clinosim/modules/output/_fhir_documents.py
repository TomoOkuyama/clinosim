"""FHIR R4 DocumentReference resource builder (FA-1 documents).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import (
    get_system_uri,
)
from clinosim.codes import (
    lookup as code_lookup,
)
from clinosim.modules.output._fhir_common import _sha1_b64


def _build_document_reference(
    doc: dict[str, Any],
    patient_id: str,
    country: str,
) -> dict[str, Any] | None:
    """Build a FHIR R4 DocumentReference resource from a narrative CIF document.

    The narrative CIF format is defined by ClinicalDocument in
    clinosim/types/clinical.py and written by document_generator.py.
    """
    import base64

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
