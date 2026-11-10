"""FHIR R4 shared low-level helpers — the FHIR-builder fragment library.

Each helper produces a FHIR *fragment* (a coding, a CodeableConcept, an
address, a reference range, a status code, a Bundle entry) rather than a
top-level resource, and depends only on :mod:`clinosim.codes`,
:mod:`clinosim.locale` and the leaf reference modules.

Issue #2530 split the former 1,700-line module by responsibility:
``context`` (BundleContext), ``ecs_extensions`` (JP eCS institutional
extensions), ``dosage`` (route / timing / Dosage / MAR) and ``fhir_time``
(FHIR date-time conversion); import those names from their modules.
"""

from __future__ import annotations

import uuid
from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri, is_english_only_system
from clinosim.codes.icd10 import condition_short_name
from clinosim.codes.prefectures import prefecture_code
from clinosim.codes.ucum import ucum_quantity
from clinosim.countries import country_code as _country_code
from clinosim.countries import lang_for
from clinosim.country_profile import country_profile
from clinosim.locale.loader import load_addresses, load_code_mapping, load_reference_ranges
from clinosim.modules._shared import is_jp
from clinosim.modules.output.fhir_r4.lib.reference_data import (
    _JP_CONDITION_SEVERITY_CS,
    _SEVERITY_JP,
    _SEVERITY_SNOMED,
)

__all__ = [
    "build_address",
    "build_diagnosis_codeable_concept",
    "build_presented_form",
    "build_reference_range",
    "build_telecom",
    "entry",
    "infer_severity",
    "iter_diagnosis_mapping_targets",
    "make_participant",
    "map_encounter_status",
    "severity_coding",
    "survey_category",
]


def _escape_html(s: str) -> str:
    """Escape HTML special characters for safe embedding in FHIR text.div.

    Escapes &, <, >, " — sufficient for plain-text clinical content that
    may contain lab values, units, or angle brackets (e.g. "PaO2 < 80 & SpO2 > 90").
    Shared across fhir_r4/labs/diagnostic_report.py and fhir_r4/documents/composition.py (DRY, CLAUDE.md
    unification rule — no inline duplication).
    """
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def display_entry(text: str) -> dict[str, str]:
    """``{"display": text}``, or ``{}`` when ``text`` is empty — a Coding never
    carries an empty display or the raw code as display (Issue #2416)."""
    return {"display": text} if text else {}


def system_coding(system_key: str, code: str, lang: str, *, fallback_display: str = "") -> dict[str, Any]:
    """A Coding whose display follows the dual-slot rule (Issue #2264).

    For an English-only CodeSystem (:func:`clinosim.codes.is_english_only_system`)
    the display is the English canonical display whatever ``lang`` is; for
    other systems it is the display in ``lang`` (then English). Used directly
    for Coding-typed elements that have no ``text`` slot (``Encounter.class``);
    CodeableConcepts use :func:`dual_slot_concept`. ``fallback_display`` is used
    when the registry has no display; an absent display is omitted.
    """
    english_only = is_english_only_system(system_key)
    display = registry_display(system_key, code, "en" if english_only else lang)
    if not display and not english_only:
        display = registry_display(system_key, code, "en")
    coding: dict[str, Any] = {"system": get_system_uri(system_key), "code": code}
    if display or fallback_display:
        coding["display"] = display or fallback_display
    return coding


def dual_slot_concept(
    system_key: str,
    code: str,
    lang: str,
    *,
    text: str | None = None,
    fallback_display: str = "",
) -> dict[str, Any]:
    """A CodeableConcept in the dual-slot shape (Issue #2276).

    For an English-only CodeSystem (:func:`clinosim.codes.is_english_only_system`)
    ``coding.display`` is the English canonical display and ``text`` carries
    the label in ``lang``; for other systems ``coding.display`` is the display
    in ``lang`` (then English). ``text`` defaults to the registry display in
    ``lang``; ``fallback_display`` is used for the coding when the registry has
    no display. Absent displays are omitted rather than echoing the code.
    """
    concept: dict[str, Any] = {"coding": [system_coding(system_key, code, lang, fallback_display=fallback_display)]}
    label = text if text is not None else registry_display(system_key, code, lang)
    if label:
        concept["text"] = label
    return concept


def text_if_localized(display_en: str, label: str) -> dict[str, Any]:
    """``{"text": label}`` when the localized ``label`` differs from the
    coding's English display, else ``{}`` (Issue #3026)."""
    return {"text": label} if label and label != display_en else {}


def english_display_concept(system_key: str, code: str, lang: str) -> dict[str, Any]:
    """A CodeableConcept for an English-only CodeSystem whose coding keeps the
    English canonical display, with the ``lang`` label in ``text`` only when it
    differs from that display (Issue #3026) — so English output carries no
    duplicate ``text``."""
    coding = system_coding(system_key, code, "en")
    concept: dict[str, Any] = {"coding": [coding]}
    label = registry_display(system_key, code, lang)
    if label and label != coding.get("display"):
        concept["text"] = label
    return concept


def survey_category(lang: str) -> list[dict]:
    """The observation category list for survey-type observations (dual slot,
    Issue #2337)."""
    return [dual_slot_concept("hl7-observation-category", "survey", lang)]


def _social_category(country: str) -> list[dict]:
    """FHIR Observation.category for social-history (US Core SDOH).

    Returns the standard hl7-observation-category coding with localized
    display + text — used by every social-history Observation builder
    (smoking, alcohol, occupation, education, housing, ...). Promoted
    from _fhir_sdoh.py in PR2 (G2 SDOH integrity refactor, 2026-06-24).
    """
    return [dual_slot_concept("hl7-observation-category", "social-history", lang_for(country))]


def entry(resource: dict) -> dict:
    """Wrap a resource as a Bundle entry.

    Perf fix (2026-10-17): the previous ``resource.get("id", str(uuid.uuid4()))``
    pattern evaluated the ``uuid.uuid4()`` default argument on every call
    (classic Python default-value gotcha) regardless of whether ``id`` was
    actually missing. Profile at p=2000 5-year showed **10.97M `os.urandom`
    calls** flowing from this one line — all wasted because every resource
    builder emits a deterministic ``id``. Also a correctness-smell: the
    deterministic sim should never leak ``os.urandom`` into any code
    path. The lazy form below only consumes ``uuid4`` when a resource
    genuinely lacks ``id``, which is a bug anyway (``_fhir_id_is_spec_valid``
    rejects empty ids downstream).
    """
    rid = resource.get("id") or str(uuid.uuid4())
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
    - Never emits display==code and never emits the literal placeholder
      ``(display unavailable)``. Issue #1766: when the display cannot be
      resolved from the primary system or the icd-10-cm cross-fallback,
      the ``display`` key is OMITTED from the coding entry entirely
      (FHIR R4 permits a bare (system, code) coding). The validator
      rejects placeholder displays as non-canonical, so emission omits
      the field rather than lying.

    Falls back to icd-10-cm lookup if the code isn't in the country's system
    (e.g. JP using icd-10 but code only in icd-10-cm).

    code.text is set to a clinical short-name / abbreviation when available
    (e.g. "COPD" instead of "Other chronic obstructive pulmonary disease"),
    enabling search by common clinical abbreviations. When no display is
    resolvable, ``text`` falls back to the raw code so narrative renderers
    have something to show.
    """

    primary_lang = lang_for(country)
    primary_system = get_system_uri(system_key)

    # Official display in the primary language, then English for the interop
    # coding. The registry resolves the ICD-10 ↔ ICD-10-CM sibling fallback
    # (Issue #2257). Issue #1766: unresolved → omit (``None``), never a
    # placeholder string.
    primary_display = registry_display(system_key, code, primary_lang) if code else None
    if primary_display == code:
        primary_display = None

    primary_coding: dict[str, Any] = {"system": primary_system, "code": code}
    if primary_display:
        primary_coding["display"] = primary_display
    # One coding (Issue #2375): the localized name goes in ``text``, not in a
    # second coding of the same system with another display.
    coding = [primary_coding]

    # code.text: clinical short-name / abbreviation for search friendliness;
    # coding[].display remains the official ICD name. Same chain as
    # ``condition_label`` (short name → official display), which the
    # narrative uses; never the raw code (Issues #2360, #2416).
    text = condition_short_name(code, primary_lang) or primary_display

    return {
        "coding": coding,
        **({"text": text} if text else {}),
    }


def iter_diagnosis_mapping_targets(country: str) -> list[str]:
    """Flatten every billable target in the country's diagnosis mapping.

    ``load_code_mapping("diagnosis", …)`` returns a ``dict[str, str | dict]``
    since Issue #957 introduced sex-conditional entries. Callers that need
    to enumerate every possible mapped code (validation tests, display-
    coverage sweeps) must walk both the plain string values and the
    ``by_sex`` / ``default`` leaves of the dict values.
    """
    country_code = _country_code(country)
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
    # Issue #3141: the line shape and the state form are country data
    # (addresses.yaml ``fhir_address``).
    shape = load_addresses(country_code)["fhir_address"]

    # Full address line: US the street line; JP 都道府県+市区町村+番地.
    line = str(shape["line_template"]).format(state=state_name, city=addr.get("city", ""), line1=addr.get("line1", ""))

    fhir_addr: dict[str, Any] = {
        # C4-13: Address.use = "home" per FHIR R4 spec.
        # JP Core Patient guidance mirrors HL7 R4: use should be populated
        # (was implicit "?"/missing, 100% of Patient.address records).
        "use": "home",
        "type": "both",
        # Issue #378: JP_Patient_eCS requires `address.text` (min=1). Only
        # emitted where the JP-CLINS (eCS) profile applies; US does not
        # assert eCS and adding `text` there would be an unrelated diff.
        # JP `line` already carries the concatenated 都道府県+市区町村+番地
        # form, which is exactly what `text` should hold.
        **({"text": line} if line and country_profile(country_code).uses("jp_clins") else {}),
        "line": [line] if line else [],
        "city": addr.get("city", ""),
        "postalCode": addr.get("postal_code", ""),
        "country": country_code,
    }

    # State: JP the JIS X 0401 prefecture code, US the state abbreviation.
    state = prefecture_code(state_name) if shape["state"] == "jis_x0401" else state_name
    if state:
        fhir_addr["state"] = state

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


def make_participant(code: str, practitioner_id: str, country: str = "US") -> dict[str, Any]:
    """Build an Encounter.participant entry; ``code`` is an HL7 v3-ParticipationType code (ATND / ADM / DIS)."""
    return {
        "type": [dual_slot_concept("hl7-v3-participationtype", code, lang_for(country))],
        "individual": {"reference": f"Practitioner/{practitioner_id}"},
    }


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
    *,
    medications: Any = None,
    age: int | None = None,
) -> list[dict[str, Any]] | None:
    """Build FHIR referenceRange from locale reference range data.

    For JP: uses JCCLS共用基準範囲 2022 with source extension.
    Sex-specific ranges are filtered by patient sex with appliesTo.
    When the patient takes a drug with a therapeutic range for this lab
    (e.g. INR on warfarin), that range is added with
    ``type = therapeutic`` (Issue #2205).
    """
    ref_data = load_reference_ranges(country_code)
    if not ref_data:
        return None

    ranges = ref_data.get("ranges", {}).get(lab_name)
    if not ranges:
        return None
    # Issue #2872: a child gets the interval for their age (the same one
    # ``determine_flag`` judges the CIF flag against) instead of the adult one.
    from clinosim.modules.observation.pediatric_ranges import pediatric_lab_range, pediatric_lab_range_text

    pediatric = pediatric_lab_range(lab_name, age, patient_sex)
    if pediatric is not None:
        p_low, p_high, p_unit, p_band = pediatric
        p_text = pediatric_lab_range_text(p_band, lang_for(country_code))
        ranges = [{"low": p_low, "high": p_high, "unit": p_unit, "text": p_text}]

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
            rr["low"] = ucum_quantity(entry["low"], unit_str)
        if entry.get("high") is not None:
            rr["high"] = ucum_quantity(entry["high"], unit_str)
        if entry.get("text"):
            rr["text"] = entry["text"]

        # appliesTo for sex-specific ranges
        if sex:
            # C2-05: resolve display via codes/data/hl7-v3-
            # administrativegender.yaml (was raw code emission with no display).
            rr["appliesTo"] = [
                {
                    "coding": [
                        system_coding(
                            "hl7-v3-administrativegender",
                            sex,
                            lang_for(country_code),
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

    from clinosim.modules.observation.engine import therapeutic_range

    therapeutic = therapeutic_range(lab_name, country_code, medications=medications, age=age)
    if therapeutic is not None:
        unit_str = (ranges[0] or {}).get("unit", "")
        result.append(
            {
                "low": ucum_quantity(therapeutic[0], unit_str),
                "high": ucum_quantity(therapeutic[1], unit_str),
                # Issue #3026: English HL7 display, the label in text.
                "type": english_display_concept("hl7-referencerange-meaning", "therapeutic", lang_for(country_code)),
                **({"text": therapeutic[2]} if therapeutic[2] else {}),
            }
        )

    return result if result else None


def judged_reference_range(ranges: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The reference range a result's interpretation is judged against: the
    therapeutic range when one is present (a patient on the matching drug,
    Issue #2205), else the first normal or unlabeled range; None when there
    is none."""
    judged = None
    for rng in ranges:
        code = ((rng.get("type") or {}).get("coding") or [{}])[0].get("code", "")
        if code == "therapeutic":
            return rng
        if (code == "normal" or not code) and judged is None:
            judged = rng
    return judged


def map_encounter_status(status: str) -> str:
    mapping = {
        "planned": "planned",
        "in_progress": "in-progress",
        "completed": "finished",
        "cancelled": "cancelled",
    }
    return mapping.get(status, "unknown")
