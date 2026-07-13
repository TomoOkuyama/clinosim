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

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key, resolve_lang
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _coding_with_display,
    _map_diagnosis_code,
)


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
        icd_sys_key = system_key_for("diagnosis", country)
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
            # C2-02/03 (session 42): use _coding_with_display so status displays
            # are populated from codes/data/hl7-condition-{clinical,ver-status}.yaml.
            # Also fixes wrong system key `hl7-condition-verification` (never
            # registered; canonical URI ends in `condition-ver-status`).
            "clinicalStatus": {"coding": [
                _coding_with_display("hl7-condition-clinical", "active",
                                     resolve_lang(ctx.country))]},
            "verificationStatus": {"coding": [
                _coding_with_display("hl7-condition-ver-status", "confirmed",
                                     resolve_lang(ctx.country))]},
            "category": [{"coding": [{
                "system": get_system_uri("hl7-condition-category"),
                "code": "encounter-diagnosis",
            }]}],
            "code": {"coding": coding, "text": icd_disp or snomed_disp},
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
            "encounter": {"reference": f"Encounter/{enc_id}"},
            "onsetDateTime": onset_date,
        }
        # CY8-21/22 polish (session 48 cycle 8): HAI Condition にも recorder /
        # asserter を emit(hospital-main の感染管理チーム相当)。encounter に
        # attending が居れば優先、無ければ hospital-main を fallback。
        _att = ""
        for _enc in ctx.record.get("encounters", []) or []:
            if (_enc.get("encounter_id") if isinstance(_enc, dict)
                else getattr(_enc, "encounter_id", "")) == enc_id:
                _att = (_enc.get("attending_physician_id") if isinstance(_enc, dict)
                        else getattr(_enc, "attending_physician_id", "")) or ""
                break
        if _att:
            resource["recorder"] = {"reference": f"Practitioner/{_att}"}
            resource["asserter"] = {"reference": f"Practitioner/{_att}"}
        else:
            resource["recorder"] = {"reference": "Practitioner/DR-IM-001"}
            resource["asserter"] = {"reference": "Practitioner/DR-IM-001"}
        out.append(resource)
    return out
