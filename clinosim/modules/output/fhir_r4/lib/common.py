"""FHIR R4 shared low-level helpers — public FHIR-builder library (Issue #545).

Leaf-level fragment helpers extracted from ``fhir_r4_adapter`` — each produces a
FHIR *fragment* (a coding, a CodeableConcept, a Dosage, a reference range, a
status code, a Bundle entry) rather than a top-level resource. They depend only
on :mod:`clinosim.codes`, :mod:`clinosim.locale`, and the two leaf reference
modules, so resource-builder modules can import them without an import cycle
back through the adapter facade.

**Public API (Issue #545)**: 69 external importers across ``clinosim/`` and
``tests/`` already treat this module as public. Promoted from
``_fhir_common`` → ``fhir_common`` and ``__all__`` below declares the
supported surface. The underscore-prefixed export names are kept for this
release cycle to make the promotion byte-neutral; a follow-up PR will drop
the ``_`` prefix on the truly-public symbols (see the Issue #545 body for
the rename list).

The deprecated ``_fhir_common`` import path still works via a compatibility
shim in ``clinosim/modules/output/_fhir_common.py`` that emits a
``DeprecationWarning``. Migrate to
``clinosim.modules.output.fhir_r4.lib.common`` (Issue #555 canonical path;
the earlier intermediate ``clinosim.modules.output.fhir_common`` path from
Issue #545 is also removed by this restructure).
"""

from __future__ import annotations

__all__ = [
    # Public dataclass shared by every bundle-builder
    "BundleContext",
    # Fragment builders — resource-shared, used by every profile
    "build_address",
    "build_diagnosis_codeable_concept",
    "build_dosage_instruction",
    "build_reference_range",
    "build_telecom",
    "build_presented_form",
    "build_route_concept",
    "build_ucum_quantity",
    "canonicalize_route",
    # Bundle-entry constructor
    "entry",
    # Status / code mappers
    "map_diagnosis_code",
    "map_encounter_status",
    "map_mar_status",
    # Coding-system helpers (used by both output/ and audit modules)
    "loinc_coding",
    "micro_coding",
    "severity_coding",
    # Cross-profile helpers
    "attach_ecs_institutional_extensions",
    "build_ecs_department_extension",
    "build_ecs_institution_extension",
    "infer_severity",
    "make_participant",
    "survey_category",
    "strip_protocol_prefix",
    # Date / datetime normalisers
    "derive_meta_last_updated",
    "to_fhir_date",
    "to_fhir_datetime",
    "to_fhir_instant",
    "tz_suffix_for_country",
    # Truly-private (kept out of __all__): _parse_dose_for_mar, _sha1_b64,
    # _escape_html, _to_ucum_code, _coding_with_display, _social_category,
    # _value, _validate_route_maps, _append_tz_if_missing, _UCUM_CODE_MAP.
]

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping, load_reference_ranges
from clinosim.modules._shared import is_jp, resolve_lang, strip_protocol_prefix
from clinosim.modules.output.fhir_r4.lib.localization import (
    _CATEGORY_DISPLAY_JA,
    _FREQ_JA,
    _ROUTE_JA,
    _localize_display,
    _localize_dosage_terms,
    _localize_drug_name,
)
from clinosim.modules.output.fhir_r4.lib.reference_data import (
    _JP_CONDITION_SEVERITY_CS,
    _PREFECTURE_CODE,
    _ROUTE_ALIASES,
    _ROUTE_SNOMED,
    _SEVERITY_JP,
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


# Human-readable → UCUM canonical token map (issue #204, 2026-07-17).
#
# fhir-jp-validator 2026-07-17 §【最優先 1】surfaced 6,203 errors on
# MedicationAdministration Quantity.code — UCUM does not accept the informal
# clinical spellings that appear in disease-YAML dose fields
# (`IU`, `mcg`, `u`). We keep the human display as-is on `Quantity.unit`
# (clinicians reading the JSON see the familiar spelling) and map the
# machine `Quantity.code` field to the UCUM canonical form.
#
# Sources for the mapping: UCUM specification §32-35 (Common Units,
# Special Units) at https://ucum.org/ucum#section-Special-Units-On-Non-Ratio-Scales
# — the bracketed forms (`[iU]`, `[meq]`) are the "arbitrary units"
# convention UCUM reserves for quantities defined by biological assay.
# UCUM defines `U` (Unit, uppercase) as a generic enzymatic activity
# unit; the informal lowercase `u` clinicians write for insulin doses
# lands on the same UCUM concept.
#
# Only include tokens that clinosim actually emits (verified against
# the 2026-07-17 validation report). Adding a token that never appears
# is dead code; missing one leaves an error path open. Extension policy:
# add a new token here + a per-token pin test in
# tests/unit/output/test_ucum_code_canonicalization.py.
_UCUM_CODE_MAP: dict[str, str] = {
    "mcg": "ug",  # microgram
    "IU": "[iU]",  # international unit (biological assay)
    "iu": "[iU]",
    "mIU": "m[iU]",
    "u": "U",  # informal insulin unit → UCUM Unit
    "units": "U",
    "unit": "U",
    "mEq": "meq",  # milliequivalent (UCUM arbitrary unit)
    "mmHg": "mm[Hg]",  # ↔ base FHIR canonical for pressure
}


def _to_ucum_code(unit: str) -> str:
    """Return the UCUM canonical code for a clinical unit string.

    Handles both scalar (``mcg``, ``IU``, ``u``) and compound (``mcg/kg``,
    ``IU/L``, ``0.1U/kg/h``) forms by splitting on ``/`` and mapping each
    factor independently; unknown factors are passed through, so ``mg/dL``,
    ``mL/h``, ``mmol/L`` are byte-identical.

    Idempotent — passing an already-canonical form (``[iU]/L``) returns it
    unchanged.
    """
    if not unit:
        return unit
    if "/" not in unit:
        return _UCUM_CODE_MAP.get(unit, unit)
    return "/".join(_UCUM_CODE_MAP.get(p, p) for p in unit.split("/"))


def build_ucum_quantity(value: Any, unit: str) -> dict[str, Any]:
    """Build a FHIR ``Quantity`` (UCUM) with ``value``, ``unit`` (display), and ``code``.

    JP-CLINS ``JP_MedicationAdministration_eCS`` (and related eCS profiles) declare
    ``Quantity.code`` as ``min=1`` bound to UCUM; the FHIR-R4 UCUM idiom is that
    ``unit`` carries the human-readable label and ``code`` carries the machine
    UCUM token. Most clinical unit strings used by clinosim (``mg`` / ``mL`` /
    ``g/dL`` / ``mL/h`` / ``mmol/L`` / ``U/L`` ...) are already valid UCUM
    tokens, so ``unit`` and ``code`` end up identical; ``_to_ucum_code``
    handles the small set of informal spellings (``mcg`` → ``ug``,
    ``IU`` → ``[iU]``, ``u`` → ``U``, ``mEq`` → ``meq``, ``mmHg`` →
    ``mm[Hg]``) that UCUM rejects.

    Introduced (2026-07-16, PR-A) so every UCUM Quantity site — MA.dose,
    MA.rateQuantity, MR.dosageInstruction[].doseAndRate[].doseQuantity,
    Observation.referenceRange.low/high — goes through one edit point.
    Extended (2026-07-17, issue #204) with the ``_UCUM_CODE_MAP``
    normalization to close the remaining 6,203 unknown-code errors from
    the fhir-jp-validator 2026-07-17 report §【最優先 1】.
    """
    q: dict[str, Any] = {"value": value, "system": get_system_uri("ucum")}
    if unit:
        q["unit"] = unit
        q["code"] = _to_ucum_code(unit)
    return q


# --------------------------------------------------------------------------- #
# JP-CLINS eCS institutional-attribution extensions (Issue #743).
#
# `JP_eCS_InstitutionNumber` and `JP_eCS_Department` are must-support on the
# JP-CLINS eCS profiles for Condition, AllergyIntolerance, MedicationRequest,
# and Patient (InstitutionNumber only — the Department extension's context
# excludes Patient). Their absence on eCS-profile-declaring resources
# violates the memory rule
# `[★★★★ Profile assertion は data-completeness verify 後]`.
#
# Extension URLs / systems come from the authoritative SDs:
#   - StructureDefinition-jp-ecs-institution-number.json
#   - StructureDefinition-jp-ecs-department.json
# InstitutionNumber.value[x] type = Identifier; the Identifier.system for the
# 10-digit medical-institution code is the same URI used by the facility
# builder's `hospital-main.identifier:medicalInstitutionCode` (Issue #746).
#
# Placeholder policy: hospital_config carries no institutional code or per-
# encounter department name today, so both extensions carry synthetic
# placeholders. Downstream Issues will thread real values from encounter
# context once hospital_config gains those fields.
_JP_ECS_INSTITUTION_NUMBER_EXT_URL = (
    "http://jpfhir.jp/fhir/clins/Extension/StructureDefinition/JP_eCS_InstitutionNumber"
)
_JP_ECS_DEPARTMENT_EXT_URL = "http://jpfhir.jp/fhir/eCS/Extension/StructureDefinition/JP_eCS_Department"
_JP_ECS_INSTITUTION_ID_SYSTEM = "http://jpfhir.jp/fhir/core/IdSystem/insurance-medical-institution-no"
_JP_ECS_INSTITUTION_PLACEHOLDER = "1300000000"
_JP_ECS_DEPARTMENT_PLACEHOLDER = "総合診療科"


def build_ecs_institution_extension() -> dict[str, Any]:
    """Return the `JP_eCS_InstitutionNumber` extension for JP eCS resources.

    Value is the fixed 10-digit institutional-code placeholder — same as
    `hospital-main.identifier:medicalInstitutionCode`. Callers gate on JP.
    """
    return {
        "url": _JP_ECS_INSTITUTION_NUMBER_EXT_URL,
        "valueIdentifier": {
            "system": _JP_ECS_INSTITUTION_ID_SYSTEM,
            "value": _JP_ECS_INSTITUTION_PLACEHOLDER,
        },
    }


def build_ecs_department_extension(department_text: str = "") -> dict[str, Any]:
    """Return the `JP_eCS_Department` extension for JP eCS resources.

    `department_text` is the department display name; falls back to the
    「総合診療科」placeholder when the caller cannot determine one from
    encounter context. Callers gate on JP.
    """
    text = department_text or _JP_ECS_DEPARTMENT_PLACEHOLDER
    return {
        "url": _JP_ECS_DEPARTMENT_EXT_URL,
        "valueCodeableConcept": {"text": text},
    }


def attach_ecs_institutional_extensions(
    resource: dict[str, Any],
    country: str,
    department_text: str = "",
    include_department: bool = True,
) -> None:
    """Append the two JP-CLINS eCS institutional-attribution extensions to
    ``resource["extension"]`` on JP output. No-op on US output. Idempotent:
    skips either extension whose URL is already present so re-application
    (e.g. from a post-hook after the builder) does not duplicate.

    Set ``include_department=False`` for Patient (the Department extension's
    context excludes Patient per its SD).
    """
    if not is_jp(country):
        return
    exts = resource.setdefault("extension", [])
    if not isinstance(exts, list):
        return
    existing = {e.get("url") for e in exts if isinstance(e, dict)}
    if _JP_ECS_INSTITUTION_NUMBER_EXT_URL not in existing:
        exts.append(build_ecs_institution_extension())
    if include_department and _JP_ECS_DEPARTMENT_EXT_URL not in existing:
        exts.append(build_ecs_department_extension(department_text))


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
    (wraps as full CodeableConcept), ``loinc_coding()`` (LOINC-specialized),
    ``build_diagnosis_codeable_concept()`` (multi-language dx codes).

    C2-01/02/03/05/06/07/08 — migrated the display-fallback
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
# churn on unrelated call sites (cycle 2).
micro_coding = _coding_with_display


def survey_category() -> list[dict]:
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


def loinc_coding(code: str, lang: str) -> dict:
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
    — distinct from micro_coding() in this module which returns the
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


def entry(resource: dict) -> dict:
    """Wrap a resource as a Bundle entry."""
    rid = resource.get("id", str(uuid.uuid4()))
    resource.get("resourceType", "Resource")
    return {
        "fullUrl": f"urn:uuid:{rid}",
        "resource": resource,
    }


def build_diagnosis_codeable_concept(code: str, system_key: str, country: str) -> dict[str, Any]:
    """Build a FHIR CodeableConcept for a diagnosis code with multilingual coding.

    - Primary coding: target country's system + target language display
    - Secondary coding: English display (for interop) — SKIPPED when the
      primary system is Japanese-only (Issue #358): MHLW ICD-10 2013 and
      similar registries publish only a Japanese display per concept, so an
      English display against the same system URI can never match the
      authoritative CS and would produce a validator display-mismatch
      error. Consumers wanting the English string should read
      ``code.text`` (in JA locales that is the JA short name) or look up
      via ``clinosim.codes.lookup(system_key, code, "en")`` themselves.
    - code.text: primary language display (local charting expression)
    - Never emits display==code: falls back to "(display unavailable)"

    Falls back to icd-10-cm lookup if the code isn't in the country's system
    (e.g. JP using icd-10 but code only in icd-10-cm).

    code.text is set to a clinical short-name / abbreviation when available
    (e.g. "COPD" instead of "Other chronic obstructive pulmonary disease"),
    enabling search by common clinical abbreviations.
    """
    from clinosim.codes.loader import is_japanese_only_display_system

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
    # Add English coding for multilingual interop when primary is not English.
    # Skip for Japanese-only registries (Issue #358) — see docstring.
    if primary_lang != "en" and en_display != primary_display and not is_japanese_only_display_system(system_key):
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


def map_diagnosis_code(code: str, country: str) -> str:
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
    country_code = "JP" if is_jp(country) else "US"
    return load_code_mapping("diagnosis", country_code).get(code, code)


def infer_severity(record: dict) -> str:
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


def severity_coding(severity: str, country: str = "US") -> dict[str, Any]:
    """Build FHIR Condition.severity CodeableConcept from severity string.

    iris4h-ai feedback F-4:JP output では JP_ConditionSeverity_CS
    (`MI` / `MO` / `SE`)を primary coding、SNOMED を secondary(国際互換性
    のため保持)として emit。US output は従来通り SNOMED 単独。
    """
    sev = severity.lower()
    _snomed_map = _SEVERITY_SNOMED.get(sev) or _SEVERITY_SNOMED.get("moderate") or {}
    snomed = dict(_snomed_map)
    if is_jp(country):
        # JP: JP CS primary + SNOMED secondary(SNOMED は英語 display のまま
        # 保持 = 標準の英語 display と一致)。fallback は moderate(既存挙動と
        # 同一)。JP CS の display は spec 準拠(`中度`、`中等度` ではない)。
        _jp_map = _SEVERITY_JP.get(sev) or _SEVERITY_JP.get("moderate") or {}
        jp_coding = {
            "system": _JP_CONDITION_SEVERITY_CS,
            **_jp_map,
        }
        snomed_coding = {
            "system": get_system_uri("snomed-ct"),
            **snomed,
        }
        return {
            "coding": [jp_coding, snomed_coding],
            "text": jp_coding.get("display", ""),
        }
    # US: SNOMED single coding
    return {
        "coding": [
            {
                "system": get_system_uri("snomed-ct"),
                **snomed,
            }
        ],
        "text": snomed.get("display", ""),
    }


def build_address(addr: dict, country: str) -> dict[str, Any] | None:
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
        # C4-13: Address.use = "home" per FHIR R4 spec.
        # JP Core Patient guidance mirrors HL7 R4: use should be populated
        # (was implicit "?"/missing, 100% of Patient.address records).
        "use": "home",
        "type": "both",
        # Issue #378: JP_Patient_eCS requires `address.text` (min=1). Only
        # emit on JP so US Patient.address stays byte-clean (US doesn't
        # assert eCS and adding `text` there would be an unrelated diff).
        # JP `line` already carries the concatenated 都道府県+市区町村+番地
        # form, which is exactly what `text` should hold.
        **({"text": line} if line and is_jp(country_code) else {}),
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
    # Issue #343: FHIR R4 Attachment.contentType の required
    # binding は IANA Media Types (urn:ietf:bcp:13) で bare mime type のみ。
    # HTTP Content-Type header の charset parameter は VS 外 → "text/plain"
    # bare で emit(UTF-8 は FHIR default 前提、semantic loss なし)。
    return [
        {
            "contentType": "text/plain",
            "language": lang,
            "data": encoded,
            "title": title,
            "size": len(text.encode("utf-8")),
            "hash": base64.b64encode(h).decode("ascii"),
        }
    ]


def build_telecom(contact: dict) -> list[dict[str, str]]:
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


def make_participant(code: str, display: str, practitioner_id: str, country: str = "US") -> dict[str, Any]:
    """Build an Encounter.participant entry.

    C5-02: localize `display` for JP output — HL7
    v3-ParticipationType English default (attender / admitter / discharger)
    was leaking to JP output as literal text.
    """
    from clinosim.modules.output.fhir_r4.lib.localization import (
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


def build_route_concept(raw_route: str | None, country: str) -> dict[str, Any] | None:
    """Build the FHIR route `CodeableConcept` for a raw route value, or None if absent.

    SINGLE lookup point for route → SNOMED across every FHIR builder (Issue #458).
    Two independent `_ROUTE_SNOMED.get(...)` sites previously existed — one in
    `build_dosage_instruction` (MedicationRequest) and one in `_build_medication_admin`
    (MedicationAdministration) — and the same missing-alias defect landed on both,
    producing 166 text-only elements on the MAR path versus 6 on the MR path. Anything
    reading a route MUST come through here; `tests/unit/output/
    test_fhir_route_alias_resolution.py` fails if a builder reaches for `_ROUTE_SNOMED`
    again. Sibling of the `classify_lab_specs` / `scenario_flags_from_protocol`
    single-edit-point pattern.

    `country` is REQUIRED (no default). A default was previously "US" and one call site
    (`build_dosage_instruction` internal) failed to forward it, silently emitting the
    US `text` form on JP output — the same J5 pattern PR #475 fixed in
    `MedicationAdministration.dosage.text`. `TypeError` at call time is preferable to
    silent locale drift.

    Resolution order: canonical key, then `_ROUTE_ALIASES` (author abbreviations such as
    `INH` / `NEB`). Case is normalised here so call sites do not each carry `.upper()`.
    The JA lookup uses the CANONICAL form, so `INHALATION` (alias) → `INHALED`
    (canonical) → `"吸入"`, not a raw miss.

    `text` field adheres to dual-slot rule (Issue #479):
    - JP (country="JP"): localized to Japanese via `_ROUTE_JA` lookup on the canonical
      form, following the pattern of Observation.code and Procedure.code
    - US (country="US"): keeps the author's own wording (upper-cased abbreviation)
    `CodeableConcept.text` is where the source system's representation belongs, while
    `coding` carries the standard meaning.

    An unresolvable route yields `{"text": text_value}` with no `coding`. That is
    deliberate: routes needing a NEW SNOMED code (`NASAL`, `NG`, `CATHETER`, …) must be
    verified per-code against an authoritative terminology server, never aliased onto
    a nearby code — see the note on `_ROUTE_ALIASES`. The `text` is still localized for
    JP so `NG` reads `経鼻` in JP output rather than the English abbreviation.

    Note: no `.strip()`. Behaviour is intentionally byte-identical to the two call sites
    it replaces so the PR's diff is confined to alias resolution; whitespace-padded route
    values do not occur in the corpus.
    """
    route = (raw_route or "").upper()
    if not route:
        return None
    canonical = _ROUTE_ALIASES.get(route, route)
    snomed = _ROUTE_SNOMED.get(canonical)
    text_value = route
    if is_jp(country):
        text_value = _ROUTE_JA.get(canonical, route)
    if snomed:
        return {
            "coding": [{"system": get_system_uri("snomed-ct"), **snomed}],
            "text": text_value,
        }
    return {"text": text_value}


def canonicalize_route(raw_route: str | None) -> str:
    """Return the canonical `_ROUTE_SNOMED` key for a raw route (upper + alias-resolved).

    Same normalization `build_route_concept` performs internally, exposed as a helper
    for downstream code that needs to gate behavior on the canonical route WITHOUT
    going through the CodeableConcept builder.

    Motivating call site: `_build_medication_admin`'s infusion-pump gate
    (`_is_infusion = canonical == "IV" and ...`). Comparing the raw upper form is
    fragile — adding an alias like `INTRAVENOUS: "IV"` to `_ROUTE_ALIASES` would
    silently break the gate (raw `INTRAVENOUS` != `"IV"`), losing every
    `resource["device"]` reference on IV continuous infusions. Same J5 pattern this
    PR is fixing elsewhere — the gate must resolve the alias first.

    Returns the upper-cased raw route when there is no alias mapping (canonical routes
    like `IV`, `PO`, SNOMED-less specials like `NG`, and truly unknown routes like
    `CATHETER` all return themselves). Empty / None inputs return `""` — the caller
    decides how to handle absence, consistent with `build_route_concept` returning
    `None` for the same case.

    Isolating this in `_fhir_common` keeps the "route maps are looked up in exactly
    one module" rule (test_no_builder_reads_the_route_maps_directly) — call sites
    import the helper, not the underlying tables.
    """
    route = (raw_route or "").upper()
    if not route:
        return ""
    return _ROUTE_ALIASES.get(route, route)


def _validate_route_maps() -> None:
    """Reverse-coverage guard for the route lookup tables (import-time).

    Same silent-no-op class as PR #90 — see `_validate_narrow_ladder` / `_validate_hai_*`
    for sibling shape. Two invariants:

    1. `_ROUTE_JA.keys() ⊇ _ROUTE_SNOMED.keys()` — every canonical SNOMED route MUST
       have a JP translation. A new `_ROUTE_SNOMED` entry without a companion
       `_ROUTE_JA` entry would silently emit the English canonical on JP output.
    2. `_ROUTE_JA.keys() ∩ _ROUTE_ALIASES.keys() == ∅` — aliases are resolved to
       canonical BEFORE the JA lookup, so an alias entry in `_ROUTE_JA` is dead
       (never reached) and misleads authors into thinking coverage exists.
    """
    missing_ja = set(_ROUTE_SNOMED.keys()) - set(_ROUTE_JA.keys())
    if missing_ja:
        raise ValueError(f"_ROUTE_JA missing JP translation for canonical SNOMED routes: {sorted(missing_ja)}")
    alias_in_ja = set(_ROUTE_JA.keys()) & set(_ROUTE_ALIASES.keys())
    if alias_in_ja:
        raise ValueError(
            f"_ROUTE_JA contains alias keys — resolve via _ROUTE_ALIASES to canonical first: {sorted(alias_in_ja)}"
        )


_validate_route_maps()


def build_dosage_instruction(order: dict, country: str = "US") -> dict[str, Any] | None:
    """Build FHIR Dosage from structured order fields."""
    dose_qty = order.get("dose_quantity")
    dose_unit = order.get("dose_unit", "")
    freq = order.get("frequency", "")
    freq_per_day = order.get("frequency_per_day")
    route_concept = build_route_concept(order.get("route"), country)
    # `text` is the localized (JP) or authored (US) route form used only for the dosage
    # text summary block below (line 670+). The JP text summary path re-derives the JA
    # form via `_ROUTE_JA.get(p_upper)`, so a JA `route` here fails that lookup and
    # falls back to `p` (itself already JA) — net-safe.
    route = route_concept["text"] if route_concept else ""

    # Issue #476: when the disease author wrote a localized dose instruction
    # (`dose_ja` / `dose_en` on the YAML entry → `dose_text_ja` / `dose_text_en`
    # on the Order), emit it as the dosage text even when structured fields
    # are empty. This is DIFFERENT from the Issue #467 defect (which stuffed
    # `display_name` into `Dosage.text` — the drug name, not the dosage):
    # `dose_text_{ja,en}` carries an authored dose instruction that is exactly
    # what belongs in `Dosage.text` when the dose is a clinical instruction
    # rather than a numeric expression (e.g. "以前の吸入薬を再開または新規開始"
    # for `ICS/LABA inhaler` step-up-after-exacerbation).
    dose_text_ja = str(order.get("dose_text_ja", "") or "")
    dose_text_en = str(order.get("dose_text_en", "") or "")
    authored_text = dose_text_ja if is_jp(country) else dose_text_en

    # If nothing structured is available, return None so the caller omits
    # `dosageInstruction`. Issue #467: the previous fallback stuffed the
    # Order's `display_name` (drug name, e.g. "Atorvastatin 10mg") into
    # `Dosage.text`. That is wrong on two counts:
    #  (1) `medicationCodeableConcept.text` already carries the drug name;
    #      duplicating it into the dosage field misrepresents "dosage".
    #  (2) The fallback was not localized — a JP MedicationRequest emitted
    #      via this path would leak an English drug string into JP output.
    # "空欄は無知、誤った断言は虚偽" (feedback_empty_vs_wrong_assertion):
    # a missing dosageInstruction is correct when we have no dosage
    # information, unlike inventing one from the drug name.
    #
    # BUT if the author provided an explicit country-scoped instruction (via
    # `dose_text_{ja,en}` — Issue #476), emit it as a text-only dosage even
    # when structured fields are absent.
    if dose_qty is None and not freq and not route:
        if authored_text:
            return {"text": authored_text}
        return None

    dosage: dict[str, Any] = {}
    parts = []

    # Dose quantity — route through build_ucum_quantity so `code` is populated
    # (JP-CLINS eCS profiles require it).
    if dose_qty is not None and dose_unit:
        dosage["doseAndRate"] = [
            {
                "doseQuantity": build_ucum_quantity(dose_qty, dose_unit),
            }
        ]
        # Issue #781: `dosageInstruction[].text` is human-readable, so drop
        # the trailing `.0` on integer-valued dose floats (`4mg` not `4.0mg`).
        # `doseQuantity.value` is unaffected — it is a JSON number and both
        # `4.0` and `4` serialize the same. `text` is the only site where
        # `.0` leaks into the rendered UI.
        _dose_txt = f"{int(dose_qty)}" if isinstance(dose_qty, float) and dose_qty.is_integer() else f"{dose_qty}"
        parts.append(f"{_dose_txt}{dose_unit}")

    # Route
    if route_concept:
        dosage["route"] = route_concept
        parts.append(route)

    # Timing
    # C4-16: derive freq_per_day from common freq
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

    # session-88j P2-5b: Dosage.patientInstruction — derived from
    # frequency label (qhs → 就寝前, ac → 食前, pc → 食後, prn → 頓用) so
    # consumers get an actionable Japanese instruction rather than the
    # bare structured timing.repeat. Explicit CIF-authored
    # `patient_instruction` on the Order (Issue #476 opt-in pattern)
    # takes precedence over the derived phrase.
    _authored_instr = str(order.get("patient_instruction", "") or "")
    _derived_instr = ""
    if freq:
        _flow_instr = freq.lower().strip()
        _flow_instr_orig = str(freq).strip()  # JA has no case
        if is_jp(country):
            _instr_ja = {
                # EN abbreviations (kept for interop when CIF passes en-freq)
                "qhs": "就寝前",
                "bedtime": "就寝前",
                "at bedtime": "就寝前",
                "hs": "就寝前",
                "ac": "食前",
                "before meal": "食前",
                "before meals": "食前",
                "pc": "食後",
                "after meal": "食後",
                "after meals": "食後",
                "qam": "朝食後",
                "qpm": "夕食後",
                "prn": "頓用（必要時）",
                "as needed": "頓用（必要時）",
                "when required": "頓用（必要時）",
                # session-88j v14 review — CIF Order.frequency is the primary
                # source (dosage.text carries the derived JA "1日1回" only
                # after `_derive_usage_display_from_timing` post-processing).
                # Map the primary EN freq strings so patientInstruction is
                # populated at emit time.
                "qd": "毎日1回、指示された時間帯に内服してください",
                "q24h": "毎日1回、指示された時間帯に内服してください",
                "once daily": "毎日1回、指示された時間帯に内服してください",
                "daily": "毎日1回、指示された時間帯に内服してください",
                "1x/day": "毎日1回、指示された時間帯に内服してください",
                "bid": "毎日2回、朝・夕の指示された時間帯に内服してください",
                "q12h": "12時間ごとに内服してください",
                "twice daily": "毎日2回、朝・夕の指示された時間帯に内服してください",
                "2x/day": "毎日2回、朝・夕の指示された時間帯に内服してください",
                "tid": "毎日3回、朝・昼・夕の指示された時間帯に内服してください",
                "q8h": "8時間ごとに内服してください",
                "three times daily": "毎日3回、朝・昼・夕の指示された時間帯に内服してください",
                "3x/day": "毎日3回、朝・昼・夕の指示された時間帯に内服してください",
                "qid": "毎日4回、指示された時間帯に内服してください",
                "q6h": "6時間ごとに内服してください",
                "four times daily": "毎日4回、指示された時間帯に内服してください",
                "4x/day": "毎日4回、指示された時間帯に内服してください",
                "q4h": "4時間ごとに内服してください",
                "q3h": "3時間ごとに内服してください",
                "q2h": "2時間ごとに内服してください",
                # And the derived JA display forms (for callers that pass those).
                "1日1回": "毎日1回、指示された時間帯に内服してください",
                "1日2回": "毎日2回、朝・夕の指示された時間帯に内服してください",
                "1日3回": "毎日3回、朝・昼・夕の指示された時間帯に内服してください",
                "1日4回": "毎日4回、指示された時間帯に内服してください",
                "6時間ごと": "6時間ごとに内服してください",
                "8時間ごと": "8時間ごとに内服してください",
                "12時間ごと": "12時間ごとに内服してください",
                "頓服": "症状のある時にのみ服用してください",
                "頓用": "症状のある時にのみ服用してください",
            }
            # Prefer JA-key lookup (case preserved), fall back to lowercased for EN.
            _derived_instr = _instr_ja.get(_flow_instr_orig, "") or _instr_ja.get(_flow_instr, "")
        else:
            _instr_en = {
                "qhs": "at bedtime",
                "bedtime": "at bedtime",
                "hs": "at bedtime",
                "ac": "before meals",
                "pc": "after meals",
                "prn": "as needed",
                "as needed": "as needed",
            }
            _derived_instr = _instr_en.get(_flow_instr, "")
    final_instr = _authored_instr or _derived_instr
    if final_instr:
        dosage["patientInstruction"] = final_instr

    # Text summary
    # Issue #476: when the disease author provided an explicit country-scoped
    # instruction, it wins over the auto-derived summary. This is intentional:
    # for instruction-only doses (e.g. "以前の吸入薬を再開または新規開始")
    # the authored text carries the clinical meaning the summary cannot
    # reconstruct from route + frequency alone.
    if authored_text:
        dosage["text"] = authored_text
    elif parts:
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
strip_protocol_prefix = strip_protocol_prefix


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


def build_reference_range(
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

    # NOTE: `ref_data["source_url"]` was previously read into a
    # `referenceRangeSource` extension per range; the extension has been
    # dropped (#202). The YAML field is kept for provenance/audit trails
    # but is not surfaced in the FHIR output.
    result: list[dict[str, Any]] = []

    for entry in ranges:
        sex = entry.get("sex")
        # If sex-specific, only include the matching range (or both if sex unknown)
        if sex and patient_sex and sex != patient_sex:
            continue

        rr: dict[str, Any] = {}
        unit_str = entry.get("unit", "")
        if entry.get("low") is not None:
            rr["low"] = build_ucum_quantity(entry["low"], unit_str)
        if entry.get("high") is not None:
            rr["high"] = build_ucum_quantity(entry["high"], unit_str)
        if entry.get("text"):
            rr["text"] = entry["text"]

        # appliesTo for sex-specific ranges
        if sex:
            # C2-05: resolve display via codes/data/hl7-v3-
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

        # `referenceRangeSource` extension は emit しない。
        # fhir-jp-validator 2026-07-17 §【最優先 2】(31k errors)で以下 2 点が
        # 判明:
        # (1) 過去 clinosim 版が使っていた URL(fragment 版 → 現行 spec 準拠版
        #     どちらも)は JP Core 1.2.0 / JP-CLINS 1.12.0 / jpfhir-terminology
        #     2.2606.0 のいずれの StructureDefinition にも存在しない
        #     (`grep -rl 'ReferenceRangeSource' fhir-jp-validator/tx-server-build/...`
        #      で match ゼロ)。spec fixedUri 直接引用 rule違反。
        # (2) `JP_Observation_LabResult_eCS` は `Observation.referenceRange.
        #     extension max=0` を定めており、たとえ spec-valid URL でも profile
        #     で禁止される。
        # source_url 情報は JP-CLINS の slot が無いため、entirely drop する。
        # ここで emit しない + `_strip_forbidden_observation_reference_range_extensions`
        # walker(fhir_r4_adapter)で defensive 除去、の 2 重防御。
        result.append(rr)

    return result if result else None


def map_mar_status(status: str) -> str:
    return {"given": "completed", "held": "on-hold", "refused": "not-done", "not_available": "not-done"}.get(
        status, "completed"
    )  # noqa: E501


# cycle 8 拡張 (feedback FB-F1):
# JP コホートの dateTime / instant field は JST (+09:00) を必ず付与する。
# HAPI FHIR Validator (JP Core 準拠) は TZ 無し dateTime を regex エラーとする。
# to_fhir_datetime + to_fhir_instant で単一 seam 化、per-builder 個別修正回避。
_JST_TZ_SUFFIX = "+09:00"
# Issue #570 convention: non-JP cohorts append UTC (`Z`) as the neutral default.
# Once locale-aware US time modelling lands, this may switch to a US-specific
# suffix (e.g. `-05:00` for America/New_York); callers still route through
# `tz_suffix_for_country(country)` so the change is a one-constant edit.
_UTC_TZ_SUFFIX = "Z"


def tz_suffix_for_country(country: str) -> str:
    """Canonical timezone suffix for the country's FHIR datetime / instant fields.

    JP → `+09:00` (JST); anything else → `Z` (UTC). Callers use this instead of
    hardcoding a TZ suffix so US cohorts do not silently emit JST timestamps
    (Issue #570 locale-gate convention).
    """
    return _JST_TZ_SUFFIX if is_jp(country) else _UTC_TZ_SUFFIX


def _append_tz_if_missing(s: str) -> str:
    """ISO 8601 datetime string に TZ が無ければ ``+09:00`` (JST) を付与。

    Historical helper: builders unconditionally append JST here. The post-emit
    walker (:func:`clinosim.modules.output.fhir_r4.post_process._normalize_dt_fields`)
    rewrites the suffix per-country afterwards (Issue #570 locale gate), so US
    cohorts do not retain JST in their final output.

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

    cycle 8 (feedback FB-F1): TZ 無し文字列には JST (+09:00) を付与。
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
    Milliseconds recommended. feedback FB-F1 で導入。
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
        # date-only → make midnight instant with JST (post-process walker
        # rewrites for non-JP cohorts per Issue #570).
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


def map_encounter_status(status: str) -> str:
    mapping = {
        "planned": "planned",
        "in_progress": "in-progress",
        "completed": "finished",
        "cancelled": "cancelled",
    }
    return mapping.get(status, "unknown")


def derive_meta_last_updated(resource: dict, prefer: tuple[str, ...]) -> str | None:
    """Canonical fallback resolver for FHIR ``Resource.meta.lastUpdated`` (Issue #549).

    Walks ``prefer`` field paths in order and returns the first non-empty value.
    Supports dotted paths for nested lookups (e.g. ``"effectivePeriod.end"``).
    Returns ``None`` when no field yields a value — callers may then apply a
    secondary fallback (bundle-context timestamp, doc-source datetime, etc.).

    Six emit sites populated ``meta.lastUpdated`` with five distinct hardcoded
    fallback chains before this helper; new resource types had no canonical
    pattern to follow. The chain is now expressed as a tuple at each call site
    and the traversal shares one implementation.
    """
    for path in prefer:
        cur: Any = resource
        for part in path.split("."):
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(part)
        if cur:
            return cur
    return None


# Issue #545 Step 3 backward-compat aliases were removed in Step 4
# (this PR). All in-tree callers use the unprefixed public names above.
