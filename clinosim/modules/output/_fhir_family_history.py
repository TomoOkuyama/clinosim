"""FHIR FamilyMemberHistory builder (AD-55 Base, AD-56 builder registry)."""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.family_history.engine import load_reference
from clinosim.modules.output._fhir_common import BundleContext, _build_diagnosis_codeable_concept


def _build_family_history(ctx: BundleContext) -> list[dict]:
    """Build FHIR FamilyMemberHistory from CIF family_history (v3-RoleCode + ICD).

    One resource per relative; patient-scoped id so the write-time de-dup keeps a
    single copy across the patient's encounters. FamilyMemberHistory.sex is omitted
    (optional) to avoid a hardcoded gender system URI.
    """
    fams = ctx.record.get("family_history") or []
    if not fams:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    icd_system_key = "icd-10" if ctx.country == "JP" else "icd-10-cm"
    rel_display = load_reference()["relationships"]
    out: list[dict] = []
    for i, fam in enumerate(fams):
        rel = _get(fam, "relationship", "")
        disp = rel_display.get(rel, {})
        res: dict[str, Any] = {
            "resourceType": "FamilyMemberHistory",
            "id": f"fmh-{ctx.patient_id}-{i:02d}",
            "status": "completed",
            "patient": {"reference": f"Patient/{ctx.patient_id}"},
            "relationship": {"coding": [{
                "system": get_system_uri("hl7-v3-rolecode"),
                "code": rel,
                "display": disp.get(lang, disp.get("en", rel)),
            }]},
            "deceasedBoolean": bool(_get(fam, "deceased", False)),
        }
        conditions = [
            {"code": _build_diagnosis_codeable_concept(code, icd_system_key, ctx.country)}
            for code in _get(fam, "condition_codes", []) or []
        ]
        if conditions:
            res["condition"] = conditions
        out.append(res)
    return out
