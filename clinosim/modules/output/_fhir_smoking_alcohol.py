"""FHIR smoking_status + alcohol_use social-history Observation builders.

AD-55 Base. Reads enum→SNOMED + LOINC reference data from
clinosim/modules/sdoh/reference_data/social_history.yaml via
load_social_history(). Display strings resolved via
clinosim.codes.lookup("snomed-ct", code, lang) (the _value helper in
_fhir_common does this).

Split out of the former _fhir_sdoh.py (PR2 G2 SDOH integrity refactor,
2026-06-24) so that each SDOH topic family has its own builder file —
care_level (JP-only) is in _fhir_care_level.py; future SDOH topics
(occupation/education/housing) get their own files following this pattern.
"""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _social_category,
    _value,
)
from clinosim.modules.sdoh import load_social_history


def _obs(obs_id: str, country: str, loinc: str, loinc_text: str,
         value_system: str, value_code: str) -> dict[str, Any]:
    """LOINC-keyed social-history Observation skeleton.

    Local helper (not promoted to _fhir_common) because the LOINC-keyed
    pattern is specific to standardized SDOH observations like smoking
    and alcohol — care_level uses a custom JP code system and has a
    different shape, so promoting this would be premature.
    """
    lang = resolve_lang(country)
    return {
        "resourceType": "Observation",
        "id": obs_id,
        "status": "final",
        "category": _social_category(country),
        "code": {"coding": [{"system": get_system_uri("loinc"), "code": loinc,
                             "display": code_lookup("loinc", loinc, "en")}],
                 "text": loinc_text},
        "valueCodeableConcept": _value(value_system, value_code, lang),
    }


def _sdoh_effective_datetime(ctx: BundleContext) -> str:
    """Return the effectiveDateTime string for a patient-level SDOH Observation.

    C1-12 (session 41 cycle 1) fix: US Core and JP Core social-history
    profiles list effective[x] as MUST-SUPPORT. Base FHIR R4 allows
    omission, but interop degrades. Use the patient's earliest encounter
    admission date as the SDOH-as-of proxy (the SDOH was assessed at
    that visit). Empty string when the record carries no encounter.
    """
    from clinosim.modules._shared import get_attr_or_key as _o
    from clinosim.modules.output._fhir_common import to_fhir_datetime
    encs = _o(ctx.record, "encounters", []) or []
    if not encs:
        return ""
    # earliest admission_datetime
    starts = []
    for e in encs:
        v = _o(e, "admission_datetime", None)
        if v:
            starts.append(v)
    if not starts:
        return ""
    starts.sort()
    return to_fhir_datetime(starts[0])


def _build_smoking_status(ctx: BundleContext) -> list[dict]:
    data = load_social_history()["smoking_status"]
    status = (ctx.patient_data or {}).get("smoking_status", "")
    entry = data["values"].get(status)
    if not entry:
        return []
    text = "喫煙状況" if is_jp(ctx.country) else "Tobacco smoking status"
    o = _obs(f"smoking-{ctx.patient_id}", ctx.country, data["loinc"], text,
             "snomed-ct", entry["snomed"])
    o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
    eff = _sdoh_effective_datetime(ctx)
    if eff:
        o["effectiveDateTime"] = eff
    return [o]


def _build_alcohol_use(ctx: BundleContext) -> list[dict]:
    data = load_social_history()["alcohol_use"]
    use = (ctx.patient_data or {}).get("alcohol_use", "")
    entry = data["values"].get(use)
    if not entry:
        return []
    text = "飲酒歴" if is_jp(ctx.country) else "History of alcohol use"
    o = _obs(f"alcohol-{ctx.patient_id}", ctx.country, data["loinc"], text,
             "snomed-ct", entry["snomed"])
    o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
    eff = _sdoh_effective_datetime(ctx)
    if eff:
        o["effectiveDateTime"] = eff
    return [o]
