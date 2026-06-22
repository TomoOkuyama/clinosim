"""FHIR social-history / SDOH Observation builders (AD-55 Base):
smoking status, alcohol use, JP long-term-care need level (要介護度)."""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_localization import _CATEGORY_DISPLAY_JA, _localize_display

_SMOKING_SNOMED = {"never": "266919005", "former": "8517006", "current": "449868002"}
_ALCOHOL_SNOMED = {"none": "105542008", "social": "28127009", "heavy": "86933000"}


def _social_category(country: str) -> list[dict]:
    return [{
        "coding": [{
            "system": get_system_uri("hl7-observation-category"),
            "code": "social-history",
            "display": _localize_display("Social History", country, _CATEGORY_DISPLAY_JA),
        }],
        "text": "社会歴" if country == "JP" else "Social History",
    }]


def _value(system_key: str, code: str, lang: str) -> dict[str, Any]:
    coding: dict[str, Any] = {"system": get_system_uri(system_key), "code": code}
    disp = code_lookup(system_key, code, lang)
    if disp and disp != code:
        coding["display"] = disp
    return {"coding": [coding], "text": disp or code}


def _obs(obs_id: str, country: str, loinc: str, loinc_text: str,
         value_system: str, value_code: str) -> dict[str, Any]:
    lang = "ja" if country == "JP" else "en"
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


def _build_smoking_status(ctx: BundleContext) -> list[dict]:
    status = (ctx.patient_data or {}).get("smoking_status", "")
    code = _SMOKING_SNOMED.get(status)
    if not code:
        return []
    text = "喫煙状況" if ctx.country == "JP" else "Tobacco smoking status"
    o = _obs(f"smoking-{ctx.patient_id}", ctx.country, "72166-2", text, "snomed-ct", code)
    o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
    return [o]


def _build_alcohol_use(ctx: BundleContext) -> list[dict]:
    use = (ctx.patient_data or {}).get("alcohol_use", "")
    code = _ALCOHOL_SNOMED.get(use)
    if not code:
        return []
    text = "飲酒歴" if ctx.country == "JP" else "History of alcohol use"
    o = _obs(f"alcohol-{ctx.patient_id}", ctx.country, "11331-6", text, "snomed-ct", code)
    o["subject"] = {"reference": f"Patient/{ctx.patient_id}"}
    return [o]


def _build_care_level(ctx: BundleContext) -> list[dict]:
    """JP 要介護度 (long-term-care need level) social-history Observation."""
    code = ctx.record.get("care_level") or ""
    if not code:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    text = "要介護度" if ctx.country == "JP" else "Long-term care need level"
    o: dict[str, Any] = {
        "resourceType": "Observation",
        "id": f"carelevel-{ctx.patient_id}",
        "status": "final",
        "category": _social_category(ctx.country),
        "code": {"text": text},
        "subject": {"reference": f"Patient/{ctx.patient_id}"},
        "valueCodeableConcept": _value("jp-care-level", code, lang),
    }
    return [o]
