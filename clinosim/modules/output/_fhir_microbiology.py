"""FHIR R4 microbiology builder (Specimen + Observation + DiagnosticReport).

Cultures, growth, and antibiotic susceptibilities (AD-55 microbiology
theme). Extracted from _fhir_observations.py in PR3 (AD-55 Module
Foundation Refactor final piece). The ctx-taking builder imports the
shared BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.modules.output._fhir_common import BundleContext, _micro_coding

_SUSCEPTIBILITY_DISPLAY = {
    "S": {"en": "Susceptible", "ja": "感性"},
    "I": {"en": "Intermediate", "ja": "中間"},
    "R": {"en": "Resistant", "ja": "耐性"},
}

# Canonical id prefixes for microbiology resources. Imported by readers
# (e.g. clinosim.audit.axes.clinical._organism_per_encounter) to avoid the
# silent-no-op coupling where a rename here would silently break downstream
# consumers (PR3b-3 stage-1 adversarial finding C4).
MB_ORG_ID_PREFIX = "mb-org-"
MB_SUS_ID_PREFIX = "mb-sus-"
MB_SPECIMEN_ID_PREFIX = "spec-"
MB_DR_ID_PREFIX = "dr-mb-"


def _bb_microbiology(ctx: BundleContext) -> list[dict]:
    """Microbiology cultures → Specimen + Observation(s) + DiagnosticReport (AD-55)."""
    cultures = ctx.record.get("microbiology") or []
    if not cultures:
        return []
    lang = "ja" if ctx.country == "JP" else "en"
    subject = {"reference": f"Patient/{ctx.patient_id}"}
    enc_ref = {"reference": f"Encounter/{ctx.primary_enc_id}"} if ctx.primary_enc_id else None
    lab_category = [{"coding": [{
        "system": get_system_uri("hl7-observation-category"),
        "code": "laboratory", "display": "Laboratory",
    }]}]
    out: list[dict] = []

    for i, mb in enumerate(cultures):
        base = f"{ctx.primary_enc_id or ctx.patient_id}-{i}"
        spec_id = f"{MB_SPECIMEN_ID_PREFIX}{base}"
        specimen: dict[str, Any] = {"resourceType": "Specimen", "id": spec_id, "subject": subject}
        if mb.get("specimen_snomed"):
            specimen["type"] = {"coding": [_micro_coding("snomed-ct", mb["specimen_snomed"], lang)]}
        if mb.get("collected_datetime"):
            specimen["collection"] = {"collectedDateTime": mb["collected_datetime"]}
        out.append(specimen)

        culture_loinc = mb.get("test_loinc", "")
        culture_code = ({"coding": [_micro_coding("loinc", culture_loinc, lang)]}
                        if culture_loinc else {"text": "Culture"})
        result_refs: list[dict] = []

        org_id = f"{MB_ORG_ID_PREFIX}{base}"
        org_obs: dict[str, Any] = {
            "resourceType": "Observation", "id": org_id, "status": "final",
            "category": lab_category, "code": culture_code, "subject": subject,
            "specimen": {"reference": f"Specimen/{spec_id}"},
        }
        if enc_ref:
            org_obs["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            org_obs["effectiveDateTime"] = mb["reported_datetime"]
        if mb.get("growth") and mb.get("organism_snomed"):
            org_obs["valueCodeableConcept"] = {
                "coding": [_micro_coding("snomed-ct", mb["organism_snomed"], lang)]
            }
            if mb.get("quantitation"):
                org_obs["note"] = [{"text": mb["quantitation"]}]
        else:
            org_obs["valueString"] = "発育なし" if lang == "ja" else "No growth"
        out.append(org_obs)
        result_refs.append({"reference": f"Observation/{org_id}"})

        for j, sus in enumerate(mb.get("susceptibilities") or []):
            interp = sus.get("interpretation", "")
            disp = _SUSCEPTIBILITY_DISPLAY.get(interp, {})
            sus_id = f"{MB_SUS_ID_PREFIX}{base}-{j}"
            sus_obs: dict[str, Any] = {
                "resourceType": "Observation", "id": sus_id, "status": "final",
                "category": lab_category,
                "code": {"coding": [_micro_coding("loinc", sus.get("antibiotic_loinc", ""), lang)]},
                "subject": subject,
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "valueCodeableConcept": {"coding": [{
                    "system": get_system_uri("hl7-observation-interpretation"),
                    "code": interp,
                    "display": disp.get(lang, disp.get("en", interp)),
                }]},
            }
            if enc_ref:
                sus_obs["encounter"] = enc_ref
            out.append(sus_obs)
            result_refs.append({"reference": f"Observation/{sus_id}"})

        report: dict[str, Any] = {
            "resourceType": "DiagnosticReport", "id": f"{MB_DR_ID_PREFIX}{base}", "status": "final",
            "category": [{"coding": [{
                "system": get_system_uri("hl7-diagnostic-service-section"),
                "code": "MB", "display": "Microbiology",
            }]}],
            "code": culture_code, "subject": subject,
            "specimen": [{"reference": f"Specimen/{spec_id}"}],
            "result": result_refs,
        }
        if enc_ref:
            report["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            report["effectiveDateTime"] = mb["reported_datetime"]
        out.append(report)

    return out
