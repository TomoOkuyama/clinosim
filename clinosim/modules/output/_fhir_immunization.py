"""FHIR R4 Immunization builder (CVX-coded adult vaccine history).

Builds FHIR Immunization resources (not Observation; resource type
distinct) from CIF ImmunizationRecord entries. Extracted from
_fhir_observations.py in PR3 (AD-55 Module Foundation Refactor final
piece). The ctx-taking builder imports the shared BundleContext from
_fhir_common, so this module never imports back through the adapter
(no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.output._fhir_common import BundleContext


def _build_immunizations(ctx: BundleContext) -> list[dict]:
    """Build FHIR Immunization resources from CIF immunizations (CVX codes, AD-30/AD-56).

    Each ImmunizationRecord in ctx.record["immunizations"] maps to one FHIR Immunization.
    Display text is resolved via lookup("cvx", code, lang); never emitted as display == code.
    US output contains no Japanese characters; JP output uses Japanese display when available.
    """
    lang = "ja" if ctx.country == "JP" else "en"
    out: list[dict] = []

    for i, imm in enumerate(ctx.record.get("immunizations") or []):
        if isinstance(imm, dict):
            cvx = imm.get("vaccine_cvx", "")
            occurrence = imm.get("occurrence_date", "")
            status = imm.get("status", "completed")
            primary_source = imm.get("primary_source", True)
        else:
            # ImmunizationRecord dataclass (in-memory path)
            cvx = getattr(imm, "vaccine_cvx", "")
            occurrence = getattr(imm, "occurrence_date", "")
            status = getattr(imm, "status", "completed")
            primary_source = getattr(imm, "primary_source", True)

        if not cvx:
            continue

        display = code_lookup("cvx", cvx, lang)
        coding: dict[str, Any] = {"system": get_system_uri("cvx"), "code": cvx}
        if display and display != cvx:
            coding["display"] = display

        vaccine_code: dict[str, Any] = {"coding": [coding]}
        if display and display != cvx:
            vaccine_code["text"] = display

        # occurrence_date may be a date object or ISO string; normalise to YYYY-MM-DD
        occ_str = occurrence.isoformat() if hasattr(occurrence, "isoformat") else str(occurrence)

        resource: dict[str, Any] = {
            "resourceType": "Immunization",
            "id": f"imm-{ctx.patient_id}-{i}",
            "status": status,
            "vaccineCode": vaccine_code,
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
            "occurrenceDateTime": occ_str,
            "primarySource": primary_source,
        }
        out.append(resource)

    return out
