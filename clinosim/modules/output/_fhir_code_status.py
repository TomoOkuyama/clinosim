"""FHIR code-status (resuscitation status) Observation builder (AD-55 Base)."""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.code_status.engine import load_reference
from clinosim.modules.output._fhir_common import BundleContext, _survey_category


def _build_code_status(ctx: BundleContext) -> list[dict]:
    code = ctx.record.get("code_status") or ""
    if not code:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    enc = ctx.primary_enc_id
    observable = load_reference()["observable_snomed"]
    snomed_uri = get_system_uri("snomed-ct")

    def _coding(c: str) -> dict[str, Any]:
        d: dict[str, Any] = {"system": snomed_uri, "code": c}
        disp = code_lookup("snomed-ct", c, lang)
        if disp and disp != c:
            d["display"] = disp
        return d

    encs = ctx.record.get("encounters") or []
    admit = encs[0].get("admission_datetime") if encs else None
    obs: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"codestatus-{enc or ctx.patient_id}",
        "status": "final",
        "category": _survey_category(),
        "code": {"coding": [_coding(observable)]},
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        "valueCodeableConcept": {"coding": [_coding(code)]},
    }
    if enc:
        obs["encounter"] = {"reference": f"Encounter/{enc}"}
    if isinstance(admit, str):
        obs["effectiveDateTime"] = admit
    return [obs]
