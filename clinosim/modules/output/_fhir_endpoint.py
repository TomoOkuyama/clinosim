"""Endpoint FHIR R4 builder (Tier 1 #2 PR1).

One Endpoint per ImagingStudyRecord (1:1 invariant). Endpoint.address is a
WADO-RS placeholder URL (clinosim/config/hospital_*.yaml imaging.wado_base_url
overridable). Future image-gen AI integration: substitute address with real
PACS / DICOMweb endpoint URL; ImagingStudy.identifier (urn:dicom:uid) is the
canonical lookup key.

Canonical constant ownership:
- ENDPOINT_ID_PREFIX: engine.py (writer-owner), imported here for re-export
  so readers can do ``from _fhir_endpoint import ENDPOINT_ID_PREFIX`` or
  ``from engine import ENDPOINT_ID_PREFIX`` — both resolve the same string
  without duplication (silent-no-op defense Layer 2).
- DICOM_WADO_RS_CONNECTION_TYPE: defined here (only used by this builder).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.imaging.engine import ENDPOINT_ID_PREFIX
from clinosim.modules.output._fhir_common import BundleContext

# Writer-owned constant — unique to Endpoint builder, not in engine.py.
DICOM_WADO_RS_CONNECTION_TYPE = "dicom-wado-rs"

_DEFAULT_WADO_BASE_URL = "https://wado.clinosim.example/dicomweb"

# Re-export so readers can import from either owner or this module.
__all__ = [
    "ENDPOINT_ID_PREFIX",
    "DICOM_WADO_RS_CONNECTION_TYPE",
    "_bb_endpoints",
    "_resolve_wado_base_url",
]


def _resolve_wado_base_url(hospital_config: dict) -> str:
    """Resolve WADO-RS base URL from hospital_config; fallback to placeholder."""
    imaging_cfg = hospital_config.get("imaging") or {}
    return imaging_cfg.get("wado_base_url") or _DEFAULT_WADO_BASE_URL


def _bb_endpoints(ctx: BundleContext) -> list[dict[str, Any]]:
    """Emit one Endpoint per ImagingStudyRecord in extensions['imaging'].

    Stub-only studies (inference failed; ``endpoint_id == ""``, session 48
    case D) carry no PACS reference — skip them instead of emitting an
    Endpoint with an empty ``id`` (invalid for Bulk Data NDJSON and breaks
    Resource.id uniqueness).
    """
    studies = (_o(ctx.record, "extensions", {}) or {}).get("imaging") or []
    if not studies:
        return []
    base_url = _resolve_wado_base_url(getattr(ctx, "hospital_config", {}) or {})
    return [
        _build_endpoint(s, base_url)
        for s in studies
        if _o(s, "endpoint_id", "")
    ]


def _build_endpoint(study: Any, base_url: str) -> dict[str, Any]:
    """Build one FHIR R4 Endpoint resource from an ImagingStudyRecord."""
    study_uid = _o(study, "study_instance_uid", "")
    return {
        "resourceType": "Endpoint",
        "id": _o(study, "endpoint_id", ""),
        "status": "active",
        "connectionType": {
            "system": get_system_uri("hl7-endpoint-connection-type"),
            "code": DICOM_WADO_RS_CONNECTION_TYPE,
            "display": code_lookup("hl7-endpoint-connection-type", DICOM_WADO_RS_CONNECTION_TYPE, "en"),
        },
        "payloadType": [{
            "coding": [{
                "system": get_system_uri("hl7-endpoint-payload-type"),
                "code": "any",
                "display": code_lookup("hl7-endpoint-payload-type", "any", "en"),
            }],
        }],
        "payloadMimeType": ["application/dicom"],
        "address": f"{base_url}/studies/{study_uid}",
    }
