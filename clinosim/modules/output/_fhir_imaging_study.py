"""ImagingStudy FHIR R4 builder (Tier 1 #2 PR1).

Reads CIF extensions['imaging']: list[ImagingStudyRecord]. Emits one
ImagingStudy resource per Record. References ServiceRequest (via basedOn),
Endpoint (via endpoint[]), Encounter, Patient.

No-drop invariant: every populated CIF field maps to a FHIR target
(spec Section 3.4 matrix):
  study_id             -> ImagingStudy.id (imgst- prefix)
  study_instance_uid   -> ImagingStudy.identifier[0] (urn:dicom:uid)
  encounter_id         -> ImagingStudy.encounter
  patient_id           -> ImagingStudy.subject
  order_id             -> ImagingStudy.basedOn[ServiceRequest]
  status               -> ImagingStudy.status
  started_datetime     -> ImagingStudy.started
  modality_code        -> ImagingStudy.modality[0] (DCM system)
  series[*]            -> ImagingStudy.series[*]
  endpoint_id          -> ImagingStudy.endpoint[Endpoint]
  report               -> DiagnosticReport (Task 6 builder)

Canonical constant ownership:
- IMAGING_STUDY_ID_PREFIX, ENDPOINT_ID_PREFIX: engine.py (writer-owner),
  imported here for use + re-export (silent-no-op defense Layer 2).
- SR_ID_PREFIX: _fhir_service_request.py (writer-owner), imported for
  basedOn reference construction.
- DICOM_UID_SYSTEM: defined here (FHIR/DICOM standard constant).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.imaging.engine import (  # canonical owners; re-exported below
    ENDPOINT_ID_PREFIX,
    IMAGING_STUDY_ID_PREFIX,
    load_modalities,
)
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_service_request import SR_ID_PREFIX  # canonical owner

# Writer-owned constant — DICOM/FHIR standard URI for DICOM Study UID.
DICOM_UID_SYSTEM = "urn:dicom:uid"

# Re-export so readers can import from this module or the canonical owner.
__all__ = [
    "IMAGING_STUDY_ID_PREFIX",
    "ENDPOINT_ID_PREFIX",
    "DICOM_UID_SYSTEM",
    "_bb_imaging_studies",
]


def _isoformat_or_str(dt: Any) -> str:
    """Convert datetime to ISO-8601 string; passthrough for str; empty for None."""
    if dt is None:
        return ""
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


def _bb_imaging_studies(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one ImagingStudy per ImagingStudyRecord in extensions['imaging']."""
    studies = (_o(ctx.record, "extensions", {}) or {}).get("imaging") or []
    if not studies:
        return []
    lang = "ja" if ctx.country.lower() == "jp" else "en"
    return [_build_imaging_study(s, lang) for s in studies]


def _build_imaging_study(study: Any, lang: str) -> dict[str, Any]:
    """Build one FHIR R4 ImagingStudy resource from an ImagingStudyRecord."""
    modalities = load_modalities()
    modality_code = _o(study, "modality_code", "")
    mod_def = modalities.get(modality_code, {})
    modality_display = mod_def.get(f"display_{lang}") or mod_def.get("display_en", modality_code)

    series_list = _o(study, "series", []) or []
    series_resources = [_build_series(s, lang) for s in series_list]
    total_instances = sum(_o(s, "instance_count", 0) for s in series_list)

    res: dict[str, Any] = {
        "resourceType": "ImagingStudy",
        "id": f"{IMAGING_STUDY_ID_PREFIX}{_o(study, 'study_id', '')}",
        "identifier": [{
            "system": DICOM_UID_SYSTEM,
            "value": f"urn:oid:{_o(study, 'study_instance_uid', '')}",
        }],
        "status": _o(study, "status", "available"),
        "modality": [{
            "system": get_system_uri("dicom-modality"),
            "code": modality_code,
            "display": modality_display,
        }],
        "subject": {"reference": f"Patient/{_o(study, 'patient_id', '')}"},
        "encounter": {"reference": f"Encounter/{_o(study, 'encounter_id', '')}"},
        "basedOn": [{"reference": f"ServiceRequest/{SR_ID_PREFIX}{_o(study, 'order_id', '')}"}],
        "endpoint": [{"reference": f"Endpoint/{_o(study, 'endpoint_id', '')}"}],
        "numberOfSeries": len(series_resources),
        "numberOfInstances": total_instances,
        "series": series_resources,
    }
    started = _isoformat_or_str(_o(study, "started_datetime", None))
    if started:
        res["started"] = started
    return res


def _build_series(series: Any, lang: str) -> dict[str, Any]:
    """Build one FHIR R4 ImagingStudy.series element from an ImagingSeries."""
    snomed_system = get_system_uri("snomed-ct")
    body_site_snomed = _o(series, "body_site_snomed", "")
    # Resolve body site display via code registry; fall back to CIF display field.
    body_site_display = code_lookup("snomed-ct", body_site_snomed, lang) or _o(
        series, "body_site_display", "",
    )
    modalities = load_modalities()
    modality_code = _o(series, "modality_code", "")
    mod_def = modalities.get(modality_code, {})
    modality_display = mod_def.get(f"display_{lang}") or mod_def.get("display_en", modality_code)
    return {
        "uid": _o(series, "series_uid", ""),
        "number": _o(series, "series_number", 1),
        "modality": {
            "system": get_system_uri("dicom-modality"),
            "code": modality_code,
            "display": modality_display,
        },
        "numberOfInstances": _o(series, "instance_count", 0),
        "description": _o(series, "description", ""),
        "bodySite": {
            "system": snomed_system,
            "code": body_site_snomed,
            "display": body_site_display,
        },
    }
