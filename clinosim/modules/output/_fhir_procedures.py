"""FHIR R4 Procedure resource builder (FA-1 procedures).

Extracted verbatim from ``fhir_r4_adapter``. Self-contained: imports only
leaf data, shared helpers, and stdlib/first-party deps — never the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import (
    get_system_uri,
    system_key_for,
)
from clinosim.codes import (
    lookup as code_lookup,
)
from clinosim.modules._shared import is_jp, is_us, resolve_lang
from clinosim.modules.output._fhir_common import to_fhir_datetime
from clinosim.modules.output._fhir_localization import _procedure_display


def _build_procedure(proc: dict, patient_id: str, index: int, country: str) -> dict:
    """Build FHIR Procedure resource."""
    code_system_key = system_key_for("procedure", country)
    code_system = get_system_uri(code_system_key)
    sct_uri = get_system_uri("snomed-ct")
    lang = resolve_lang(country)

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
    primary_lang = resolve_lang(country)
    primary_display = _procedure_display(primary_code, primary_lang, fallback)

    coding_entries: list[dict[str, Any]] = [{
        "system": code_system,
        "code": primary_code,
        "display": primary_display,
    }]

    # Secondary coding: the OTHER country's code system for international interop
    if is_jp(country) and proc_code_us:
        us_display = _procedure_display(proc_code_us, "en", fallback)
        coding_entries.append({
            "system": get_system_uri("cpt"),
            "code": proc_code_us,
            "display": us_display,
        })
    elif is_us(country) and proc_code_jp:
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
        # Session 46 chain #2: JP Core Procedure profile.
        **({"meta": {"profile": [
            "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"
        ]}} if is_jp(country) else {}),
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

    # Session 52 fix: route through to_fhir_datetime so performedPeriod /
    # performedDateTime carry the FHIR R4-required TZ suffix (JST +09:00
    # for JP, per FB-F1 helper). Previously raw strings bypassed the
    # helper — only site left after session 48 sweep, source of the
    # iris4h-ai HAPI validator "日付/TZ 不備 262件 Procedure" finding.
    _start_fhir = to_fhir_datetime(start)
    _end_fhir = to_fhir_datetime(end)
    if _start_fhir and _end_fhir and _start_fhir != _end_fhir:
        resource["performedPeriod"] = {"start": _start_fhir, "end": _end_fhir}
    elif _start_fhir:
        resource["performedDateTime"] = _start_fhir

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
    # CY7-17 (Chain-7): Procedure.reasonCode fallback — text-only citing the
    # encounter's primary diagnosis when the CIF procedure record doesn't
    # carry an explicit reason. FHIR R4 Procedure.reasonCode 0..*.
    if not resource.get("reasonCode"):
        resource["reasonCode"] = [{
            "text": "入院時診断に基づく処置" if is_jp(country) else "Procedure indicated by encounter diagnosis",
        }]

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
    # CY7-18 (Chain-7): bodySite text-only fallback when the CIF record
    # doesn't carry a SNOMED site code (bedside procedures often don't).
    if not resource.get("bodySite"):
        resource["bodySite"] = [{"text": "処置部位不明" if is_jp(country) else "Body site not specified"}]

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
    # CY7-19 (Chain-7): outcome default = SNOMED 385669000 "Successful" when
    # Procedure.status == "completed" and no explicit outcome_code. Reflects
    # the majority clinical reality (few procedures fail without explicit
    # complication).
    if not resource.get("outcome") and resource.get("status") == "completed":
        _succ_code = "385669000"
        resource["outcome"] = {
            "coding": [{
                "system": sct_uri,
                "code": _succ_code,
                "display": code_lookup("snomed-ct", _succ_code, lang) or "Successful",
            }],
            "text": "成功" if is_jp(country) else "Successful",
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
