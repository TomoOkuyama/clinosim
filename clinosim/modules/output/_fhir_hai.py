"""FHIR R4 HAI Condition builder (AD-55 Module: hai, PR-B).

Reads list[HAIEvent] from ctx.record.extensions["hai"] and emits one
Condition per HAI. Cultures are emitted by the existing
_fhir_microbiology.py builder via record.microbiology (no overlap).
Dual coding: US uses ICD-10-CM billable; JP uses WHO ICD-10 4-char
via existing code_mapping_diagnosis/jp.yaml; SNOMED international
common to both. The ctx-taking builder imports the shared
BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""
from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key, resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, _map_diagnosis_code


def _extensions_hai_list(ctx: BundleContext) -> list:
    ext = get_attr_or_key(ctx.record, "extensions", {}) or {}
    return ext.get("hai", []) or []


def _build_hai_conditions(ctx: BundleContext) -> list[dict]:
    """Build FHIR Condition resources from CIF extensions['hai']."""
    hais = _extensions_hai_list(ctx)
    if not hais:
        return []
    country = ctx.country
    lang = resolve_lang(country)
    out: list[dict] = []
    for h in hais:
        icd_internal = get_attr_or_key(h, "icd10_code", "")
        snomed = get_attr_or_key(h, "snomed_code", "")
        hai_id = get_attr_or_key(h, "hai_id", "")
        enc_id = get_attr_or_key(h, "encounter_id", "")
        onset_date = get_attr_or_key(h, "onset_date", "")
        if not icd_internal or not hai_id:
            continue
        icd_country = _map_diagnosis_code(icd_internal, country)
        icd_sys_key = "icd-10-cm" if country == "US" else "icd-10"
        icd_disp = code_lookup(icd_sys_key, icd_country, lang) or ""
        snomed_disp = code_lookup("snomed-ct", snomed, lang) or ""
        coding: list[dict[str, Any]] = [{
            "system": get_system_uri(icd_sys_key),
            "code": icd_country,
            "display": icd_disp,
        }]
        if snomed:
            coding.append({
                "system": get_system_uri("snomed-ct"),
                "code": snomed,
                "display": snomed_disp,
            })
        resource: dict[str, Any] = {
            "resourceType": "Condition",
            "id": hai_id,
            "clinicalStatus": {"coding": [{
                "system": get_system_uri("hl7-condition-clinical"),
                "code": "active",
            }]},
            "verificationStatus": {"coding": [{
                "system": get_system_uri("hl7-condition-verification"),
                "code": "confirmed",
            }]},
            "category": [{"coding": [{
                "system": get_system_uri("hl7-condition-category"),
                "code": "encounter-diagnosis",
            }]}],
            "code": {"coding": coding, "text": icd_disp or snomed_disp},
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
            "encounter": {"reference": f"Encounter/{enc_id}"},
            "onsetDateTime": onset_date,
        }
        out.append(resource)
    return out
