"""FHIR R4 Procedure resource builder (FA-1 procedures).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import (
    get_system_uri,
)
from clinosim.codes import (
    lookup as code_lookup,
)
from clinosim.modules.output._fhir_localization import _procedure_display


def _build_procedure(proc: dict, patient_id: str, index: int, country: str) -> dict:
    """Build FHIR Procedure resource."""
    code_system_key = "k-codes" if country == "JP" else "cpt"
    code_system = get_system_uri(code_system_key)
    sct_uri = get_system_uri("snomed-ct")
    lang = "ja" if country == "JP" else "en"

    # Use performedDateTime for point-in-time procedures, performedPeriod for longer ones
    start = proc.get("start_datetime", "")
    end = proc.get("end_datetime", "")

    # Encounter-scoped id to avoid collisions across patient's multiple encounters
    enc_id = proc.get("encounter_id", "")
    base_pid = proc.get("procedure_id") or f"proc-{patient_id}-{index:03d}"
    resource_id = f"{enc_id}-{base_pid}" if enc_id else base_pid

    # Per AD-30, CIF stores only codes. Displays resolved via code_lookup.
    proc_code_jp = proc.get("procedure_code_jp", "")
    proc_code_us = proc.get("procedure_code_us", "")
    primary_code = proc.get("procedure_code", "")
    proc_type = proc.get("procedure_type", "")
    fallback = proc_type or "(procedure)"

    # Resolve displays via code dictionaries (k-codes.yaml / cpt.yaml)
    primary_lang = "ja" if country == "JP" else "en"
    primary_display = _procedure_display(primary_code, primary_lang, fallback)

    coding_entries: list[dict[str, Any]] = [{
        "system": code_system,
        "code": primary_code,
        "display": primary_display,
    }]

    # Secondary coding: the OTHER country's code system for international interop
    if country == "JP" and proc_code_us:
        us_display = _procedure_display(proc_code_us, "en", fallback)
        coding_entries.append({
            "system": get_system_uri("cpt"),
            "code": proc_code_us,
            "display": us_display,
        })
    elif country == "US" and proc_code_jp:
        # Secondary K-code for interop — use ENGLISH display (not Japanese)
        jp_en_display = _procedure_display(proc_code_jp, "en", fallback)
        coding_entries.append({
            "system": get_system_uri("k-codes"),
            "code": proc_code_jp,
            "display": jp_en_display,
        })

    resource: dict[str, Any] = {
        "resourceType": "Procedure",
        "id": resource_id,
        "status": "completed",
        "code": {
            "coding": coding_entries,
            "text": primary_display,
        },
        "subject": {"reference": f"Patient/{patient_id}"},
    }

    # category (SNOMED)
    category_code = proc.get("category_code", "")
    if category_code:
        resource["category"] = {
            "coding": [{
                "system": sct_uri,
                "code": category_code,
                "display": code_lookup("snomed-ct", category_code, lang),
            }],
        }

    if start and end and start != end:
        resource["performedPeriod"] = {"start": start, "end": end}
    elif start:
        resource["performedDateTime"] = start

    if proc.get("encounter_id"):
        resource["encounter"] = {"reference": f"Encounter/{proc['encounter_id']}"}

    # performer[] with function (surgeon, anesthesiologist)
    performers: list[dict[str, Any]] = []
    surgeon_id = proc.get("primary_surgeon_id", "")
    anes_id = proc.get("anesthesiologist_id", "")
    if surgeon_id:
        performers.append({
            "function": {
                "coding": [{
                    "system": sct_uri,
                    "code": "304292004",
                    "display": code_lookup("snomed-ct", "304292004", lang),
                }],
            },
            "actor": {"reference": f"Practitioner/{surgeon_id}"},
        })
    if anes_id and anes_id != surgeon_id:
        performers.append({
            "function": {
                "coding": [{
                    "system": sct_uri,
                    "code": "158967008",
                    "display": code_lookup("snomed-ct", "158967008", lang),
                }],
            },
            "actor": {"reference": f"Practitioner/{anes_id}"},
        })
    if performers:
        resource["performer"] = performers
        # recorder (default to surgeon when available)
        resource["recorder"] = {"reference": f"Practitioner/{surgeon_id or anes_id}"}

    # reasonReference — link to encounter's primary Condition
    if enc_id:
        resource["reasonReference"] = [
            {"reference": f"Condition/cond-{enc_id}-primary"}
        ]

    # bodySite (SNOMED)
    body_site_code = proc.get("body_site_code", "")
    if body_site_code:
        resource["bodySite"] = [{
            "coding": [{
                "system": sct_uri,
                "code": body_site_code,
                "display": code_lookup("snomed-ct", body_site_code, lang),
            }],
        }]

    # location (OR etc.)
    location_id = proc.get("location_id", "")
    if location_id:
        resource["location"] = {"reference": f"Location/{location_id}"}

    # outcome (SNOMED)
    outcome_code = proc.get("outcome_code", "")
    if outcome_code:
        resource["outcome"] = {
            "coding": [{
                "system": sct_uri,
                "code": outcome_code,
                "display": code_lookup("snomed-ct", outcome_code, lang),
            }],
        }

    # complication (SNOMED)
    comp_codes = proc.get("complication_codes", []) or []
    if comp_codes:
        resource["complication"] = [
            {
                "coding": [{
                    "system": sct_uri,
                    "code": c,
                    "display": code_lookup("snomed-ct", c, lang),
                }],
            }
            for c in comp_codes
        ]

    return resource
