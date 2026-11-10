"""FHIR R4 patient-demographics resource builders (FA-1 Phase 11).

Patient, JP Core Coverage (+ payor Organization), occupation Observation, and
AllergyIntolerance — plus the identity-config cache and the marital/language/
coverage display constants used only by this cluster. Extracted verbatim from
``fhir_r4_adapter``; depends only on clinosim.codes/locale and the leaf
reference/localization + _fhir_common helper modules (no adapter import cycle).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

from clinosim.codes import display as registry_display
from clinosim.codes import get_system_uri, slug_to_code
from clinosim.codes.bcp47 import bcp47_display
from clinosim.codes.loinc import loinc_coding
from clinosim.codes.ucum import ucum_quantity
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_identity_config, resident_insurer_number, vocab_display
from clinosim.locale.loaders.fhir_identity import load_facility_identity
from clinosim.modules._shared import is_jp
from clinosim.modules.output.fhir_r4.lib.common import (
    _social_category,
    build_address,
    build_telecom,
    display_entry,
    dual_slot_concept,
    english_display_concept,
    system_coding,
    text_if_localized,
)
from clinosim.modules.output.fhir_r4.lib.fhir_time import to_fhir_date, to_fhir_deceased_datetime
from clinosim.modules.output.fhir_r4.lib.ids import (
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)
from clinosim.modules.output.fhir_r4.lib.jp_profiles import JP_OBSERVATION_COMMON_PROFILE

# === Issue #1344: US Core Patient extensions ===
# https://hl7.org/fhir/us/core/StructureDefinition-us-core-race.html
# https://hl7.org/fhir/us/core/StructureDefinition-us-core-ethnicity.html
# https://hl7.org/fhir/us/core/StructureDefinition-us-core-birthsex.html
#
# Codes are OMB race + ethnicity categories from the CDC race+ethnicity
# CodeSystem (OID 2.16.840.1.113883.6.238). Internal race/ethnicity
# fields on PatientProfile carry the sim's snake_case slug; this map
# translates each to the (code, display) pair the US Core Extension slot
# expects.
_US_CORE_RACE_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
_US_CORE_ETHNICITY_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
_US_CORE_BIRTHSEX_URL = "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"
_OMB_RACE_ETHNICITY_SYSTEM = get_system_uri("omb-race")

# Phase 3.γ (#1808 follow-up) + hardcoded-audit Phase A1 (#1900+1):
# both the slug → OMB code map and the display SoT now live in the
# authority yamls `clinosim/codes/data/omb-race.yaml` +
# `omb-ethnicity.yaml` (`slug_to_code:` + `codes:` blocks). This
# module keeps only the thin `@cache`-backed aliases so existing call
# sites (`_OMB_RACE_SLUG_TO_CODE.get(...)`) stay unchanged; display is
# resolved via `code_lookup(<system>, code, lang)` against the same
# yaml's `codes:` block, so JA + future locale displays emerge from
# the authority yaml.
_OMB_RACE_SLUG_TO_CODE: dict[str, str] = slug_to_code("omb-race")
_OMB_ETHNICITY_SLUG_TO_CODE: dict[str, str] = slug_to_code("omb-ethnicity")


def _build_us_core_race_extension(race: str, lang: str = "en") -> dict[str, Any] | None:
    """Build a us-core-race Extension for the given internal race slug.

    Returns None when the slug is empty or unrecognised — the extension is
    only emitted when a real OMB category is available (fabricating one
    would be worse than omitting per feedback_empty_vs_wrong_assertion).

    Phase 3.γ: display resolves via `code_lookup("omb-race", code, lang)`
    against `codes/data/omb-race.yaml` so JA + future-locale displays
    emerge from the authority yaml instead of a module-local map.
    """
    code = _OMB_RACE_SLUG_TO_CODE.get(race or "")
    if not code:
        return None
    display = registry_display("omb-race", code, lang) or ""
    return {
        "url": _US_CORE_RACE_URL,
        "extension": [
            {
                "url": "ombCategory",
                "valueCoding": {
                    "system": _OMB_RACE_ETHNICITY_SYSTEM,
                    "code": code,
                    **display_entry(display),
                },
            },
            {"url": "text", "valueString": display},
        ],
    }


def _build_us_core_ethnicity_extension(ethnicity: str, lang: str = "en") -> dict[str, Any] | None:
    """Build a us-core-ethnicity Extension — Phase 3.γ: display via
    `code_lookup("omb-ethnicity", code, lang)` against the authority yaml."""
    code = _OMB_ETHNICITY_SLUG_TO_CODE.get(ethnicity or "")
    if not code:
        return None
    display = registry_display("omb-ethnicity", code, lang) or ""
    return {
        "url": _US_CORE_ETHNICITY_URL,
        "extension": [
            {
                "url": "ombCategory",
                "valueCoding": {
                    "system": _OMB_RACE_ETHNICITY_SYSTEM,
                    "code": code,
                    **display_entry(display),
                },
            },
            {"url": "text", "valueString": display},
        ],
    }


def _build_us_core_birthsex_extension(sex: str) -> dict[str, Any] | None:
    """Map PatientProfile.sex ("M"/"F") to the us-core-birthsex valueCode.

    The sim does not currently distinguish administrative gender from
    birth sex; the two coincide, so ``sex`` is the correct source for the
    US-Core birthsex Extension. Values outside M/F are omitted (would
    require an "UNK"/"OTH" mapping that the sim does not yet model).
    """
    sex_upper = (sex or "").strip().upper()
    if sex_upper not in ("M", "F"):
        return None
    return {
        "url": _US_CORE_BIRTHSEX_URL,
        "valueCode": sex_upper,
    }


# === Issue #854 Bucket C row 18 (PR-patient): opaque Patient.id ===
# Structural key = the CIF ``patient_id`` verbatim (`POP-{n:06d}`, a
# simulation-generation-artifact slug, not a clinical identifier).
# Post-#854 every FHIR Patient.id is ``pt-<12hex>`` (15 chars, fixed);
# `POP-{n}` is preserved on `Patient.identifier[]` under the
# POPULATION_SLUG_KEY_SYSTEM so consumers who key on the human-readable
# generation slug (iris4h-ai clinical cockpit, integration tests) can
# still recover it. Every downstream `f"Patient/{patient_id}"` site is
# routed through `patient_ref` — never string-format the CIF value
# directly.
PATIENT_ID_PREFIX = "pt-"
POPULATION_SLUG_KEY_SYSTEM = structural_key_system("population-slug")


_US_SSN_SYSTEM = get_system_uri("us-ssn")
_US_SSN_SALT = "patient-ssn"


def _build_us_ssn(cif_patient_id: str) -> str:
    """Deterministic synthetic SSN in the never-issued 9xx area (no real SSN can collide)."""
    n = int(hashlib.sha256(f"{_US_SSN_SALT}:{cif_patient_id}".encode()).hexdigest()[:16], 16)
    area = 900 + n % 100
    group = 1 + (n // 100) % 99
    serial = 1 + (n // 9900) % 9999
    return f"{area:03d}-{group:02d}-{serial:04d}"


def _build_us_ssn_identifier(cif_patient_id: str) -> dict[str, Any]:
    return {
        "use": "official",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("hl7-v2-0203"),
                    "code": "SS",
                    "display": "Social Security number",
                }
            ],
            "text": "SSN",
        },
        "system": _US_SSN_SYSTEM,
        "value": _build_us_ssn(cif_patient_id),
    }


# National identifier builders by the name identity.yaml
# ``fhir_patient.national_identifier`` gives (Issue #3141).
_NATIONAL_IDENTIFIER_BUILDERS: dict[str, Callable[[str], dict[str, Any]]] = {"ssn": _build_us_ssn_identifier}


def resolve_patient_id(cif_patient_id: str) -> str:
    """Return the opaque FHIR Patient.id for a CIF ``patient_id``.

    Shape: ``pt-{sha256(cif_patient_id)[:12]}`` = 15 chars, fixed.

    Empty ``cif_patient_id`` returns an empty string rather than raising —
    the empty upstream is a data-quality bug the caller should surface,
    but the FHIR emit layer preserves the pre-#854 behaviour of emitting
    an empty reference so downstream FHIR-validator gates can flag it as
    an integrity violation (rule
    ``feedback_empty_vs_wrong_assertion`` — 空欄は無知).
    """
    if not cif_patient_id:
        return ""
    return derive_opaque_id(PATIENT_ID_PREFIX, cif_patient_id)


def patient_ref(cif_patient_id: str) -> dict[str, str]:
    """Return a FHIR ``Reference`` dict pointing at the opaque Patient id.

    All emit sites that need ``{"reference": f"Patient/{...}"}`` must
    route through this helper — never string-format the CIF
    ``patient_id`` directly into the reference slot. Empty
    ``cif_patient_id`` yields ``{"reference": "Patient/"}`` — a broken
    reference matching pre-#854 behaviour so downstream FHIR-integrity
    audits keep catching it.
    """
    return {"reference": f"Patient/{resolve_patient_id(cif_patient_id)}"}


# === Issue #854 Bucket A row 4 (PR-obs-standalone): opaque occupation id ===
# Issue #909: salt hash input with observation-key kind so ``.id`` diverges
# from ``Patient.id`` (which hashes ``patient_id`` unsalted).
_OCCUPATION_KEY_KIND = "occupation-observation-key"
# Structural key = pre-#854 id body (patient id).
OCCUPATION_ID_PREFIX = "occupation-"
OCCUPATION_KEY_SYSTEM = structural_key_system(_OCCUPATION_KEY_KIND)


def _resolve_occupation_id(structural_key: str) -> str:
    return derive_opaque_id(OCCUPATION_ID_PREFIX, f"{_OCCUPATION_KEY_KIND}:{structural_key}")


# === Issue #854 Bucket C (PR-coverage): opaque Coverage.id ===
# Structural key = pre-#854 id body `{patient_id}-{idx}` (`cov-` prefix
# stripped); post-#854 every `.id` is `cov-<12hex>` (16 chars, fixed).
# Coverage already carries a member-id identifier[] for the JP insurance
# number; a second entry under COVERAGE_KEY_SYSTEM round-trips the
# structural key so consumers keyed on the old id still work.
COVERAGE_ID_PREFIX = "cov-"
COVERAGE_KEY_SYSTEM = structural_key_system("coverage-key")


def _resolve_coverage_id(structural_key: str) -> str:
    return derive_opaque_id(COVERAGE_ID_PREFIX, structural_key)


# FHIR R4 standard: beneficiary's relationship to the policy subscriber
_SUBSCRIBER_REL_SYSTEM = get_system_uri("hl7-subscriber-relationship")


def _default_coverage_period_year(patient_data: dict) -> int:
    """Pick a default calendar year for Coverage.period when the enrollment
    lacks explicit start/end (C2-11 fallback). Uses the patient's first
    encounter year if available; otherwise a fixed simulation year.

    Kept for backward compatibility with callers that only pass patient_data;
    the multi-FY emit path (Issue #923) uses `_derive_encounter_date_range`
    instead.
    """
    encs = patient_data.get("encounters", [])
    if encs:
        first_dt = encs[0].get("admission_datetime", "") or encs[0].get("period", {}).get("start", "")
        first_dt = str(first_dt)
        if len(first_dt) >= 4 and first_dt[:4].isdigit():
            return int(first_dt[:4])
    return 2025


def _fy_boundary(country: str) -> tuple[int, int]:
    """Return (month, day) marking the fiscal-year start for the locale.

    JP defaults to (4, 1) per identity.yaml `fiscal_year`. Non-JP locales
    without a fiscal_year block fall back to calendar-year (1, 1).
    """
    fy = _identity_cfg(country).get("fiscal_year", {}) or {}
    return (int(fy.get("start_month", 1)), int(fy.get("start_day", 1)))


def _age_gate_config(country: str) -> dict[str, int]:
    """Return the age-gate thresholds from identity.yaml.

    JP defaults (Issue #923):
      - late_elderly_min_age: 75 (mandatory 後期高齢者医療制度 enrolment)
      - primary_subscriber_min_age: 18 (被保険者 slot legal minimum)
    """
    gates = _identity_cfg(country).get("age_gates", {}) or {}
    return {
        "late_elderly_min_age": int(gates.get("late_elderly_min_age", 75)),
        "primary_subscriber_min_age": int(gates.get("primary_subscriber_min_age", 18)),
    }


def _minor_dependent_categories(country: str) -> frozenset[str]:
    """Categories under which a minor is a dependant on a guardian's policy
    (identity.yaml ``age_gates.minor_dependent_categories``, Issue #3000)."""
    gates = _identity_cfg(country).get("age_gates", {}) or {}
    return frozenset(str(c) for c in gates.get("minor_dependent_categories") or [])


def _guardian_subscriber(patient_data: dict) -> dict[str, str] | None:
    """The guardian on record as a display-only Reference (Issue #3000).

    A child born in the simulation carries its mother as the emergency
    contact (``MTH``); no Patient resource is fabricated for her, so the
    reference names her only. ``None`` when no guardian is on record.
    """
    contact = patient_data.get("contact") or {}
    if not isinstance(contact, dict) or contact.get("emergency_contact_relationship") not in _GUARDIAN_RELATIONS:
        return None
    name = str(contact.get("emergency_contact_name") or "")
    return {"display": name} if name else None


# Emergency-contact relationships that make the contact a minor's guardian.
_GUARDIAN_RELATIONS = frozenset({"MTH", "parent"})


def _resident_payer_number(country: str, scheme: str, prefecture: str, city: str) -> str:
    """保険者番号 of the ``scheme`` insurer of the patient's residence
    (Issue #3015: 国保 by municipality, 後期高齢者医療 by the prefecture's
    広域連合), else the first ``scheme`` payer in identity.yaml; empty when
    none is configured (e.g., non-JP locale)."""
    resident = resident_insurer_number(country, scheme, prefecture, city)
    if resident:
        return resident
    for e in (_identity_cfg(country).get("payers", {}) or {}).get(scheme) or []:
        if e.get("number"):
            return str(e["number"])
    return ""


def _late_elderly_payer_number(country: str, prefecture: str = "", city: str = "") -> str:
    """The 後期高齢者医療 保険者番号 for a residence (``_resident_payer_number``).

    Used when Issue #923's age-gate reassigns an aging-into-≥75 patient's
    Coverage row to 後期高齢者医療制度.
    """
    return _resident_payer_number(country, "late_elderly", prefecture, city)


def _parse_iso_date(value: Any) -> date | None:
    """Parse an ISO-8601 date/datetime string into a `date`, ignoring the time.

    Encounter `admission_datetime` values come through as either
    'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS[+09:00]'; we only need the day
    part for FY bucketing.
    """
    if not value:
        return None
    s = str(value)
    if len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _derive_encounter_date_range(encounters: list[dict] | None, patient_data: dict) -> tuple[date | None, date | None]:
    """Return (earliest, latest) encounter date across the patient's encounters.

    Falls back to `patient_data.get("encounters")` when the caller does not
    supply an explicit list (identity module or legacy tests). Returns
    (None, None) when no dates can be parsed.
    """
    src = encounters if encounters is not None else patient_data.get("encounters", []) or []
    starts: list[date] = []
    ends: list[date] = []
    for enc in src:
        if not isinstance(enc, dict):
            continue
        s = _parse_iso_date(enc.get("admission_datetime") or enc.get("period", {}).get("start"))
        if s:
            starts.append(s)
        e = _parse_iso_date(
            enc.get("discharge_datetime") or enc.get("period", {}).get("end") or enc.get("admission_datetime")
        )
        if e:
            ends.append(e)
    if not starts and not ends:
        return (None, None)
    earliest = min(starts) if starts else min(ends)
    latest = max(ends) if ends else max(starts)
    return (earliest, latest)


def _fy_bounds_containing(day: date, fy_month: int, fy_day: int) -> tuple[date, date]:
    """Return the (start, end_inclusive) of the fiscal year containing `day`.

    For JP (fy_month=4, fy_day=1): a date in Jan-Mar belongs to the prior
    FY (started April 1 of previous calendar year); April 1 onward belongs
    to the FY starting that April.
    """
    if (day.month, day.day) >= (fy_month, fy_day):
        start_year = day.year
    else:
        start_year = day.year - 1
    start = date(start_year, fy_month, fy_day)
    # end = one day before next FY start
    next_start = date(start_year + 1, fy_month, fy_day)
    end = date.fromordinal(next_start.toordinal() - 1)
    return (start, end)


def _iter_fy_periods(earliest: date, latest: date, fy_month: int, fy_day: int) -> list[tuple[date, date]]:
    """Enumerate fiscal-year (start, end) pairs covering [earliest, latest]."""
    periods: list[tuple[date, date]] = []
    cur_start, cur_end = _fy_bounds_containing(earliest, fy_month, fy_day)
    while cur_start <= latest:
        periods.append((cur_start, cur_end))
        next_start = date(cur_start.year + 1, fy_month, fy_day)
        cur_start = next_start
        cur_end = date.fromordinal(date(next_start.year + 1, fy_month, fy_day).toordinal() - 1)
    return periods


def _age_on(dob: date, when: date) -> int:
    """Age in whole years on `when` (birthday-adjusted, standard convention)."""
    years = when.year - dob.year
    if (when.month, when.day) < (dob.month, dob.day):
        years -= 1
    return years


def _birthday(dob: date, age: int) -> date:
    """The day ``age`` is reached (29 February birthdays fall on 1 March)."""
    try:
        return dob.replace(year=dob.year + age)
    except ValueError:
        return date(dob.year + age, 3, 1)


def _jp_school_entry(dob: date) -> date:
    """1 April of the school year a child enters elementary school (学校教育法):
    a child who is 6 by 1 April enters that April (birthdays 2 April to
    1 April of the following year share a school year)."""
    year = dob.year + 6 if (dob.month, dob.day) <= (4, 1) else dob.year + 7
    return date(year, 4, 1)


def jp_income_quantile(patient_id: str) -> float:
    """Per-person income quantile in [0, 1) for the JP copay tier (Issue #3016);
    stable for a person across years, no RNG draw."""
    from clinosim.determinism import sha_quantile

    return sha_quantile(f"jp-copay-income|{patient_id}")


def jp_copay_pct(dob: date, on: date, income_q: float, country: str = "JP") -> int:
    """JP 一部負担金割合 (%) on ``on`` (Issue #3016), from identity.yaml ``copay``:
    by age (school entry, 70, 75) and, from 70, by the income quantile."""
    cfg = _identity_cfg(country).get("copay", {}) or {}
    late_age = _age_gate_config(country)["late_elderly_min_age"]
    age = _age_on(dob, on)
    if age >= late_age:
        le = cfg["late_elderly"]
        if income_q < float(le["high_income_share"]):
            return int(le["high_income_pct"])
        middle_from = date.fromisoformat(str(le["middle_income_from"]))
        if on >= middle_from and income_q < float(le["high_income_share"]) + float(le["middle_income_share"]):
            return int(le["middle_income_pct"])
        return int(le["pct"])
    old = cfg["age_70_74"]
    if age >= int(old["min_age"]):
        return int(old["high_income_pct"]) if income_q < float(old["high_income_share"]) else int(old["pct"])
    if on < _jp_school_entry(dob):
        return int(cfg["preschool_pct"])
    return int(cfg["standard_pct"])


def _national_payer_number(country: str, prefecture: str = "", city: str = "") -> str:
    """The 国民健康保険 保険者番号 for a residence (``_resident_payer_number``),
    used for the months before a 後期高齢者 enrollee's 75th birthday."""
    return _resident_payer_number(country, "national", prefecture, city)


@lru_cache(maxsize=2)
def _identity_cfg(country: str) -> dict:
    """Full resident-identity locale config (AD-54).

    ``@lru_cache(maxsize=2)`` bounds the cache to the two supported
    countries (US / JP). Issue #557: replaces the pre-Aug-2026 pattern
    of a module-level `_IDENTITY_CFG_CACHE: dict` mutated across module
    boundaries — the previous 3 external re-imports (`_fhir_post_process`,
    `_fhir_inline_bb`) were unused ``noqa: F401`` re-exports and are
    removed.
    """
    return load_identity_config(country)


def _payer_name_map(country: str) -> dict[str, str]:
    """Map 保険者番号 → insurer name from locale (display resolved at output, AD-30)."""
    payers = _identity_cfg(country).get("payers", {})
    out: dict[str, str] = {}
    for entries in payers.values():
        for e in entries or []:
            if e.get("number"):
                out[str(e["number"])] = str(e.get("name", e["number"]))
    return out


def _derive_coverage_status(period_end: str | None, snapshot_date: str | None) -> str:
    """Return the FHIR R4 ``Coverage.status`` code for a policy period.

    Rule (Issue #944): ``Coverage.status = "active"`` means "currently in
    effect". A per-FY row whose ``period.end`` is strictly before the
    simulation snapshot date has, by definition, expired — emit
    ``"cancelled"`` (the FHIR R4 status value used for a policy that has
    ended; ``"entered-in-error"`` is reserved for records the emitter
    knows were wrong).

    Boundary: ``period.end == snapshot_date`` still counts as active
    (inclusive comparison — the FY endpoint IS the last day of coverage).

    Backward compat: when ``snapshot_date`` is unknown (identity-only
    tests, callers that don't plumb the CIF metadata through) we default
    to ``"active"``, preserving the pre-#944 emit for those paths.
    """
    if not period_end or not snapshot_date:
        return "active"
    # String compare is safe for ISO-8601 YYYY-MM-DD values (lexicographic
    # order == chronological order); avoids re-parsing on the hot path.
    return "active" if period_end >= snapshot_date else "cancelled"


def _member_id_value(cfg: dict, insurer: str, symbol: str | None, number: str, branch: str | None) -> str:
    """The composite member identifier of a Coverage (Issue #3149): the
    locale's ``member_id_fields`` joined by ``:`` (a missing field is an empty
    string), the 保険者番号 left-padded with zeros to ``insurer_number_width``."""
    width = int(cfg.get("insurer_number_width") or 0)
    parts = {"insurer": insurer.zfill(width), "symbol": symbol or "", "number": number, "branch": branch or ""}
    return ":".join(parts[f] for f in cfg.get("member_id_fields") or ["insurer", "number"])


def _current_member_identifier(coverages: list[dict], member_id_system: str) -> dict | None:
    """The member identifier of the patient's current Coverage (Issue #3149):
    the active Coverage with the latest period start, else the latest one."""
    rows = [r for r in coverages if r.get("resourceType") == "Coverage"]
    if not rows:
        return None
    rows.sort(key=lambda r: (r.get("status") == "active", str((r.get("period") or {}).get("start", ""))))
    for ident in rows[-1].get("identifier") or []:
        if ident.get("system") == member_id_system:
            return {"system": ident["system"], "value": ident["value"]}
    return None


def _build_coverage_resources(
    patient_data: dict,
    country: str,
    encounters: list[dict] | None = None,
    snapshot_date: str | None = None,
) -> list[dict]:
    """Build JP Core Coverage + payor Organization from the patient's insurance enrollment.

    Reads CIF data only (no dependency on the identity module — module independence).
    `national_id` is never read here: the privacy chokepoint (AD-54) means individual
    numbers are never emitted to FHIR.

    Issue #923: emits one Coverage row per fiscal year covered by the patient's
    encounter window (JP FY = 4/1 → 3/31 per identity.yaml `fiscal_year`), so no
    encounter falls outside its Coverage.period. Each per-FY row is *re-aged*: the
    category and payer are recomputed from the patient's age at that FY's April 1
    boundary, so a patient turning 75 mid-simulation gets a 後期高齢者医療制度 row
    starting the next FY. Falls back to the pre-#923 single-row emit for callers
    that don't pass encounters (identity-only tests, non-JP locales, etc.).
    """
    cfg = _identity_cfg(country).get("fhir_coverage", {})
    if not cfg:
        return []
    name_map = _payer_name_map(country)
    type_labels = _identity_cfg(country).get("coverage_type_labels", {})
    identity = patient_data.get("identity") or {}
    enrollments = identity.get("enrollments") or []
    pid = patient_data.get("patient_id", "")
    resources: list[dict] = []

    # Issue #923 §Fix 1: emit one Coverage per FY covered by encounters.
    # Falls back to a single row (pre-#923 behaviour) when we can't derive
    # a range — legacy callers / tests without encounters.
    fy_month, fy_day = _fy_boundary(country)
    earliest, latest = _derive_encounter_date_range(encounters, patient_data)
    if earliest and latest:
        fy_periods = _iter_fy_periods(earliest, latest, fy_month, fy_day)
    else:
        fallback_year = _default_coverage_period_year(patient_data)
        fy_periods = [
            (
                date(fallback_year, fy_month, fy_day),
                date.fromordinal(date(fallback_year + 1, fy_month, fy_day).toordinal() - 1),
            )
        ]

    gates = _age_gate_config(country)
    minor_dependent = _minor_dependent_categories(country)
    dob = _parse_iso_date(patient_data.get("date_of_birth"))
    # Issue #3015: the insurers of the patient's residence.
    _addr = patient_data.get("address") or {}
    _pref = str(_addr.get("state", "") or "") if isinstance(_addr, dict) else ""
    _city = str(_addr.get("city", "") or "") if isinstance(_addr, dict) else ""
    late_elderly_payer = _late_elderly_payer_number(country, _pref, _city)
    # Issue #3000: no coverage before birth.
    if dob:
        fy_periods = [(max(s, dob), e) for s, e in fy_periods if e >= dob]
    # Issue #3016: 後期高齢者医療 starts on the 75th birthday — split the fiscal
    # year there. The part from the birthday gets its own structural key.
    periods: list[tuple[date, date, str]] = []
    late_start = _birthday(dob, gates["late_elderly_min_age"]) if dob else None
    for s, e in fy_periods:
        if late_start is not None and s < late_start <= e:
            periods.append((s, late_start - timedelta(days=1), f"fy{s.year}"))
            periods.append((late_start, e, f"fy{s.year}-from{late_start.isoformat()}"))
        else:
            periods.append((s, e, f"fy{s.year}"))
    income_q = jp_income_quantile(pid) if is_jp(country) else 0.0

    # Deduplicate payor Organization resources across FY rows — the same
    # 保険者番号 typically holds the entire encounter window; only aging-into-≥75
    # rows swap to the 後期高齢者 payer.
    emitted_payer_ids: set[str] = set()

    for enr_idx, enr in enumerate(enrollments):
        base_insurer = enr.get("insurer_number") or ""
        number = enr.get("member_id") or ""
        symbol = enr.get("group_symbol")
        branch = enr.get("branch_number")
        base_category = enr.get("category") or ""
        if not base_insurer or not number:
            continue

        for fy_start, fy_end, period_key in periods:
            # Issue #923 §Fix 2: re-age the category at each FY boundary.
            # Two age checks:
            #  - late_elderly gate uses `fy_end`: if the patient is ≥75 at
            #    ANY point in the FY (i.e., turns 75 during the period),
            #    the row is 後期高齢者医療制度 for the whole FY. This models
            #    the JP legal reality that 75+ residents are auto-enrolled
            #    on their 75th birthday — since we don't split FYs at the
            #    birthday, we conservatively promote the whole FY row. It
            #    also drives the audit `older_wrong` count to 0 (the
            #    reproduction script measures age at Jan 1 mid-FY).
            #  - primary-subscriber gate uses `fy_start`: minors are demoted
            #    to 被扶養者 whenever they are still under 18 at the FY start,
            #    because the 被保険者 slot is a policy-time role.
            # Issue #3016: the late-elderly gate uses the period start — the
            # fiscal year is split on the 75th birthday above, so a row is
            # 後期高齢者医療 exactly when the patient is 75 throughout it. A
            # 後期 enrollee's rows before 75 are 国民健康保険 (the scheme of
            # the years before; the enrollment itself starts at 75).
            age_at_period_start = _age_on(dob, fy_start) if dob else -1
            if dob:
                if age_at_period_start >= gates["late_elderly_min_age"]:
                    category = "late_elderly"
                elif base_category == "late_elderly":
                    category = "national"
                elif age_at_period_start < gates["primary_subscriber_min_age"] and base_category == "employee":
                    category = "dependent"
                else:
                    category = base_category
            else:
                category = base_category

            # Insurer + card fields track the (possibly reassigned) category.
            if category == "late_elderly" and late_elderly_payer:
                insurer = late_elderly_payer
                # Late-elderly enrolment is per-individual: no 記号 / 枝番.
                use_symbol: str | None = None
                use_branch: str | None = None
            elif category == "national" and base_category == "late_elderly":
                insurer = _national_payer_number(country, _pref, _city) or base_insurer
                use_symbol = None
                use_branch = None
            elif category != base_category and category == "dependent":
                # Minor demoted from 被保険者 → 被扶養者 on the same policy;
                # keep the household insurer + 記号 but 枝番 must exist.
                insurer = base_insurer
                use_symbol = symbol
                use_branch = branch or "01"
            else:
                insurer = base_insurer
                use_symbol = symbol
                use_branch = branch

            payer_org_id = f"payer-{insurer}"
            if payer_org_id not in emitted_payer_ids:
                emitted_payer_ids.add(payer_org_id)
                resources.append(
                    {
                        "resourceType": "Organization",
                        "id": payer_org_id,
                        "identifier": [
                            {
                                "system": cfg.get("insurer_number_system", ""),
                                "value": insurer,
                            }
                        ],
                        "type": [dual_slot_concept("hl7-organization-type", "pay", lang_for(country))],
                        "name": name_map.get(insurer, insurer),
                    }
                )

            # JP Core extensions: 記号 / 番号 / 枝番. Each extension is
            # only appended when the identity.yaml declares a non-empty
            # StructureDefinition URL for it — US locales set the ext_*
            # keys to "" so the block emits no extensions (US-Core
            # Coverage has no equivalent slot).
            extensions: list[dict] = []
            ext_symbol_url = cfg.get("ext_symbol") or ""
            ext_number_url = cfg.get("ext_number") or ""
            ext_subnumber_url = cfg.get("ext_subnumber") or ""
            if use_symbol and ext_symbol_url:
                extensions.append({"url": ext_symbol_url, "valueString": use_symbol})
            if ext_number_url:
                extensions.append({"url": ext_number_url, "valueString": number})
            if use_branch and ext_subnumber_url:
                extensions.append({"url": ext_subnumber_url, "valueString": use_branch})

            # Composite member identifier — fields and 保険者番号 width from
            # identity.yaml (Issue #3149; JP: 保険者番号:記号:番号:枝番 with an
            # 8-digit 保険者等番号, US: <insurer>:<member_id>).
            composite = _member_id_value(cfg, insurer, use_symbol, number, use_branch)
            subscriber = f"{use_symbol}:{number}" if use_symbol else number

            # Issue #923: structural key always carries the FY year so
            # per-encounter records emitted for the same patient across
            # different FYs each land as a distinct Coverage row (the
            # write()-level dedup keys on `.id`, so a pre-#923 pid-only
            # key would silently collapse a multi-FY patient down to a
            # single row — see #923 scan showing 39.94% uncovered with
            # single-FY keys). Different-FY records for the same patient
            # now hash to distinct ids and coexist as intended; same-FY
            # duplicate records collapse as before.
            _cov_structural_key = f"{pid}-{enr_idx}-{period_key}"
            # Issue #944: derive Coverage.status from period.end vs the
            # simulation snapshot date. Explicit enrollment valid_to (rare,
            # Phase 2) still wins over the FY-derived end below — resolve
            # the effective period.end here so both branches converge.
            _effective_period_end: str
            if enr.get("valid_to"):
                _effective_period_end = str(enr["valid_to"])
            else:
                _effective_period_end = fy_end.isoformat()
            coverage: dict[str, Any] = {
                "resourceType": "Coverage",
                "id": _resolve_coverage_id(_cov_structural_key),
                "identifier": [
                    {"system": cfg.get("member_id_system", ""), "value": composite},
                    wrap_as_identifier(_cov_structural_key, COVERAGE_KEY_SYSTEM),
                ],
                "status": _derive_coverage_status(_effective_period_end, snapshot_date),
                "subscriberId": subscriber,
                # CY7-13 (Chain-7): Coverage.subscriber — the person carrying the
                # policy. For "self" relationship the subscriber IS the beneficiary
                # (JP 主たる被保険者 = 本人); for "other" (dependent) it's the
                # policy-holder relative. Without a distinct 主たる被保険者
                # Person record, we point to the patient themselves (matches
                # subscriberId derivation above and passes FHIR R4 conformance —
                # subscriber is 0..1 Reference to Patient|RelatedPerson).
                "subscriber": patient_ref(pid),
                "beneficiary": patient_ref(pid),
                "payor": [{"reference": f"Organization/{payer_org_id}"}],
            }
            # Issue #1767: emit `extension` only when non-empty — FHIR R4
            # requires empty 0..* arrays to be absent, not `[]`. US locales
            # (no JP 記号/番号/枝番) therefore skip the key entirely.
            if extensions:
                coverage["extension"] = extensions
            if cfg.get("profile"):
                coverage["meta"] = {"profile": [cfg["profile"]]}
            if use_branch:
                coverage["dependent"] = use_branch
            # C2-06: resolve display via codes/data/
            # hl7-subscriber-relationship.yaml — was raw code emission.
            # Beneficiary's relationship to the subscriber: 被扶養者 → not self.
            # Issue #3000: a minor on a guardian's policy is the subscriber's
            # child; the subscriber is the guardian on record, else the policy
            # holder is named by role only (no fabricated person).
            is_minor = bool(dob) and age_at_period_start < gates["primary_subscriber_min_age"]
            if is_minor and (category == "dependent" or base_category in minor_dependent):
                rel_code = "child"
                guardian = _guardian_subscriber(patient_data)
                if guardian:
                    coverage["subscriber"] = guardian
                else:
                    coverage.pop("subscriber", None)
                    coverage["policyHolder"] = {
                        "display": t("fhir_emit_text.coverage_policy_holder_guardian", lang_for(country))
                    }
            else:
                rel_code = "other" if category == "dependent" else "self"
            coverage["relationship"] = {
                "coding": [
                    system_coding(
                        "hl7-subscriber-relationship",
                        rel_code,
                        lang_for(country),
                    )
                ]
            }
            # Coverage.type: human label (text-only CodeableConcept — no fabricated codes).
            label = type_labels.get(category)
            if label:
                coverage["type"] = {"text": label}
            # Coverage.period — Issue #923 §Fix 1: one FY per row.
            # Explicit enrollment valid_from / valid_to still wins (Phase 2
            # will emit period-bounded enrollments; when they do, respect
            # those over the derived FY boundary).
            if enr.get("valid_from") or enr.get("valid_to"):
                period: dict[str, str] = {}
                if enr.get("valid_from"):
                    period["start"] = str(enr["valid_from"])
                if enr.get("valid_to"):
                    period["end"] = str(enr["valid_to"])
            else:
                period = {"start": fy_start.isoformat(), "end": fy_end.isoformat()}
            coverage["period"] = period
            # C3-08: Coverage.class[] — group / plan
            # classification. For JP, class[0].type=group with 保険者番号 as
            # the coverage class identifier.
            # C5-09: diversify to include both `group` and
            # `plan` classifications when insurer symbol resolves to a plan
            # name — plan carries the human-readable insurance product name.
            _class_entries: list[dict[str, Any]] = [
                {
                    "type": {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-coverage-class"),
                                "code": "group",
                                # Issue #3026: English display; the label is text.
                                "display": t("fhir_emit_text.coverage_class_group", "en"),
                            }
                        ],
                        **text_if_localized(
                            t("fhir_emit_text.coverage_class_group", "en"),
                            t("fhir_emit_text.coverage_class_group", lang_for(country)),
                        ),
                    },
                    "value": insurer,
                    "name": name_map.get(insurer, insurer),
                }
            ]
            if use_symbol:
                _class_entries.append(
                    {
                        "type": {
                            "coding": [
                                {
                                    "system": get_system_uri("hl7-coverage-class"),
                                    "code": "plan",
                                    # Issue #3026: English display; the label is text.
                                    "display": t("fhir_emit_text.coverage_class_plan", "en"),
                                }
                            ],
                            **text_if_localized(
                                t("fhir_emit_text.coverage_class_plan", "en"),
                                t("fhir_emit_text.coverage_class_plan", lang_for(country)),
                            ),
                        },
                        "value": use_symbol,
                        "name": name_map.get(insurer, insurer),
                    }
                )
            coverage["class"] = _class_entries
            # CY7-14 (Chain-7): Coverage.costToBeneficiary — JP 自己負担割合.
            # Issue #3016: JP follows age on the period start and the income
            # tier (``jp_copay_pct``); other countries keep the category proxy.
            if is_jp(country) and dob:
                _coshare_pct = jp_copay_pct(dob, fy_start, income_q, country)
            else:
                _coshare_pct = 10 if category == "late_elderly" else 30
            coverage["costToBeneficiary"] = [
                {
                    "type": {
                        "coding": [
                            {
                                "system": get_system_uri("hl7-coverage-copay-type"),
                                "code": "copaypct",
                                "display": "Copay percentage",
                            }
                        ],
                        "text": t("fhir_emit_text.copay_percentage", lang_for(country)),
                    },
                    "valueQuantity": ucum_quantity(_coshare_pct, "%"),
                }
            ]
            resources.append(coverage)

    return resources


def _build_patient(
    p: dict, country: str, encounters: list[dict] | None = None, snapshot_date: str | None = None
) -> dict:
    """Build FHIR Patient resource with locale-aware name. ``encounters`` /
    ``snapshot_date`` place the current Coverage whose member identifier the
    Patient carries where the locale asks for it (Issue #3149)."""
    # Extract name from patient profile
    name_data = p.get("name", {})
    family = name_data.get("family_name", p.get("patient_id", ""))
    given = name_data.get("given_name", "")

    gender = "female" if p.get("sex") == "F" else "male"
    dob = p.get("date_of_birth")

    # Build FHIR HumanName. C2-19: JP Core requires
    # kanji + kana names as TWO separate name[] entries, each tagged with the
    # ISO21090 EN-representation extension using `valueCode` (was
    # `valueString` — an FHIR schema violation, JP Core validators reject).
    # Kanji name → IDE (ideographic), phonetic (katakana / hiragana) → SYL.
    ISO21090_URL = "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation"
    # C4-12: HumanName.use = "official" per FHIR R4 spec
    # and JP Core Patient recommendation for the registered / kanji name.
    names: list[dict[str, Any]] = []
    if is_jp(country):
        # Kanji entry — always emitted for JP.
        # Issue #378: JP_Patient_eCS requires `name.text` (min=1). Concatenate
        # kanji family + given with a single space (JP clinical convention:
        # "田中 徹") so the eCS profile assertion is data-complete.
        kanji_name: dict[str, Any] = {
            "use": "official",
            "text": f"{family} {given}".strip(),
            "family": family,
            "given": [given],
            "extension": [{"url": ISO21090_URL, "valueCode": "IDE"}],
        }
        names.append(kanji_name)
        # Phonetic (kana) entry — emitted only when phonetic pair present.
        # Issue #732: population/engine.py emits `PersonName.phonetic` as a
        # single string "<family-kana> <given-kana>" (see PersonName typed as
        # `str | None`), so the historical `isinstance(phonetic, dict)` gate
        # silently skipped 100% of JP Patients — no SYL entry across the
        # baseline. Accept both shapes so the emit doesn't rely on an upstream
        # schema unification: dict-form (already correct) OR string-form
        # (split on whitespace into family + given kana).
        phonetic = name_data.get("phonetic")
        kana_family = kana_given = ""
        if isinstance(phonetic, dict):
            kana_family = phonetic.get("family_name", "")
            kana_given = phonetic.get("given_name", "")
        elif isinstance(phonetic, str) and phonetic.strip():
            _parts = phonetic.strip().split(None, 1)
            kana_family = _parts[0] if _parts else ""
            kana_given = _parts[1] if len(_parts) > 1 else ""
        if kana_family or kana_given:
            _kana_fam = kana_family or family
            _kana_giv = kana_given or given
            names.append(
                {
                    "use": "official",
                    "text": f"{_kana_fam} {_kana_giv}".strip(),
                    "family": _kana_fam,
                    "given": [_kana_giv],
                    "extension": [{"url": ISO21090_URL, "valueCode": "SYL"}],
                }
            )
    else:
        names.append({"use": "official", "family": family, "given": [given]})
    names[0]  # kept for legacy readers below

    pid = p.get("patient_id", str(uuid.uuid4()))
    # Hospital MRN identifier system, from the locale (Issue #3149: JP
    # builds the JP-CLINS facility patient-ID OID from the 10-digit
    # 医療機関コード; Issue #1763: US uses a project-owned https URL).
    _patient_cfg = _identity_cfg(country).get("fhir_patient") or {}
    mrn_system = str(_patient_cfg.get("mrn_system", "")).format(**load_facility_identity(country))
    resource: dict[str, Any] = {
        "resourceType": "Patient",
        # Issue #854 Bucket C row 18 (PR-patient): opaque `pt-<12hex>` id.
        # The CIF `patient_id` = ``POP-{n:06d}`` slug is preserved on
        # `.identifier[]` under POPULATION_SLUG_KEY_SYSTEM for
        # round-trip / consumer lookup.
        "id": resolve_patient_id(pid),
        # C2-20: declare JP Core Patient conformance
        # for JP exports. US export intentionally omits — no US Core profile
        # is asserted (a separate roadmap item).
        #
        # Issue #378 (restoring #379 with data-completeness):
        # JP_Patient_eCS assertion RESTORED. #382 removed the URI because
        # #379 had shipped URI-only without emitting the required fields
        # (`name.text`, `address.text`, `meta.lastUpdated`) — the resulting
        # 5× validator cascade justified the revert (feedback:
        # `feedback_profile_assertion_requires_data_completeness`). This PR
        # emits all three required fields BEFORE claiming the profile, so
        # the assertion is now data-complete and the eCS Pattern B (3,096
        # errors on referring resources) is resolved without the earlier
        # cascade. SD-verified min=1 requirements: `meta.lastUpdated`,
        # `meta.profile`, `name`, `name.text`, `name.given`, `gender`,
        # `birthDate`, `address`, `address.text`.
        **(
            {
                "meta": {
                    "profile": [
                        "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient",
                        "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Patient_eCS",
                    ],
                    # Static deterministic timestamp mirrors `fhir_r4/encounters/facility.py`
                    # (pattern). Real-world lastUpdated is server-
                    # provided; clinosim's simulator has no such notion, so
                    # a fixed value keeps reproducibility byte-clean while
                    # satisfying the eCS min=1 requirement.
                    "lastUpdated": "2026-01-01T00:00:00+09:00",
                }
            }
            if is_jp(country)
            else {}
        ),
        "identifier": [
            {
                "use": "usual",
                "type": {
                    "coding": [
                        {
                            "system": get_system_uri("hl7-v2-0203"),
                            "code": "MR",
                            "display": "Medical Record Number",
                        }
                    ],
                    "text": t("fhir_emit_text.mrn", lang_for(country)),
                },
                "system": mrn_system,
                "value": pid,
                "assigner": {"reference": "Organization/hospital-main"},
            },
            # Issue #854 PR-patient: preserve the CIF simulation-slug
            # `POP-{n}` on identifier[] so consumers keyed on the
            # human-readable generation id can recover it after the
            # `.id` opaque migration.
            wrap_as_identifier(pid, POPULATION_SLUG_KEY_SYSTEM),
        ],
        "active": True,
        "name": names,
        "gender": gender,
    }

    # Issue #3141: which national identifier the Patient carries is country
    # data (identity.yaml ``fhir_patient.national_identifier``).
    _national_id = _patient_cfg.get("national_identifier")
    if _national_id and p.get("patient_id"):
        resource["identifier"].append(_NATIONAL_IDENTIFIER_BUILDERS[str(_national_id)](pid))
    # Issue #3149: JP_Patient_eCS R1012 — exactly one insured-person
    # identifier, the current Coverage's member identifier.
    if _patient_cfg.get("insured_identifier_from_coverage"):
        member_system = str((_identity_cfg(country).get("fhir_coverage") or {}).get("member_id_system", ""))
        insured = _current_member_identifier(
            _build_coverage_resources(p, country, encounters, snapshot_date), member_system
        )
        if insured is not None:
            resource["identifier"].append(insured)

    if dob:
        resource["birthDate"] = to_fhir_date(dob)

    # Issue #1344: US Core Patient extensions (us-core-race,
    # us-core-ethnicity, us-core-birthsex) — must-support on US Core
    # AllPatients profile. Sourced from PatientProfile.race /
    # PatientProfile.ethnicity (US demographics.yaml `race_distribution`
    # / `ethnicity_distribution`, populated by
    # ``patient.activator`` for the US locale) and PatientProfile.sex.
    # US-only emit: JP locale has no equivalent extension slot and the
    # sim's population module currently only samples race/ethnicity for
    # US. Unknown / unmapped slugs are silently omitted rather than
    # emitting a fabricated OMB code (feedback_empty_vs_wrong_assertion).
    if not is_jp(country):
        _uc_extensions: list[dict[str, Any]] = []
        _race_ext = _build_us_core_race_extension(str(p.get("race") or ""))
        if _race_ext:
            _uc_extensions.append(_race_ext)
        _eth_ext = _build_us_core_ethnicity_extension(str(p.get("ethnicity") or ""))
        if _eth_ext:
            _uc_extensions.append(_eth_ext)
        _bs_ext = _build_us_core_birthsex_extension(str(p.get("sex") or ""))
        if _bs_ext:
            _uc_extensions.append(_bs_ext)
        if _uc_extensions:
            resource.setdefault("extension", []).extend(_uc_extensions)

    # CY7-15 (Chain-7): multipleBirthBoolean — required by JP Core Patient
    # profile 0..1. Default false (majority — realistic multiple-birth
    # rate <2% for JP live-birth records but registered explicitly on
    # birth certificate). Population module doesn't currently model this,
    # so default across cohort is a defensible completeness fix (Coverage:
    # boolean false is a valid emit per FHIR R4).
    resource["multipleBirthBoolean"] = False

    # CY7-16 (Chain-7): deceased[Boolean|DateTime] — carries mortality
    # status. Default deceasedBoolean=false because Patient records in
    # clinosim represent the living cohort at snapshot time; if the CIF
    # marks the patient as deceased, override with deceasedDateTime.
    _dod = p.get("date_of_death", "") or p.get("dod", "")
    if _dod:
        # Issue #2984: a documented time of death (in-hospital death: the
        # expired encounter's discharge) is the deceased instant.
        # Issue #1440: a death known by date alone expands to end-of-day
        # so same-day intra-day events fall before the deceased moment.
        resource["deceasedDateTime"] = to_fhir_deceased_datetime(p.get("death_datetime") or _dod, country)
        # Issue #926: FHIR `Patient.active` = "Whether this patient's record
        # is in active use." A deceased patient's record is by definition no
        # longer in active use. Flip active=false whenever the CIF marks
        # the patient as deceased (deceasedDateTime is set). Living patients
        # keep the default active=true set above.
        resource["active"] = False
    else:
        resource["deceasedBoolean"] = False

    # Blood type: v3 fix — JP Core (as of jpfhir.jp.core#1.2.0)
    # does not define a `JP_Patient_BloodTypeCode` Extension, and neither
    # FHIR core nor US Core specifies a Patient-level BloodType extension.
    # The URL we used to emit was fabricated; v3 validation flagged all
    # 580 JP Patients with an unknown-extension warning (580 resources /
    # ext URL). The follow-up chain now emits blood type as two
    # laboratory Observations per patient (LOINC 883-9 ABO group +
    # LOINC 10331-7 Rh group, SNOMED CT valueCodeableConcept) via
    # `_bb_blood_type` (`labs/blood_type.py`); the Patient resource
    # stays free of a fabricated extension.
    _ = p.get("blood_type")  # explicit no-op: blood type is emitted as Observation, not on Patient

    # Address
    addr = p.get("address")
    if addr and isinstance(addr, dict):
        fhir_addr = build_address(addr, country)
        if fhir_addr:
            resource["address"] = [fhir_addr]

    # Telecom (phone)
    contact = p.get("contact")
    if contact and isinstance(contact, dict):
        telecoms = build_telecom(contact)
        if telecoms:
            resource["telecom"] = telecoms

    # Marital status
    marital = p.get("marital_status", "")
    if marital:
        # Issue #3026: English HL7 display on the coding, the label in text.
        resource["maritalStatus"] = english_display_concept("hl7-v3-maritalstatus", marital, lang_for(country))

    # Communication / preferred language
    lang = p.get("preferred_language", "")
    if lang:
        # BCP-47 (`urn:ietf:bcp:47`) is English-only per both validators'
        # tx-server loadouts, but the two we target expect different
        # English displays. Issue #1764: HL7 base + US Core v9 require
        # the IETF canonical form (`English (United States)`, with a
        # space), while fhir-jp-validator registered the no-space form
        # (`English(US)`). The variant is a profile rule (JP output is
        # validated against JP Core), chosen by country (Issue #2481).
        _lang_display = bcp47_display(lang, profile="jp-core" if is_jp(country) else None) or ""
        resource["communication"] = [
            {
                "language": {
                    "coding": [
                        {
                            "system": get_system_uri("bcp-47-language"),
                            "code": lang,
                            **display_entry(_lang_display),
                        }
                    ],
                },
                "preferred": True,
            }
        ]

    # Issue #3182: the emergency contact is a RelatedPerson
    # (``demographics/related_person.py``), not Patient.contact —
    # JP_Patient_eCheckupGeneral reserves Patient.contact for the workplace.

    # Issue #743: JP_Patient_eCS declares `JP_eCS_InstitutionNumber` as
    # must-support (the Department extension context excludes Patient).
    # Attach here (inline) because Patient's eCS profile URL is set
    # directly on this builder, not via `_apply_jp_clins_profile` post-hook.
    from clinosim.modules.output.fhir_r4.lib.ecs_extensions import attach_ecs_institutional_extensions

    attach_ecs_institutional_extensions(resource, country, include_department=False)

    return resource


# ============================================================
# AllergyIntolerance
# ============================================================


# Occupation category localization for Observation.valueCodeableConcept
def _build_occupation_observation(
    occupation: str,
    patient_id: str,
    country: str,
) -> dict | None:
    """Build FHIR Observation for patient occupation (social history).

    Uses US Core Patient Occupation profile (LOINC 11341-5).
    Reference: http://hl7.org/fhir/us/core/StructureDefinition/us-core-occupation
    """
    if not occupation:
        return None
    # Issue #2630: a child below working age has no occupation.
    from clinosim.modules.population._identity import DEVELOPMENTAL_STAGES

    if occupation in DEVELOPMENTAL_STAGES:
        return None
    # Issue #2269: the occupation vocabulary shared with narrative and LLM
    # prompts; an unknown slug is humanised (a test keeps every generated
    # slug in the table).
    display = vocab_display("occupation", occupation, lang_for(country), fallback=occupation.replace("_", " "))
    _occupation_key = patient_id
    return {
        "resourceType": "Observation",
        "id": _resolve_occupation_id(_occupation_key),
        "identifier": [wrap_as_identifier(_occupation_key, OCCUPATION_KEY_SYSTEM)],
        # chain #2: JP Core Observation_Common profile.
        **({"meta": {"profile": [JP_OBSERVATION_COMMON_PROFILE]}} if is_jp(country) else {}),
        "status": "final",
        "category": _social_category(country),
        "code": {
            "coding": [loinc_coding("11341-5", "en")],
            "text": t("fhir_emit_text.occupation", lang_for(country)),
        },
        "subject": patient_ref(patient_id),
        "valueCodeableConcept": {
            "coding": [
                {
                    "system": get_system_uri("occupation-category"),
                    "code": occupation,
                    "display": display,
                }
            ],
            "text": display,
        },
    }
