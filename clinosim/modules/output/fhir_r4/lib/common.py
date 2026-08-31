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
    "augment_iv_dosage_with_rate",
    "resolve_iv_infusion_default",
    # Bundle-entry constructor
    "entry",
    # Status / code mappers
    "map_diagnosis_code",
    "iter_diagnosis_mapping_targets",
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

import re
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
    # Issue #925: populated by `_build_bundle` right before the Composition
    # builders run — index of already-emitted resources bucketed by encounter
    # id and resourceType. Consumers (`_bb_compositions` +
    # `_bb_imaging_report_compositions`) use it to populate
    # `Composition.section[].entry[]` with references to the encounter's
    # MedicationRequests / Observations / Procedures / Conditions / ServiceRequests
    # / DiagnosticReports. Shape:
    #   {encounter_id: {resourceType: [{"reference": "…/id", "display": "…"?}, …]}}
    # `None` when the caller has not run the pre-composition indexing pass
    # (unit-tests exercising a single builder in isolation).
    encounter_resource_index: dict[str, dict[str, list[dict[str, str]]]] | None = None
    # Issue #944: simulation snapshot date (YYYY-MM-DD) from cif/metadata.json,
    # read once by `convert_cif_to_fhir` and threaded through so
    # `_build_coverage_resources` can decide Coverage.status per FY row
    # (active vs cancelled). None when the CIF has no metadata.json
    # (identity-only tests, non-standard callers) — builders MUST fall
    # back to their pre-#944 defaults in that case.
    snapshot_date: str | None = None


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


def map_diagnosis_code(code: str, country: str, sex: str = "") -> str:
    """Translate an internal chronic/history diagnosis base code to its locale code.

    US maps internal category/WHO codes (I50, E78, I21, ...) to billable ICD-10-CM
    leaves; JP maps identity (WHO ICD-10 category codes are valid as-is). Codes absent
    from the locale map pass through unchanged — disease primary diagnoses are already
    specific (e.g. I21.9, A41.9) and stay untouched. See locale/<c>/code_mapping_diagnosis.

    Sex-conditional targets (Issue #957): a mapping value may be a dict of the
    form ``{default: "<code>", by_sex: {F: "<code>", M: "<code>"}}`` when the
    ICD-10-CM leaf splits by patient sex (currently only C50 breast cancer,
    which resolves to ``C50.919`` for female patients and ``C50.929`` for
    male patients). Pass ``sex`` at every per-person call site; callers that
    omit it get the ``default`` target (which for C50 is the female leaf,
    the ~99 %-of-cases pick).

    Dedup is intentionally done on the *internal* base code by the caller, not on the
    mapped code, so a current acute MI (primary I21.9) still suppresses a duplicate
    "old MI" chronic entry rather than emitting both.
    """
    if not code:
        return code
    country_code = "JP" if is_jp(country) else "US"
    target = load_code_mapping("diagnosis", country_code).get(code, code)
    if isinstance(target, dict):
        by_sex = target.get("by_sex") or {}
        sex_norm = (sex or "").upper()[:1]  # "F"/"M"/"" — first char, case-fold
        if sex_norm in ("F", "M") and sex_norm in by_sex:
            return str(by_sex[sex_norm])
        return str(target.get("default", code))
    return target


def iter_diagnosis_mapping_targets(country: str) -> list[str]:
    """Flatten every billable target in the country's diagnosis mapping.

    ``load_code_mapping("diagnosis", …)`` returns a ``dict[str, str | dict]``
    since Issue #957 introduced sex-conditional entries. Callers that need
    to enumerate every possible mapped code (validation tests, display-
    coverage sweeps) must walk both the plain string values and the
    ``by_sex`` / ``default`` leaves of the dict values.
    """
    country_code = "JP" if is_jp(country) else "US"
    out: list[str] = []
    for value in load_code_mapping("diagnosis", country_code).values():
        if isinstance(value, dict):
            default = value.get("default")
            if default is not None:
                out.append(str(default))
            for leaf in (value.get("by_sex") or {}).values():
                out.append(str(leaf))
        else:
            out.append(str(value))
    return out


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


# Issue #848: `Dosage.patientInstruction` template families, keyed by
# clinical administration route. Prior emit used a single oral-specific
# template ("毎日1回、指示された時間帯に内服してください") for every route
# — 33% of populated PI on the JP p=10000 s500 sample carried a
# non-oral route while asserting "内服" in the same resource (saline
# 100% wrong at 838 records). Each entry below produces the correct
# JA phrase for its route family; unknown routes yield None so
# `patientInstruction` is omitted (FHIR cardinality 0..1) rather than
# emitted with a value contradicting the resource's own `route.text`.
#
# Route markers are matched against the localized ``route`` string
# (``route.text`` after ``build_route_concept`` — Japanese for JP
# output). Matching is substring-based so composite tokens like
# "IV drip" / "点滴静注" both resolve to the parenteral verb.
_PI_ROUTE_FAMILIES_JA: tuple[tuple[tuple[str, ...], str], ...] = (
    # Parenteral (nurse-administered under physician orders)
    (
        (
            "静注",
            "点滴",
            "皮下注",
            "皮下",
            "筋注",
            "筋肉内",
            "静脈",
            "IV",
            "IV DRIP",
            "DRIP",
            "IM",
            "SC",
            "SQ",
            "SUBCUT",
            "SUBCUTANEOUS",
            "INTRAMUSCULAR",
            "INTRAVENOUS",
            "INFUSION",
        ),
        "医師の指示のもと、看護師が投与します",
    ),
    # Inhalation
    (
        ("吸入", "ネブライザー", "ネブライザ", "INH", "INHALATION", "INHALE", "NEB", "NEBULIZER"),
        "指示された方法で吸入してください",
    ),
    # Sublingual (patient-administered but under-tongue, not swallowed)
    (("舌下", "SL", "SUBLINGUAL"), "指示された時に舌下に投与してください"),
    # Rectal
    (("直腸", "坐薬", "座薬", "PR", "RECTAL", "SUPPOSITORY"), "指示された時間に直腸内に挿入してください"),
    # Transdermal patch
    (("貼付", "パッチ", "TRANSDERMAL", "PATCH", "TDS"), "指示された部位に貼付してください"),
    # Topical ointment / cream / external
    (("塗布", "外用", "軟膏", "TOPICAL", "TOP", "OINTMENT", "CREAM"), "指示された部位に塗布してください"),
    # Eye drop
    (("点眼", "OPHTH", "OPHTHALMIC", "EYE"), "指示された時間に点眼してください"),
    # Nasal drop / spray
    (("点鼻", "NASAL", "NAS"), "指示された時間に点鼻してください"),
    # Enteral / NG / gastrostomy tube (not oral swallowing, but does go through GI)
    (("経腸", "経管", "NG", "NASOGASTRIC", "PEG", "ENTERAL"), "看護師が経管より投与します"),
    # Oral (swallowed) — last so more-specific markers above win first
    (("経口", "内服", "PO", "ORAL", "BY MOUTH"), "毎日{freq_ph}指示された時間帯に内服してください"),
)


# Interval-based frequency labels → JA phrase (no `毎日` prefix). These
# are route-independent when composed with the appropriate verb, so we
# check them BEFORE the route dispatch and append the route verb
# afterwards.
_INTERVAL_FREQ_PREFIX_JA: dict[str, str] = {
    "6時間ごと": "6時間ごとに",
    "8時間ごと": "8時間ごとに",
    "12時間ごと": "12時間ごとに",
    "q2h": "2時間ごとに",
    "q3h": "3時間ごとに",
    "q4h": "4時間ごとに",
    "q6h": "6時間ごとに",
    "q8h": "8時間ごとに",
    "q12h": "12時間ごとに",
}


def _resolve_patient_instruction_ja(route: str, freq: str, freq_per_day: int | None) -> str:
    """Return a route-appropriate JA ``patientInstruction`` string.

    Issue #848: chooses the phrasing template from
    ``_PI_ROUTE_FAMILIES_JA`` based on the localized route string, then
    composes a frequency phrase for oral routes. Returns ``""`` when
    the route family is unknown — the caller drops
    ``patientInstruction`` rather than emit a template that would
    contradict the resource's own ``route.text``.
    """
    route_txt = (route or "").strip()
    if not route_txt:
        return ""
    freq_orig = str(freq or "").strip()
    freq_key = freq_orig.lower()
    # Resolve freq → per-day integer for both EN and JA labels.
    pd = freq_per_day
    if pd is None:
        if freq_key in ("qd", "q24h", "once daily", "daily", "1x/day") or freq_orig == "1日1回":
            pd = 1
        elif freq_key in ("bid", "q12h", "twice daily", "2x/day") or freq_orig == "1日2回":
            pd = 2
        elif freq_key in ("tid", "q8h", "three times daily", "3x/day") or freq_orig == "1日3回":
            pd = 3
        elif freq_key in ("qid", "q6h", "four times daily", "4x/day") or freq_orig == "1日4回":
            pd = 4

    # Interval-based labels (q2h/q3h/…/6時間ごと/…) — carry their own JA
    # prefix, not a `毎日N回、` prefix. Look up by both the raw label and
    # its lowercased form.
    interval_prefix = _INTERVAL_FREQ_PREFIX_JA.get(freq_orig) or _INTERVAL_FREQ_PREFIX_JA.get(freq_key)

    for markers, template in _PI_ROUTE_FAMILIES_JA:
        if any(m in route_txt for m in markers) or route_txt.upper() in [m.upper() for m in markers]:
            if "{freq_ph}" not in template:
                return template
            # Oral: compose the freq prefix + verb.
            if interval_prefix:
                return f"{interval_prefix}内服してください"
            if pd == 1:
                phrase = "1回、"
            elif pd == 2:
                phrase = "2回、朝・夕の"
            elif pd == 3:
                phrase = "3回、朝・昼・夕の"
            elif pd == 4:
                phrase = "4回、"
            elif pd:
                phrase = f"{pd}回、"
            else:
                phrase = ""
            if phrase:
                return template.replace("{freq_ph}", phrase)
            # Neither pd-based nor interval-based freq matched — emit the
            # generic oral instruction rather than nothing (route IS oral,
            # so telling the patient to take it orally is not misleading).
            return "指示された時間帯に内服してください"
    return ""


# ────────────────────────────────────────────────────────────────────
# Issue #966: IV rate augmentation
#
# PR #920 populated ``MedicationRequest.dosageInstruction.doseAndRate
# .doseQuantity`` to 94.4 % coverage but did NOT emit ``rateQuantity``
# (or ``timing.repeat.duration`` for intermittent bolus) for IV-route
# orders — 421/421 IV MRs shipped without any rate specification.
# Downstream drug-safety alerts (KCl > 10 mEq/h, vancomycin > 10 mg/min)
# and nursing-side administration reconstruction depend on explicit rate.
#
# Fix: at emit time, look up per-drug infusion defaults from the yaml
# catalog ``clinosim/locale/shared/iv_infusion_defaults.yaml``
# (feedback_constants_live_in_external_config.md — tunable clinical
# constants belong in yaml, not code). The Python side holds only mode
# dispatch and the fallback default block.
#
# Priority order inside ``augment_iv_dosage_with_rate``:
#   1. Dose text already carries a rate expression (``100 mL/h``,
#      ``12U/kg/h``, ``5 mcg/min``) — emit rateQuantity from that.
#   2. Catalog lookup on the display_name (normalized, then longest
#      prefix, then first token, then alias table).
#   3. ``default`` block from the yaml (generic 30-min bolus).
#   4. ``mode = push`` → emit NEITHER rate nor duration (drug is
#      legitimately given as < 5 min IV push; a fabricated rate is worse
#      than omission — feedback_semantic_correctness_over_coverage).
_IV_RATE_TEXT_RE = re.compile(
    r"(?P<val>\d+(?:\.\d+)?)\s*(?P<num>mL|mg|mcg|ug|U|units|IU|mEq)"
    r"\s*/\s*(?P<denom>kg/h|kg/min|kg/hr|hr|h|min)",
    re.IGNORECASE,
)


def _canonicalize_iv_rate_unit(numerator: str, denominator: str) -> str:
    """Normalize the (numerator, denominator) match into a UCUM rate string.

    UCUM keeps ``mL``, ``mg``, ``mcg``, ``U`` as-is; ``hr`` → ``h``. Weight-
    normalized rates (``mg/kg/h``) are emitted as authored — UCUM allows
    the compound form. ``build_ucum_quantity`` down-line applies its own
    unit-code canonicalization (Issue #781 test) so this just picks a
    clean surface form for ``rate_unit``.
    """
    num = numerator.strip()
    denom = denominator.strip().lower()
    if denom in ("hr",):
        denom = "h"
    return f"{num}/{denom}"


def resolve_iv_infusion_default(display_name: str) -> dict[str, Any] | None:
    """Return the per-drug IV infusion default entry for ``display_name`` or None.

    Lookup order (see ``iv_infusion_defaults.yaml`` header for full contract):
      1. Strip protocol prefix (``"IV_fluid: NS 80 mL/h"`` → ``"NS 80 mL/h"``)
         and lowercase.
      2. Full-string match against the ``drugs`` map.
      3. Longest-prefix token match — so ``"Ceftriaxone 1g IV q8h"``
         resolves to ``"ceftriaxone"``.
      4. First-token match (safety net for authors' whitespace variants).
      5. ``aliases`` table (``"NS"`` → ``"normal saline"``).
      6. ``default`` block.
      7. ``None`` if the yaml has no ``default`` block (misconfiguration).
    """
    from clinosim.locale.loader import load_iv_infusion_defaults

    catalog = load_iv_infusion_defaults() or {}
    drugs: dict[str, Any] = catalog.get("drugs", {}) or {}
    aliases: dict[str, str] = catalog.get("aliases", {}) or {}
    default: dict[str, Any] | None = catalog.get("default")

    cleaned, _ = strip_protocol_prefix(display_name or "")
    key = cleaned.strip().lower()
    if not key:
        return default
    # Strip a leading route qualifier ("IV normal saline 1000mL" →
    # "normal saline 1000mL"). Authors put the route into the display_name
    # for supportive orders whose type does not carry a separate
    # ``route`` field on the CIF item; the route is redundant here since
    # the caller has already gated on canonical route = IV.
    tokens = key.split()
    if tokens and tokens[0] in ("iv", "i.v.", "intravenous"):
        tokens = tokens[1:]
        key = " ".join(tokens)
    if key in drugs:
        return drugs[key]
    # Longest-prefix token match — so "Ceftriaxone 1g IV q8h" resolves to
    # "ceftriaxone", "normal saline 1000ml" to "normal saline".
    for n in range(len(tokens), 0, -1):
        cand = " ".join(tokens[:n])
        if cand in drugs:
            return drugs[cand]
    if tokens and tokens[0] in drugs:
        return drugs[tokens[0]]
    # Aliases: try the full key, then longest-prefix, then first token
    # (mirror the drugs-map resolution order).
    if key in aliases:
        return drugs.get(aliases[key], default)
    for n in range(len(tokens), 0, -1):
        cand = " ".join(tokens[:n])
        if cand in aliases:
            return drugs.get(aliases[cand], default)
    if tokens and tokens[0] in aliases:
        return drugs.get(aliases[tokens[0]], default)
    return default


def augment_iv_dosage_with_rate(
    dosage: dict[str, Any],
    dose_text: str,
    route: str | None,
    display_name: str,
) -> None:
    """Extend ``dosage`` in-place with rateQuantity or timing.duration for IV orders.

    No-op when the route is not IV (canonical-form comparison, so
    ``INTRAVENOUS`` / ``iv`` aliases all resolve). No-op when the drug's
    catalog entry is ``mode: push`` (< 5 min IV push, e.g. fentanyl,
    naloxone — a fabricated rate here would be worse than an honest
    absence per feedback_semantic_correctness_over_coverage).

    ``continuous`` → sets ``dosage["doseAndRate"][0]["rateQuantity"]``
    (allocates the doseAndRate list if it does not exist).

    ``bolus`` → sets ``dosage["timing"]["repeat"]["duration"]`` +
    ``durationUnit = "min"`` (preserves any existing ``frequency`` /
    ``period`` block placed by the caller). ``timing.repeat.duration``
    is the FHIR-native way to express a scheduled infusion length; the
    ``MedicationAdministration`` sibling reconstructs the actual
    administered rate at nursing-record time.

    Priority: an explicit rate expression already inside ``dose_text``
    (``12 U/kg/h``, ``100 mL/h``, ``5 mcg/min``) wins over the catalog —
    the disease-YAML author wrote a specific rate that we must honour.
    """
    if not dosage:
        return
    canonical = canonicalize_route(route)
    if canonical != "IV":
        return

    # Priority 1: rate already in dose_text.
    if dose_text:
        m = _IV_RATE_TEXT_RE.search(dose_text)
        if m:
            try:
                rate_value = float(m.group("val"))
            except ValueError:
                rate_value = None
            if rate_value is not None:
                rate_unit = _canonicalize_iv_rate_unit(m.group("num"), m.group("denom"))
                dar = dosage.setdefault("doseAndRate", [{}])
                if not dar:
                    dar.append({})
                dar[0]["rateQuantity"] = build_ucum_quantity(rate_value, rate_unit)
                return

    # Priority 2/3: catalog lookup + default fallback.
    entry = resolve_iv_infusion_default(display_name)
    if not entry:
        return
    mode = str(entry.get("mode", "") or "").lower()
    if mode == "continuous":
        rate_value = entry.get("rate_value")
        rate_unit = entry.get("rate_unit", "")
        if rate_value is None or not rate_unit:
            return
        dar = dosage.setdefault("doseAndRate", [{}])
        if not dar:
            dar.append({})
        dar[0]["rateQuantity"] = build_ucum_quantity(rate_value, rate_unit)
    elif mode == "bolus":
        duration = entry.get("duration_min")
        if duration is None:
            return
        # Preserve any existing timing.repeat (frequency/period from the
        # caller's frequency parse) — merge rather than clobber.
        timing = dosage.setdefault("timing", {})
        repeat = timing.setdefault("repeat", {})
        repeat["duration"] = duration
        repeat["durationUnit"] = "min"
    # mode == "push" (or unrecognized): intentional no-op.


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

    # Dosage.patientInstruction — Issue #848 fix (route-aware).
    # Prior emit derived the phrase from the frequency label alone and
    # every generated JA template ended in "内服してください" ("take
    # orally") — so a saline IV drip (route.text="静注") shipped with
    # PI="毎日1回、指示された時間帯に内服してください" and the two
    # fields in the same resource disagreed on the route. Fix:
    # `_resolve_patient_instruction_ja` picks the phrasing template from
    # the ROUTE first (parenteral / inhalation / rectal / patch /
    # topical / eye drop / oral / …), then folds in the frequency
    # phrase only for oral. Non-JA callers keep the smaller
    # freq-timing-only map (qhs → "at bedtime" etc.) — the issue
    # measured the mismatch on JA output only.
    #
    # Explicit CIF-authored `patient_instruction` on the Order (Issue
    # #476 opt-in pattern) still takes precedence over the derived
    # phrase.
    _authored_instr = str(order.get("patient_instruction", "") or "")
    _derived_instr = ""
    # Also derive from freq_per_day when the raw freq label is absent —
    # this covers the "dose+freq_per_day-only" order shape used by the
    # discharge_prescription pipeline where `frequency` is left empty
    # (v14 review found 15 MR under this shape had text="…1日1回" but
    # `patientInstruction` empty).
    if not freq and freq_per_day:
        _pd_to_key = {1: "qd", 2: "bid", 3: "tid", 4: "qid", 6: "q4h", 8: "q3h", 12: "q2h"}
        freq = _pd_to_key.get(int(freq_per_day), "")
    if is_jp(country):
        # Timing-only labels (qhs / ac / pc / qam / qpm / prn) have no
        # route dependency — they describe WHEN, not HOW. Handle those
        # first before falling through to the route-based composer.
        _timing_only_ja = {
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
            "頓服": "症状のある時にのみ服用してください",
            "頓用": "症状のある時にのみ服用してください",
        }
        _flow_instr = (freq or "").lower().strip()
        _flow_instr_orig = str(freq or "").strip()
        _derived_instr = _timing_only_ja.get(_flow_instr_orig) or _timing_only_ja.get(_flow_instr, "")
        if not _derived_instr:
            _derived_instr = _resolve_patient_instruction_ja(route, freq, freq_per_day)
    elif freq:
        _flow_instr = freq.lower().strip()
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

    # Issue #966: IV-route drugs need an infusion rate (or timing.duration)
    # in addition to doseQuantity. `augment_iv_dosage_with_rate` is a no-op
    # for non-IV routes and for drugs the yaml catalog marks as `push`.
    # The dose text source is `display_name` (authored dose string), since
    # `order["dose_quantity"]`/`order["dose_unit"]` do not preserve the raw
    # "/h" or "/min" suffix that `parse_dose_string` strips before setting
    # the numeric qty. `display_name` still carries the untouched string
    # (see `enrich_medication_order` in modules/order/engine.py).
    _display_name = str(order.get("display_name", "") or "")
    augment_iv_dosage_with_rate(
        dosage,
        dose_text=_display_name,
        route=order.get("route"),
        display_name=_display_name,
    )

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
        #     どちらも)は JP Core 1.2.0 / JP-CLINS 1.13.0 / jpfhir-terminology
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
