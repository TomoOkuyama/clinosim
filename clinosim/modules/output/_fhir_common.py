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
from datetime import date, datetime
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping, load_reference_ranges
from clinosim.modules._shared import is_jp, is_us, resolve_lang, strip_protocol_prefix
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


def _escape_html(s: str) -> str:
    """Escape HTML special characters for safe embedding in FHIR text.div.

    Escapes &, <, >, " — sufficient for plain-text clinical content that
    may contain lab values, units, or angle brackets (e.g. "PaO2 < 80 & SpO2 > 90").
    Shared across _fhir_diagnostic_report.py and _fhir_composition.py (DRY, CLAUDE.md
    unification rule — no inline duplication).
    """
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _coding_with_display(system_key: str, code: str, lang: str) -> dict:
    """Build a FHIR coding, resolving display via codes/data.

    Never emits ``display=code`` (a common FHIR interop trap); if
    ``code_lookup`` cannot resolve a display it is omitted entirely.

    Used at every builder site that emits a single coding (no CodeableConcept
    wrapping and no multilingual duplicate). Sibling helpers: ``_value()``
    (wraps as full CodeableConcept), ``_loinc_coding()`` (LOINC-specialized),
    ``_build_diagnosis_codeable_concept()`` (multi-language dx codes).

    C2-01/02/03/05/06/07/08 (session 42 cycle 2) — migrated the display-fallback
    sites (Encounter.type, Condition.clinicalStatus/verificationStatus,
    Observation.referenceRange.appliesTo, Coverage.relationship,
    PractitionerRole.code, DiagnosticReport.category) through this helper.
    """
    coding: dict[str, Any] = {"system": get_system_uri(system_key), "code": code}
    disp = code_lookup(system_key, code, lang)
    if disp and disp != code:
        coding["display"] = disp
    return coding


# Legacy alias — microbiology builders (_fhir_microbiology) use this name.
# The public helper name is `_coding_with_display`. Keep the alias to avoid
# churn on unrelated call sites (session 42, cycle 2).
_micro_coding = _coding_with_display


def _survey_category() -> list[dict]:
    """Return the observation category list for survey-type observations.

    Uses get_system_uri to avoid hardcoding FHIR system URIs (project rule).
    """
    return [
        {
            "coding": [
                {
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "survey",
                    "display": "Survey",
                }
            ],
            "text": "Survey",
        }
    ]


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
    return [
        {
            "coding": [
                {
                    "system": get_system_uri("hl7-observation-category"),
                    "code": "social-history",
                    "display": _localize_display("Social History", country, _CATEGORY_DISPLAY_JA),
                }
            ],
            "text": "社会歴" if is_jp(country) else "Social History",
        }
    ]


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
    resource.get("resourceType", "Resource")
    return {
        "fullUrl": f"urn:uuid:{rid}",
        "resource": resource,
    }


def _build_diagnosis_codeable_concept(code: str, system_key: str, country: str) -> dict[str, Any]:
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
    primary_lang = resolve_lang(country)
    primary_system = get_system_uri(system_key)

    # Look up display in primary language (with cross-system fallback)
    primary_display = code_lookup(system_key, code, primary_lang) if code else ""
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

    coding = [
        {
            "system": primary_system,
            "code": code,
            "display": primary_display,
        }
    ]
    # Add English coding for multilingual interop when primary is not English
    if primary_lang != "en" and en_display != primary_display:
        coding.append(
            {
                "system": primary_system,  # same code system, different display
                "code": code,
                "display": en_display,
            }
        )

    # code.text: clinical short-name / abbreviation for search friendliness.
    # coding[].display remains the official ICD name; text is what clinicians type.
    base_code = code.split(".")[0] if code else ""
    short_name = code_lookup("condition-short-name", base_code, primary_lang) if base_code else ""
    text = short_name if short_name and short_name != base_code else primary_display

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
    country_code = "US" if is_us(country) else "JP"
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
    if is_jp(country):
        orig_display = snomed.get("display", "")
        snomed["display"] = _SEVERITY_DISPLAY_JA.get(orig_display, orig_display)
    return {
        "coding": [
            {
                "system": get_system_uri("snomed-ct"),
                **snomed,
            }
        ],
        "text": snomed.get("display", ""),
    }


def _build_address(addr: dict, country: str) -> dict[str, Any] | None:
    """Build FHIR Address from CIF address data."""
    if not addr.get("city") and not addr.get("line1"):
        return None

    state_name = addr.get("state", "")
    country_code = addr.get("country", country)

    # Build full address line
    if is_jp(country_code):
        # JP: 都道府県+市区町村+番地
        line = f"{state_name}{addr.get('city', '')}{addr.get('line1', '')}"
    else:
        # US: street line
        line = addr.get("line1", "")

    fhir_addr: dict[str, Any] = {
        # C4-13 (session 43 cycle 4): Address.use = "home" per FHIR R4 spec.
        # JP Core Patient guidance mirrors HL7 R4: use should be populated
        # (was implicit "?"/missing, 100% of Patient.address records).
        "use": "home",
        "type": "both",
        "line": [line] if line else [],
        "city": addr.get("city", ""),
        "postalCode": addr.get("postal_code", ""),
        "country": country_code,
    }

    # State: use code for JP (JIS X 0401), abbreviation for US
    if is_jp(country_code):
        code = _PREFECTURE_CODE.get(state_name, "")
        if code:
            fhir_addr["state"] = code
    elif state_name:
        fhir_addr["state"] = state_name

    return fhir_addr


def build_presented_form(text: str, title: str, lang: str = "en") -> list[dict[str, Any]]:
    """Build DiagnosticReport.presentedForm[] from a text summary.

    C5-20 (Chain 3): patient-facing rendered form of the diagnostic report.
    FHIR R4 presentedForm is Attachment (0..*). clinosim emits a text/plain
    representation (base64-encoded) — a PDF-format placeholder would require
    a PDF-generation dependency and would not be reviewable by consumers.
    Downstream systems can transform text/plain to PDF at delivery time if
    needed.

    Returns [] if text is empty (Attachment.data must be non-empty).
    """
    if not text:
        return []
    import base64
    import hashlib

    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    h = hashlib.sha1(text.encode("utf-8")).digest()
    return [
        {
            "contentType": "text/plain; charset=utf-8",
            "language": lang,
            "data": encoded,
            "title": title,
            "size": len(text.encode("utf-8")),
            "hash": base64.b64encode(h).decode("ascii"),
        }
    ]


def _build_telecom(contact: dict) -> list[dict[str, str]]:
    """Build FHIR ContactPoint list from CIF contact data."""
    telecoms: list[dict[str, str]] = []
    if contact.get("phone_mobile"):
        telecoms.append(
            {
                "system": "phone",
                "value": contact["phone_mobile"],
                "use": "mobile",
            }
        )
    if contact.get("phone_home") and contact["phone_home"] != contact.get("phone_mobile"):
        telecoms.append(
            {
                "system": "phone",
                "value": contact["phone_home"],
                "use": "home",
            }
        )
    if contact.get("email"):
        telecoms.append(
            {
                "system": "email",
                "value": contact["email"],
                "use": "home",
            }
        )
    return telecoms


def _make_participant(code: str, display: str, practitioner_id: str, country: str = "US") -> dict[str, Any]:
    """Build an Encounter.participant entry.

    C5-02 (session 43 cycle 5): localize `display` for JP output — HL7
    v3-ParticipationType English default (attender / admitter / discharger)
    was leaking to JP output as literal text.
    """
    from clinosim.modules.output._fhir_localization import (
        _PARTICIPATION_TYPE_DISPLAY_JA,
        _localize_display,
    )

    localized = _localize_display(display, country, _PARTICIPATION_TYPE_DISPLAY_JA)
    return {
        "type": [
            {
                "coding": [
                    {
                        "system": get_system_uri("hl7-v3-participationtype"),
                        "code": code,
                        "display": localized,
                    }
                ],
            }
        ],
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
        dosage["doseAndRate"] = [
            {
                "doseQuantity": {
                    "value": dose_qty,
                    "unit": dose_unit,
                    "system": get_system_uri("ucum"),
                },
            }
        ]
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
    # C4-16 (session 43 cycle 4): derive freq_per_day from common freq
    # strings when the order only supplies the label (was 13% of MR with
    # dosageInstruction lacking timing.repeat).
    if freq_per_day is None and freq:
        _flow = freq.lower().strip()
        _derived: int | None = None
        if _flow in ("qd", "q24h", "once daily", "daily", "1x/day"):
            _derived = 1
        elif _flow in ("bid", "q12h", "twice daily", "2x/day"):
            _derived = 2
        elif _flow in ("tid", "q8h", "three times daily", "3x/day"):
            _derived = 3
        elif _flow in ("qid", "q6h", "four times daily", "4x/day"):
            _derived = 4
        elif _flow in ("q4h",):
            _derived = 6
        elif _flow in ("q3h",):
            _derived = 8
        elif _flow in ("q2h",):
            _derived = 12
        elif _flow in ("qhs", "bedtime", "at bedtime", "hs"):
            _derived = 1
        if _derived is not None:
            freq_per_day = _derived

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
        _flow = freq.lower().strip()
        # PRN / as needed → asNeededBoolean=true, no fixed frequency.
        if _flow in ("prn", "as needed", "when required"):
            dosage["asNeededBoolean"] = True
        parts.append(freq)

    # Text summary
    if parts:
        if is_jp(country):
            ja_parts = []
            for p in parts:
                p_upper = p.upper()
                ja_parts.append(_ROUTE_JA.get(p_upper) or _FREQ_JA.get(p_upper) or _FREQ_JA.get(p) or p)
            text = " ".join(ja_parts)
            # Final pass through dosage term translator for any remaining English
            dosage["text"] = _localize_dosage_terms(text) if is_jp(country) else text
        else:
            dosage["text"] = " ".join(parts)
    elif order.get("display_name"):
        name = order["display_name"]
        dosage["text"] = _localize_drug_name(name, country) if is_jp(country) else name

    return dosage if dosage else None


# Promoted to clinosim/modules/_shared.py (β-JP-1 chain 1a adv-1 I-1) so the
# narrative renderer shares the same normalization; kept as an alias here for
# the existing FHIR-builder import sites.
_strip_protocol_prefix = strip_protocol_prefix


def _parse_dose_for_mar(text: str) -> dict[str, Any]:
    """Lightweight dose parser for MAR (avoids importing order engine in adapter)."""
    import re

    result: dict[str, Any] = {}
    if not text:
        return result
    m = re.search(r"(\d+(?:\.\d+)?)\s*(mg|g|mcg|ug|mL|ml|L|IU|U|unit|units|%)", text, re.IGNORECASE)
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
    lab_name: str,
    patient_sex: str,
    country_code: str,
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
                "value": entry["low"],
                "unit": unit_str,
                "system": get_system_uri("ucum"),
                "code": unit_str,
            }
        if entry.get("high") is not None:
            rr["high"] = {
                "value": entry["high"],
                "unit": unit_str,
                "system": get_system_uri("ucum"),
                "code": unit_str,
            }
        if entry.get("text"):
            rr["text"] = entry["text"]

        # appliesTo for sex-specific ranges
        if sex:
            # C2-05 (session 42): resolve display via codes/data/hl7-v3-
            # administrativegender.yaml (was raw code emission with no display).
            rr["appliesTo"] = [
                {
                    "coding": [
                        _coding_with_display(
                            "hl7-v3-administrativegender",
                            sex,
                            resolve_lang(country_code),
                        )
                    ],
                }
            ]

        # Source extension. The JP Core Observation_Common profile defines a
        # `referenceRangeSource` sub-extension for citing the range's issuing
        # body (e.g. JCCLS 共用基準範囲 2022). Attach ONLY for country=JP;
        # US bundles must not embed jpfhir.jp URLs (multi-locale isolation,
        # session 47 P2-13 Task 5 bug fix).
        if source_url and country_code.upper() == "JP":
            rr["extension"] = [
                {
                    "url": "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common#referenceRangeSource",
                    "valueString": source_url,
                }
            ]

        result.append(rr)

    return result if result else None


def _map_mar_status(status: str) -> str:
    return {"given": "completed", "held": "on-hold", "refused": "not-done", "not_available": "not-done"}.get(
        status, "completed"
    )  # noqa: E501


# session 48 cycle 8 拡張 (feedback FB-F1):
# JP コホートの dateTime / instant field は JST (+09:00) を必ず付与する。
# HAPI FHIR Validator (JP Core 準拠) は TZ 無し dateTime を regex エラーとする。
# to_fhir_datetime + to_fhir_instant で単一 seam 化、per-builder 個別修正回避。
_JST_TZ_SUFFIX = "+09:00"


def _append_tz_if_missing(s: str) -> str:
    """ISO 8601 datetime string に TZ が無ければ +09:00 (JST) を付与。

    既に TZ suffix(+HH:MM / -HH:MM / Z)がある場合は passthrough。
    'T' を含まない date-only 文字列 (YYYY-MM-DD) は passthrough(FHIR は date
    型として許容)。
    """
    if not s or "T" not in s:
        return s
    # tail check for existing TZ
    tail = s[-6:]  # like "+09:00" or "-05:00"
    if s.endswith("Z"):
        return s
    if len(s) >= 6 and (tail.startswith("+") or tail.startswith("-")) and tail[3] == ":":
        return s
    # short TZ form "+0900" (no colon)
    if len(s) >= 5 and (s[-5] == "+" or s[-5] == "-") and s[-5:-2].lstrip("+-").isdigit():
        return s
    return s + _JST_TZ_SUFFIX


def to_fhir_datetime(value: Any) -> str:
    """Normalize a datetime-like value to a FHIR R4 ``dateTime`` string with TZ.

    FHIR R4 ``dateTime`` requires ISO 8601 with ``T`` separator; ``str(datetime)``
    produces space-separated form which fails the R4 regex. This helper accepts:
    ``datetime`` / ``date`` objects (via ``.isoformat()``), ISO strings
    (passthrough), space-separated strings (normalized to ``T`` form),
    ``None`` / empty string (→ ``""``).

    Single edit point for the ``str(x)`` / ``hasattr(x, "isoformat")`` fallback
    pattern previously scattered across FHIR builders (FP-UNIFY-2, 2026-07-07).

    session 48 cycle 8 (feedback FB-F1): TZ 無し文字列には JST (+09:00) を付与。
    """
    if value is None or value == "":
        return ""
    if isinstance(value, (datetime, date)):
        s = value.isoformat()
    else:
        s = str(value)
        if len(s) >= 11 and s[10] == " ":
            s = s[:10] + "T" + s[11:]
    return _append_tz_if_missing(s)


def to_fhir_instant(value: Any) -> str:
    """Normalize to FHIR R4 ``instant`` (秒精度 + TZ 必須).

    ``instant`` is stricter than ``dateTime``: time-of-day and TZ are required.
    Milliseconds recommended. session 48 feedback FB-F1 で導入。
    """
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        s = value.isoformat()
        # ensure seconds present
        if "." not in s.split("T", 1)[1] and s.count(":") == 2:
            pass  # already has seconds
        elif s.count(":") == 1:
            s += ":00"
        return _append_tz_if_missing(s)
    if isinstance(value, date):
        # date-only → make midnight instant with TZ
        return f"{value.isoformat()}T00:00:00{_JST_TZ_SUFFIX}"
    s = str(value)
    if len(s) >= 11 and s[10] == " ":
        s = s[:10] + "T" + s[11:]
    # date-only string → append midnight
    if "T" not in s and len(s) == 10:
        return f"{s}T00:00:00{_JST_TZ_SUFFIX}"
    # ensure seconds present
    if s.count(":") == 1:
        s += ":00"
    return _append_tz_if_missing(s)


def to_fhir_date(value: Any) -> str:
    """Normalize a datetime-like value to a FHIR R4 ``date`` string (YYYY-MM-DD).

    Strips any time component. Accepts ``date`` / ``datetime`` objects, ISO
    strings, space-separated strings, ``None`` / empty string (→ ``""``).
    Companion to :func:`to_fhir_datetime` (FP-UNIFY-2, 2026-07-07).
    """
    if value is None or value == "":
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)[:10]


def _map_encounter_status(status: str) -> str:
    mapping = {
        "planned": "planned",
        "in_progress": "in-progress",
        "completed": "finished",
        "cancelled": "cancelled",
    }
    return mapping.get(status, "unknown")
