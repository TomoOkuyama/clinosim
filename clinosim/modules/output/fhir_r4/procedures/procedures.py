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
from clinosim.modules.output.fhir_r4.lib.common import to_fhir_datetime
from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name, _procedure_display


def _build_procedure(
    proc: dict,
    patient_id: str,
    index: int,
    country: str,
    record: dict | None = None,
) -> dict:
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
    # Issue #360 G6 / Issue #474: supportive-care Procedure records commonly
    # lack a K-code, so `primary_display` falls back to the English composite
    # ``{type}: {detail}`` text from ``modules/order/engine.py`` (e.g.
    # "O2: Nasal cannula SpO2 >= 94%") OR to a procedure name from encounter
    # YAML (e.g. "Ice pack application", "Wound irrigation with normal saline").
    #
    # Route the JP fallback through `_localize_drug_name` — despite its name,
    # this function is the phrase-level translator that consults
    # `drug_names_ja.yaml` (which already carries procedure phrases like
    # "Ice pack application" → "氷嚢貼付") and internally chains
    # `_localize_dosage_terms` for prefix / abbrev translation
    # (O2 → 酸素投与, PO → 経口, etc.).
    #
    # Prior code called `_localize_dosage_terms` directly, which only handles
    # dosage abbreviations and left encounter-YAML procedure names in English
    # (71/112 JP Procedure.code.text hits per Issue #474 measurement).
    # When a K-code was resolved, `_procedure_display` already returned the
    # authoritative JP display, so this call is a no-op there (idempotent).
    if is_jp(country) and primary_display:
        primary_display = _localize_drug_name(primary_display, country)

    coding_entries: list[dict[str, Any]] = [
        {
            "system": code_system,
            "code": primary_code,
            "display": primary_display,
        }
    ]

    # Secondary coding: the OTHER country's code system for international interop
    if is_jp(country) and proc_code_us:
        us_display = _procedure_display(proc_code_us, "en", fallback)
        coding_entries.append(
            {
                "system": get_system_uri("cpt"),
                "code": proc_code_us,
                "display": us_display,
            }
        )
    elif is_us(country) and proc_code_jp:
        # Secondary K-code for interop — use ENGLISH display (not Japanese)
        jp_en_display = _procedure_display(proc_code_jp, "en", fallback)
        coding_entries.append(
            {
                "system": get_system_uri("k-codes"),
                "code": proc_code_jp,
                "display": jp_en_display,
            }
        )

    resource: dict[str, Any] = {
        "resourceType": "Procedure",
        "id": resource_id,
        # Chain #2: JP Core Procedure profile.
        **(
            {"meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure"]}}
            if is_jp(country)
            else {}
        ),
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
            "coding": [
                {
                    "system": sct_uri,
                    "code": category_code,
                    "display": code_lookup("snomed-ct", category_code, lang),
                }
            ],
        }

    # Route through to_fhir_datetime so performedPeriod /
    # performedDateTime carry the FHIR R4-required TZ suffix (JST +09:00
    # for JP, per FB-F1 helper). Previously raw strings bypassed the
    # helper — this was the last site left after a broader sweep, and
    # was the source of the iris4h-ai HAPI validator "日付/TZ 不備 262件
    # Procedure" finding.
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
        performers.append(
            {
                "function": {
                    "coding": [
                        {
                            "system": sct_uri,
                            "code": "304292004",
                            "display": code_lookup("snomed-ct", "304292004", lang),
                        }
                    ],
                },
                "actor": {"reference": f"Practitioner/{surgeon_id}"},
            }
        )
    if anes_id and anes_id != surgeon_id:
        performers.append(
            {
                "function": {
                    "coding": [
                        {
                            "system": sct_uri,
                            "code": "158967008",
                            "display": code_lookup("snomed-ct", "158967008", lang),
                        }
                    ],
                },
                "actor": {"reference": f"Practitioner/{anes_id}"},
            }
        )
    if performers:
        resource["performer"] = performers
        # recorder (default to surgeon when available)
        resource["recorder"] = {"reference": f"Practitioner/{surgeon_id or anes_id}"}

    # reasonReference — link to encounter's primary Condition. Chronic-
    # primary encounters resolve to the patient-scoped chronic Condition;
    # acute-primary encounters keep the encounter-scoped id.
    if enc_id:
        if record is not None:
            from clinosim.modules.output.fhir_r4.conditions.primary_ref import primary_condition_ref

            _primary_ref = primary_condition_ref(record, patient_id, enc_id)
        else:
            _primary_ref = f"cond-{enc_id}-primary"
        resource["reasonReference"] = [{"reference": f"Condition/{_primary_ref}"}]
    # session-88j P2-5a: Procedure.reasonCode with real ICD-10 coding from
    # the encounter's clinical_diagnosis (was text-only generic template
    # "入院時診断に基づく処置" for all procedures — v14 review flagged as
    # uninformative). Preserves the existing text as fallback + as .text
    # alongside the coding for consumers that fall back to text.
    # CY7-17 (Chain-7): base fallback wording kept identical for
    # backwards compatibility of CY7-17 assertions.
    if not resource.get("reasonCode"):
        _dx = (record or {}).get("clinical_diagnosis", {}) or {}
        _dx_code = _dx.get("discharge_diagnosis_code") or _dx.get("admission_diagnosis_code", "") or ""
        _dx_display = _dx.get("discharge_diagnosis_display") or _dx.get("admission_diagnosis_display", "") or ""
        _generic_text = "入院時診断に基づく処置" if is_jp(country) else "Procedure indicated by encounter diagnosis"
        if _dx_code:
            # Use country-scoped ICD-10 system key (JP=icd-10-mhlw, US=icd-10-cm)
            # to stay consistent with Condition.code system emission.
            _icd_key = system_key_for("diagnosis", country)
            _display = _dx_display or (code_lookup(_icd_key, _dx_code, lang) or _dx_code)
            resource["reasonCode"] = [
                {
                    "coding": [
                        {
                            "system": get_system_uri(_icd_key),
                            "code": _dx_code,
                            "display": _display,
                        }
                    ],
                    "text": _display or _generic_text,
                }
            ]
        else:
            resource["reasonCode"] = [{"text": _generic_text}]

    # bodySite (SNOMED)
    body_site_code = proc.get("body_site_code", "")
    if body_site_code:
        resource["bodySite"] = [
            {
                "coding": [
                    {
                        "system": sct_uri,
                        "code": body_site_code,
                        "display": code_lookup("snomed-ct", body_site_code, lang),
                    }
                ],
            }
        ]
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
            "coding": [
                {
                    "system": sct_uri,
                    "code": outcome_code,
                    "display": code_lookup("snomed-ct", outcome_code, lang),
                }
            ],
        }
    # CY7-19 (Chain-7): outcome default = SNOMED 385669000 "Successful" when
    # Procedure.status == "completed" and no explicit outcome_code. Reflects
    # the majority clinical reality (few procedures fail without explicit
    # complication).
    if not resource.get("outcome") and resource.get("status") == "completed":
        _succ_code = "385669000"
        resource["outcome"] = {
            "coding": [
                {
                    "system": sct_uri,
                    "code": _succ_code,
                    "display": code_lookup("snomed-ct", _succ_code, lang) or "Successful",
                }
            ],
            "text": "成功" if is_jp(country) else "Successful",
        }

    # complication (SNOMED)
    comp_codes = proc.get("complication_codes", []) or []
    if comp_codes:
        resource["complication"] = [
            {
                "coding": [
                    {
                        "system": sct_uri,
                        "code": c,
                        "display": code_lookup("snomed-ct", c, lang),
                    }
                ],
            }
            for c in comp_codes
        ]

    return resource
