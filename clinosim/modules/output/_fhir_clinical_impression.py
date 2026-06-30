"""ClinicalImpression FHIR R4 builder (Tier 1 #3 α-min-1 Task 9).

Reads CIF record.extensions["clinical_impressions"]: list[ClinicalImpressionRecord].
Emits one ClinicalImpression resource per record.

No-drop invariant (CIF → FHIR):
  impression_id        -> ClinicalImpression.id (ci- prefix)
  encounter_id         -> ClinicalImpression.encounter
  patient_id (from ctx) -> ClinicalImpression.subject
  date                 -> ClinicalImpression.effectiveDateTime
  description          -> ClinicalImpression.description
  summary              -> ClinicalImpression.summary
  investigation_refs[] -> ClinicalImpression.investigation[].item[]
  finding_refs[]       -> ClinicalImpression.finding[].itemReference
  prognosis            -> ClinicalImpression.prognosisCodeableConcept[].text
  practitioner_id      -> ClinicalImpression.assessor

Canonical constant ownership:
- CLINICAL_IMPRESSION_ID_PREFIX: clinosim.modules.document (writer-owner), imported here.
"""

from __future__ import annotations

from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document import CLINICAL_IMPRESSION_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext

__all__ = [
    "CLINICAL_IMPRESSION_ID_PREFIX",
    "_bb_clinical_impressions",
]


def _bb_clinical_impressions(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one ClinicalImpression per entry in extensions['clinical_impressions']."""
    ext = _o(ctx.record, "extensions", {}) or {}
    impressions = _o(ext, "clinical_impressions", []) or []
    if not impressions:
        return []
    return [_build_clinical_impression(imp, ctx.patient_id) for imp in impressions]


def _build_clinical_impression(imp: Any, patient_id: str) -> dict[str, Any]:
    """Build one FHIR R4 ClinicalImpression from a ClinicalImpressionRecord."""
    impression_id = _o(imp, "impression_id", "") or ""
    encounter_id = _o(imp, "encounter_id", "") or ""
    date_val = _o(imp, "date", None)
    description = _o(imp, "description", "") or ""
    summary = _o(imp, "summary", "") or ""
    investigation_refs = _o(imp, "investigation_refs", []) or []
    finding_refs = _o(imp, "finding_refs", []) or []
    prognosis = _o(imp, "prognosis", "") or ""
    practitioner_id = _o(imp, "practitioner_id", "") or ""

    # date → ISO string
    if date_val is not None and hasattr(date_val, "isoformat"):
        effective_dt = date_val.isoformat()
    elif date_val is not None:
        effective_dt = str(date_val)
    else:
        effective_dt = ""

    res: dict[str, Any] = {
        "resourceType": "ClinicalImpression",
        "id": impression_id if impression_id.startswith(CLINICAL_IMPRESSION_ID_PREFIX) else f"{CLINICAL_IMPRESSION_ID_PREFIX}{impression_id}",
        "status": "completed",
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    if encounter_id:
        res["encounter"] = {"reference": f"Encounter/{encounter_id}"}
    if effective_dt:
        res["effectiveDateTime"] = effective_dt
    if description:
        res["description"] = description
    if summary:
        res["summary"] = summary
    if practitioner_id:
        res["assessor"] = {"reference": f"Practitioner/{practitioner_id}"}

    # investigation: group observation refs into a single investigation item
    if investigation_refs:
        res["investigation"] = [{
            "code": {"text": "Investigations"},
            "item": [{"reference": f"Observation/{ref}"} for ref in investigation_refs],
        }]

    # finding: one entry per condition ref
    if finding_refs:
        res["finding"] = [
            {"itemReference": {"reference": f"Condition/{ref}"}}
            for ref in finding_refs
        ]

    if prognosis:
        res["prognosisCodeableConcept"] = [{"text": prognosis}]

    return res
