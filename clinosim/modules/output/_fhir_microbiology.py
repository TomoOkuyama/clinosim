"""FHIR R4 microbiology builder (Specimen + Observation + DiagnosticReport).

Cultures, growth, and antibiotic susceptibilities (AD-55 microbiology
theme). Extracted from _fhir_observations.py in PR3 (AD-55 Module
Foundation Refactor final piece). The ctx-taking builder imports the
shared BundleContext from _fhir_common, so this module never imports back
through the adapter (no cycle).
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri, system_key_for
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, _micro_coding
from clinosim.modules.output._fhir_localization import localize_fixed_label

# Canonical id prefixes for microbiology resources. Imported by readers
# (e.g. clinosim.audit.axes.clinical._organism_per_encounter) to avoid the
# silent-no-op coupling where a rename here would silently break downstream
# consumers (PR3b-3 stage-1 adversarial finding C4).
MB_ORG_ID_PREFIX = "mb-org-"
MB_SUS_ID_PREFIX = "mb-sus-"
MB_SPECIMEN_ID_PREFIX = "spec-"
MB_DR_ID_PREFIX = "dr-mb-"

# Canonical URI for HAI event cross-reference identifiers (PR3b-5,
# 2026-06-29). Emitted on Specimen + mb-org-*/mb-sus-* Observation +
# DiagnosticReport when MicrobiologyResult.hai_event_id is non-empty.
# Internal-only — clinosim simulator cross-reference, not registered in
# JP Core / US Core / HL7 IGs. Uses `urn:clinosim:...` convention
# matching the existing internal identifier in _fhir_practitioner.py
# (`urn:clinosim:staff`) — adversarial-1 finding consolidated the
# convention to urn-form to avoid two parallel patterns. Audit reader
# (clinosim.audit.axes.clinical) imports this same constant; a rename
# here triggers ImportError downstream rather than a silent gate skip
# (same defense pattern as MB_ORG_ID_PREFIX and ABX_ORDER_ID_PREFIX).
HAI_EVENT_ID_SYSTEM = "urn:clinosim:identifier:hai-event-id"


def resolve_culture_code(specimen: str, test_loinc: str, country: str) -> tuple[str, str]:
    """Resolve (code_value, code_system_key) for a microbiology culture test.

    Country-gated: JP resolves via code_mapping_microbiology.yaml when the
    specimen is mapped (currently all of blood/urine/sputum/wound -> jlac10
    6B010); otherwise falls back to the raw `test_loinc` value tagged as
    loinc (never tag a LOINC-shaped fallback under the country's mapped
    system — that would produce an incoherent coding).

    Single source of truth for this resolution — consumed by both the FHIR
    builder (_bb_microbiology, below) and csv_adapter.py, so both outputs
    stay consistent (TODO.md 2026-07-04).
    """
    country_code = "JP" if is_jp(country) else "US"
    code_map = load_code_mapping("microbiology", country_code)
    if specimen in code_map:
        return code_map[specimen], system_key_for("microbiology", country_code)
    return test_loinc, "loinc"


def resolve_susceptibility_code(antibiotic_loinc: str, country: str) -> tuple[str, str]:
    """Resolve (code_value, code_system_key) for a drug susceptibility test.

    Country-gated: JP resolves via code_mapping_microbiology_susceptibility.yaml
    when the antibiotic_loinc is mapped (currently all 10 known antibiotics ->
    jlac10 6C010); otherwise falls back to the raw `antibiotic_loinc` value
    tagged as loinc (same coherent-fallback rule as resolve_culture_code).

    Single source of truth for this resolution — consumed by both the FHIR
    builder (_bb_microbiology, below) and csv_adapter.py.
    """
    country_code = "JP" if is_jp(country) else "US"
    code_map = load_code_mapping("microbiology_susceptibility", country_code)
    if antibiotic_loinc in code_map:
        return code_map[antibiotic_loinc], system_key_for("microbiology", country_code)
    return antibiotic_loinc, "loinc"


def _bb_microbiology(ctx: BundleContext) -> list[dict]:
    """Microbiology cultures → Specimen + Observation(s) + DiagnosticReport (AD-55)."""
    cultures = ctx.record.get("microbiology") or []
    if not cultures:
        return []
    lang = resolve_lang(ctx.country)
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
        # PR3b-5: build identifier list once per culture; empty when not HAI.
        hai_event_id = mb.get("hai_event_id", "")
        hai_identifier = (
            [{"system": HAI_EVENT_ID_SYSTEM, "value": hai_event_id}]
            if hai_event_id else []
        )
        specimen: dict[str, Any] = {"resourceType": "Specimen", "id": spec_id, "subject": subject}
        if hai_identifier:
            specimen["identifier"] = hai_identifier
        if mb.get("specimen_snomed"):
            specimen["type"] = {"coding": [_micro_coding("snomed-ct", mb["specimen_snomed"], lang)]}
        if mb.get("collected_datetime"):
            specimen["collection"] = {"collectedDateTime": mb["collected_datetime"]}
        out.append(specimen)

        culture_code_value, code_system = resolve_culture_code(
            mb.get("specimen", ""), mb.get("test_loinc", ""), ctx.country
        )
        culture_code = ({"coding": [_micro_coding(code_system, culture_code_value, lang)]}
                        if culture_code_value else {"text": "Culture"})
        result_refs: list[dict] = []

        org_id = f"{MB_ORG_ID_PREFIX}{base}"
        org_obs: dict[str, Any] = {
            "resourceType": "Observation", "id": org_id, "status": "final",
            "category": lab_category, "code": culture_code, "subject": subject,
            "specimen": {"reference": f"Specimen/{spec_id}"},
        }
        if hai_identifier:
            org_obs["identifier"] = hai_identifier
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
            org_obs["valueString"] = localize_fixed_label("No growth", ctx.country)
        out.append(org_obs)
        result_refs.append({"reference": f"Observation/{org_id}"})

        for j, sus in enumerate(mb.get("susceptibilities") or []):
            interp = sus.get("interpretation", "")
            sus_id = f"{MB_SUS_ID_PREFIX}{base}-{j}"
            antibiotic_loinc = sus.get("antibiotic_loinc", "")
            sus_code_value, sus_code_system = resolve_susceptibility_code(
                antibiotic_loinc, ctx.country
            )
            sus_obs: dict[str, Any] = {
                "resourceType": "Observation", "id": sus_id, "status": "final",
                "category": lab_category,
                "code": {"coding": [_micro_coding(sus_code_system, sus_code_value, lang)]},
                "subject": subject,
                "specimen": {"reference": f"Specimen/{spec_id}"},
                "valueCodeableConcept": {"coding": [{
                    "system": get_system_uri("hl7-observation-interpretation"),
                    "code": interp,
                    "display": code_lookup("hl7-observation-interpretation", interp, lang),
                }]},
            }
            if hai_identifier:
                sus_obs["identifier"] = hai_identifier
            if enc_ref:
                sus_obs["encounter"] = enc_ref
            # C1-13 (session 41 cycle 1): pin effectiveDateTime to match the
            # organism observation above (both belong to the same reported result).
            if mb.get("reported_datetime"):
                sus_obs["effectiveDateTime"] = mb["reported_datetime"]
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
        if hai_identifier:
            report["identifier"] = hai_identifier
        if enc_ref:
            report["encounter"] = enc_ref
        if mb.get("reported_datetime"):
            report["effectiveDateTime"] = mb["reported_datetime"]
        out.append(report)

    return out
