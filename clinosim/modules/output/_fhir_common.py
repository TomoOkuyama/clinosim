"""FHIR R4 shared low-level helpers (FA-1 Phase 3).

Leaf-level fragment helpers extracted from ``fhir_r4_adapter`` — each produces a
FHIR *fragment* (a coding, a CodeableConcept, a Dosage, a reference range, a
status code, a Bundle entry) rather than a top-level resource. They depend only
on :mod:`clinosim.codes`, :mod:`clinosim.locale`, and the two leaf reference
modules, so resource-builder modules can import them without an import cycle
back through the adapter facade.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping, load_reference_ranges
from clinosim.modules.output._fhir_localization import (
    _CATEGORY_DISPLAY_JA,
    _FREQ_JA,
    _ROUTE_JA,
    _SEVERITY_DISPLAY_JA,
    _localize_display,
    _localize_dosage_terms,
    _localize_drug_name,
)
from clinosim.modules.output._fhir_reference_data import (
    _CONDITION_SHORT_NAME,
    _PREFECTURE_CODE,
    _ROUTE_SNOMED,
    _SEVERITY_SNOMED,
)


@dataclass
class BundleContext:
    """Shared inputs for FHIR resource builders (AD-56)."""

    record: dict
    country: str
    roster_map: dict
    hospital_config: dict
    patient_data: dict
    patient_id: str
    is_readmission: bool
    prior_encounter_id: Any
    primary_dx_code: str
    admit_dx_code: str
    admit_dx_system: str
    primary_enc_id: str
    patient_sex: str


def _micro_coding(system_key: str, code: str, lang: str) -> dict:
    """Build a coding with display resolved via codes (never display == code)."""
    coding: dict[str, Any] = {"system": get_system_uri(system_key), "code": code}
    disp = code_lookup(system_key, code, lang)
    if disp and disp != code:
        coding["display"] = disp
    return coding


def _survey_category() -> list[dict]:
    """Return the observation category list for survey-type observations.

    Uses get_system_uri to avoid hardcoding FHIR system URIs (project rule).
    """
    return [{
        "coding": [{
            "system": get_system_uri("hl7-observation-category"),
            "code": "survey",
            "display": "Survey",
        }],
        "text": "Survey",
    }]


def _loinc_coding(code: str, lang: str) -> dict:
    """Build a LOINC coding entry. Display resolved via lookup; never display == code."""
    disp = code_lookup("loinc", code, lang)
    entry: dict[str, Any] = {"system": get_system_uri("loinc"), "code": code}
    if disp and disp != code:
        entry["display"] = disp
    return entry


def _social_category(country: str) -> list[dict]:
    """FHIR Observation.category for social-history (US Core SDOH).

    Returns the standard hl7-observation-category coding with localized
    display + text — used by every social-history Observation builder
    (smoking, alcohol, occupation, education, housing, ...). Promoted
    from _fhir_sdoh.py in PR2 (G2 SDOH integrity refactor, 2026-06-24).
    """
    return [{
        "coding": [{
            "system": get_system_uri("hl7-observation-category"),
            "code": "social-history",
            "display": _localize_display("Social History", country, _CATEGORY_DISPLAY_JA),
        }],
        "text": "社会歴" if country == "JP" else "Social History",
    }]


def _value(system_key: str, code: str, lang: str) -> dict[str, Any]:
    """Build a FHIR valueCodeableConcept with localized display.

    Generic helper for any coded value whose display lives in
    clinosim.codes. Returns a CodeableConcept fragment
    {"coding": [{"system": ..., "code": ..., "display": ...}], "text": ...}
    — distinct from _micro_coding() in this module which returns the
    bare coding dict (no CodeableConcept wrapping). Used by SDOH
    builders (smoking_status / alcohol_use / care_level) and any future
    builder emitting a coded valueCodeableConcept.

    Promoted from _fhir_sdoh.py in PR2 (G2 SDOH integrity refactor,
    2026-06-24).
    """
    coding: dict[str, Any] = {"system": get_system_uri(system_key), "code": code}
    disp = code_lookup(system_key, code, lang)
    if disp and disp != code:
        coding["display"] = disp
    return {"coding": [coding], "text": disp or code}


def _entry(resource: dict) -> dict:
    """Wrap a resource as a Bundle entry."""
    rid = resource.get("id", str(uuid.uuid4()))
    rtype = resource.get("resourceType", "Resource")
    return {
        "fullUrl": f"urn:uuid:{rid}",
        "resource": resource,
    }


def _build_diagnosis_codeable_concept(
    code: str, system_key: str, country: str
) -> dict[str, Any]:
    """Build a FHIR CodeableConcept for a diagnosis code with multilingual coding.

    - Primary coding: target country's system + target language display
    - Secondary coding: always includes English display (for interop)
    - code.text: primary language display (local charting expression)
    - Never emits display==code: falls back to "(display unavailable)"

    Falls back to icd-10-cm lookup if the code isn't in the country's system
    (e.g. JP using icd-10 but code only in icd-10-cm).

    code.text is set to a clinical short-name / abbreviation when available
    (e.g. "COPD" instead of "Other chronic obstructive pulmonary disease"),
    enabling search by common clinical abbreviations.
    """
    primary_lang = "ja" if country != "US" else "en"
    primary_system = get_system_uri(system_key)

    # Look up display in primary language (with cross-system fallback)
    primary_display = (
        code_lookup(system_key, code, primary_lang)
        if code
        else ""
    )
    # If primary system has no entry, try icd-10-cm which is more comprehensive
    if (not primary_display or primary_display == code) and system_key != "icd-10-cm":
        alt = code_lookup("icd-10-cm", code, primary_lang)
        if alt and alt != code:
            primary_display = alt
    # Last-resort fallback: never emit display==code
    if not primary_display or primary_display == code:
        primary_display = "(display unavailable)"

    # English display (for interop secondary coding)
    en_display = code_lookup(system_key, code, "en") if code else ""
    if (not en_display or en_display == code) and system_key != "icd-10-cm":
        alt_en = code_lookup("icd-10-cm", code, "en")
        if alt_en and alt_en != code:
            en_display = alt_en
    if not en_display or en_display == code:
        en_display = "(display unavailable)"

    coding = [{
        "system": primary_system,
        "code": code,
        "display": primary_display,
    }]
    # Add English coding for multilingual interop when primary is not English
    if primary_lang != "en" and en_display != primary_display:
        coding.append({
            "system": primary_system,  # same code system, different display
            "code": code,
            "display": en_display,
        })

    # code.text: clinical short-name / abbreviation for search friendliness.
    # coding[].display remains the official ICD name; text is what clinicians type.
    text = _CONDITION_SHORT_NAME.get(code.split(".")[0], {}).get(primary_lang) or primary_display

    return {
        "coding": coding,
        "text": text,
    }


def _map_diagnosis_code(code: str, country: str) -> str:
    """Translate an internal chronic/history diagnosis base code to its locale code.

    US maps internal category/WHO codes (I50, E78, I21, ...) to billable ICD-10-CM
    leaves; JP maps identity (WHO ICD-10 category codes are valid as-is). Codes absent
    from the locale map pass through unchanged — disease primary diagnoses are already
    specific (e.g. I21.9, A41.9) and stay untouched. See locale/<c>/code_mapping_diagnosis.

    Dedup is intentionally done on the *internal* base code by the caller, not on the
    mapped code, so a current acute MI (primary I21.9) still suppresses a duplicate
    "old MI" chronic entry rather than emitting both.
    """
    if not code:
        return code
    country_code = "JP" if country != "US" else "US"
    return load_code_mapping("diagnosis", country_code).get(code, code)


def _infer_severity(record: dict) -> str:
    """Infer encounter severity from physiological states."""
    states = record.get("physiological_states", [])
    if not states:
        return ""
    # Use peak inflammation as severity proxy
    peak_infl = max(s.get("inflammation_level", 0) for s in states)
    if peak_infl >= 0.5:
        return "severe"
    elif peak_infl >= 0.2:
        return "moderate"
    elif peak_infl > 0:
        return "mild"
    return ""


def _severity_coding(severity: str, country: str = "US") -> dict[str, Any]:
    """Build FHIR severity CodeableConcept from severity string."""
    sev = severity.lower()
    snomed = dict(_SEVERITY_SNOMED.get(sev, _SEVERITY_SNOMED.get("moderate")))
    if country == "JP":
        orig_display = snomed.get("display", "")
        snomed["display"] = _SEVERITY_DISPLAY_JA.get(orig_display, orig_display)
    return {
        "coding": [{
            "system": get_system_uri("snomed-ct"),
            **snomed,
        }],
        "text": snomed.get("display", ""),
    }


def _build_address(addr: dict, country: str) -> dict[str, Any] | None:
    """Build FHIR Address from CIF address data."""
    if not addr.get("city") and not addr.get("line1"):
        return None

    state_name = addr.get("state", "")
    country_code = addr.get("country", country)

    # Build full address line
    if country_code == "JP":
        # JP: 都道府県+市区町村+番地
        line = f"{state_name}{addr.get('city', '')}{addr.get('line1', '')}"
    else:
        # US: street line
        line = addr.get("line1", "")

    fhir_addr: dict[str, Any] = {
        "type": "both",
        "line": [line] if line else [],
        "city": addr.get("city", ""),
        "postalCode": addr.get("postal_code", ""),
        "country": country_code,
    }

    # State: use code for JP (JIS X 0401), abbreviation for US
    if country_code == "JP":
        code = _PREFECTURE_CODE.get(state_name, "")
        if code:
            fhir_addr["state"] = code
    elif state_name:
        fhir_addr["state"] = state_name

    return fhir_addr


def _build_telecom(contact: dict) -> list[dict[str, str]]:
    """Build FHIR ContactPoint list from CIF contact data."""
    telecoms: list[dict[str, str]] = []
    if contact.get("phone_mobile"):
        telecoms.append({
            "system": "phone", "value": contact["phone_mobile"], "use": "mobile",
        })
    if contact.get("phone_home") and contact["phone_home"] != contact.get("phone_mobile"):
        telecoms.append({
            "system": "phone", "value": contact["phone_home"], "use": "home",
        })
    if contact.get("email"):
        telecoms.append({
            "system": "email", "value": contact["email"], "use": "home",
        })
    return telecoms


def _make_participant(code: str, display: str, practitioner_id: str) -> dict[str, Any]:
    """Build an Encounter.participant entry."""
    return {
        "type": [{
            "coding": [{
                "system": get_system_uri("hl7-v3-participationtype"),
                "code": code,
                "display": display,
            }],
        }],
        "individual": {"reference": f"Practitioner/{practitioner_id}"},
    }


def _build_dosage_instruction(order: dict, country: str = "US") -> dict[str, Any] | None:
    """Build FHIR Dosage from structured order fields."""
    dose_qty = order.get("dose_quantity")
    dose_unit = order.get("dose_unit", "")
    freq = order.get("frequency", "")
    freq_per_day = order.get("frequency_per_day")
    route = (order.get("route") or "").upper()

    # If nothing structured is available, fall back to text from display_name
    if dose_qty is None and not freq and not route:
        text = order.get("display_name", "")
        if text:
            return {"text": text}
        return None

    dosage: dict[str, Any] = {}
    parts = []

    # Dose quantity
    if dose_qty is not None and dose_unit:
        dosage["doseAndRate"] = [{
            "doseQuantity": {
                "value": dose_qty,
                "unit": dose_unit,
                "system": get_system_uri("ucum"),
            },
        }]
        parts.append(f"{dose_qty}{dose_unit}")

    # Route
    if route:
        snomed = _ROUTE_SNOMED.get(route)
        if snomed:
            dosage["route"] = {
                "coding": [{"system": get_system_uri("snomed-ct"), **snomed}],
                "text": route,
            }
        else:
            dosage["route"] = {"text": route}
        parts.append(route)

    # Timing
    if freq_per_day:
        dosage["timing"] = {
            "repeat": {
                "frequency": freq_per_day,
                "period": 1,
                "periodUnit": "d",
            },
        }
        parts.append(freq or f"{freq_per_day}x/day")
    elif freq:
        parts.append(freq)

    # Text summary
    if parts:
        if country == "JP":
            ja_parts = []
            for p in parts:
                p_upper = p.upper()
                ja_parts.append(_ROUTE_JA.get(p_upper) or _FREQ_JA.get(p_upper) or _FREQ_JA.get(p) or p)
            text = " ".join(ja_parts)
            # Final pass through dosage term translator for any remaining English
            dosage["text"] = _localize_dosage_terms(text) if country == "JP" else text
        else:
            dosage["text"] = " ".join(parts)
    elif order.get("display_name"):
        name = order["display_name"]
        dosage["text"] = _localize_drug_name(name, country) if country == "JP" else name

    return dosage if dosage else None


def _strip_protocol_prefix(name: str) -> tuple[str, str]:
    """Strip protocol/category prefix from drug order text.

    "DVT_prophylaxis: Enoxaparin 2000IU SC daily" → ("Enoxaparin 2000IU SC daily", "DVT prophylaxis")
    "antipyretic: Acetaminophen 500mg PO q6h PRN temp >= 38.5" → ("Acetaminophen 500mg PO q6h PRN temp >= 38.5", "antipyretic")
    "Ceftriaxone 1g IV q8h" → ("Ceftriaxone 1g IV q8h", "")

    Returns (cleaned_name, protocol_category).
    """
    if ":" in name:
        prefix, rest = name.split(":", 1)
        rest = rest.strip()
        if rest:
            return rest, prefix.replace("_", " ").strip()
    return name, ""


def _parse_dose_for_mar(text: str) -> dict[str, Any]:
    """Lightweight dose parser for MAR (avoids importing order engine in adapter)."""
    import re
    result: dict[str, Any] = {}
    if not text:
        return result
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mg|g|mcg|ug|mL|ml|L|IU|U|unit|units|%)",
                  text, re.IGNORECASE)
    if m:
        try:
            result["dose_quantity"] = float(m.group(1))
            result["dose_unit"] = m.group(2)
        except ValueError:
            pass
    route_match = re.search(r"\b(PO|IV|SC|IM|SL|PR|NG|inhaled|topical)\b", text, re.IGNORECASE)
    if route_match:
        result["route"] = route_match.group(1).upper()
    return result


def _sha1_b64(text: str) -> str:
    """Return base64-encoded SHA1 hash of text, as required by FHIR Attachment.hash."""
    import base64
    import hashlib
    h = hashlib.sha1(text.encode("utf-8")).digest()
    return base64.b64encode(h).decode("ascii")


def _build_reference_range(
    lab_name: str, patient_sex: str, country_code: str,
) -> list[dict[str, Any]] | None:
    """Build FHIR referenceRange from locale reference range data.

    For JP: uses JCCLS共用基準範囲 2022 with source extension.
    Sex-specific ranges are filtered by patient sex with appliesTo.
    """
    ref_data = load_reference_ranges(country_code)
    if not ref_data:
        return None

    ranges = ref_data.get("ranges", {}).get(lab_name)
    if not ranges:
        return None

    source_url = ref_data.get("source_url", "")
    result: list[dict[str, Any]] = []

    for entry in ranges:
        sex = entry.get("sex")
        # If sex-specific, only include the matching range (or both if sex unknown)
        if sex and patient_sex and sex != patient_sex:
            continue

        rr: dict[str, Any] = {}
        unit_str = entry.get("unit", "")
        if entry.get("low") is not None:
            rr["low"] = {
                "value": entry["low"], "unit": unit_str,
                "system": get_system_uri("ucum"), "code": unit_str,
            }
        if entry.get("high") is not None:
            rr["high"] = {
                "value": entry["high"], "unit": unit_str,
                "system": get_system_uri("ucum"), "code": unit_str,
            }
        if entry.get("text"):
            rr["text"] = entry["text"]

        # appliesTo for sex-specific ranges
        if sex:
            rr["appliesTo"] = [{
                "coding": [{
                    "system": get_system_uri("hl7-v3-administrativegender"),
                    "code": sex,
                }],
            }]

        # Source extension (JP Core)
        if source_url:
            rr["extension"] = [{
                "url": "http://jpfhir.jp/fhir/core/StructureDefinition/"
                       "JP_Observation_Common#referenceRangeSource",
                "valueString": source_url,
            }]

        result.append(rr)

    return result if result else None


def _map_mar_status(status: str) -> str:
    return {"given": "completed", "held": "on-hold", "refused": "not-done", "not_available": "not-done"}.get(status, "completed")


def _map_encounter_status(status: str) -> str:
    mapping = {
        "planned": "planned",
        "in_progress": "in-progress",
        "completed": "finished",
        "cancelled": "cancelled",
    }
    return mapping.get(status, "unknown")
