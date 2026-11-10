"""FHIR / encounter / outpatient / identity locale loaders — encounter
disposition defaults, ambulatory visit-length distributions, external
organization catalog, practitioner qualifications, resident identity
config.

Extracted from the historical god-file ``clinosim/locale/loader.py`` as
the final step C2d of the full-review Phase C locale split, continuing
B1 / C2a / C2b / C2c. After this PR ``loader.py`` becomes a pure
re-export barrel — every historical loader lives in a submodule under
``clinosim/locale/loaders/``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.locale._io import (
    _FALLBACK_ENCOUNTER_DISPOSITION,
    _LOCALE_DIR,
    _country_dir,
    _load_yaml,
)


@lru_cache(maxsize=1)
def load_encounter_disposition_defaults() -> dict[str, Any]:
    """Load Encounter.hospitalization fallback defaults (Issue #941).

    Single-source-of-truth for the HL7 admit-source / discharge-disposition
    fallback codes and JP-CLINS ValueSet binding URLs used by the FHIR emit
    path when the CIF encounter carries no explicit disposition. See
    ``clinosim/locale/shared/encounter_disposition_defaults.yaml``.
    """
    raw = _load_yaml(
        _LOCALE_DIR / "shared" / "encounter_disposition_defaults.yaml",
        fallback=_FALLBACK_ENCOUNTER_DISPOSITION,
    )
    if not isinstance(raw, dict):
        return _FALLBACK_ENCOUNTER_DISPOSITION
    # Fail-soft merge with fallback so a partial yaml still yields a
    # complete config (each required key has a hardcoded default).
    merged: dict[str, Any] = {}
    for slot, defaults in _FALLBACK_ENCOUNTER_DISPOSITION.items():
        entry = raw.get(slot) or {}
        if not isinstance(entry, dict):
            entry = {}
        merged[slot] = {**defaults, **entry}
    return merged


@lru_cache(maxsize=2)
def load_ambulatory_visit_length(country: str) -> dict[str, Any]:
    """Load per-visit-type ambulatory (outpatient) encounter length distributions.

    Returned shape:

        {
          "visit_types": {
             "chronic_followup": {"min": int, "mode": int, "max": int},
             "post_discharge":   {"min": int, "mode": int, "max": int},
             "pediatric_visit":  {"min": int, "mode": int, "max": int},
             "health_screening": {"min": int, "mode": int, "max": int},
             ...
          },
          "default": {"min": int, "mode": int, "max": int},
        }

    Issue #927: pre-fix outpatient length was a flat ``rng.integers(15, 45)``
    regardless of visit purpose, which excluded the 5-10 min return-visit
    peak that dominates JP primary-care volume. This loader is the single
    source-of-truth for the per-visit-type triangular distributions used
    by ``clinosim.simulator.outpatient._sample_ambulatory_visit_length_minutes``.
    """
    fallback = {
        "visit_types": {},
        "default": {"min": 15, "mode": 25, "max": 45},
    }
    data = _load_yaml(_country_dir(country) / "ambulatory_visit_length.yaml", fallback=fallback)
    _validate_ambulatory_visit_length(data, country)
    return data


def _validate_ambulatory_visit_length(data: dict, country: str) -> None:
    """Fail loud if the yaml is malformed — every distribution must satisfy
    0 < min <= mode <= max. Triangular sampling silently degenerates when
    the invariant is violated, so we catch it at import time."""
    if not isinstance(data, dict):
        raise ValueError(
            f"ambulatory_visit_length.yaml ({country}): top-level must be a dict, got {type(data).__name__}"
        )

    def _check_bucket(name: str, bucket: Any) -> None:
        if not isinstance(bucket, dict):
            raise ValueError(
                f"ambulatory_visit_length.yaml ({country}): {name!r} must be a dict, got {type(bucket).__name__}"
            )
        for k in ("min", "mode", "max"):
            if k not in bucket:
                raise ValueError(f"ambulatory_visit_length.yaml ({country}): {name!r} missing key {k!r}")
            v = bucket[k]
            if not isinstance(v, int | float) or isinstance(v, bool):
                raise ValueError(f"ambulatory_visit_length.yaml ({country}): {name}.{k}={v!r} must be numeric")
        lo, mode, hi = float(bucket["min"]), float(bucket["mode"]), float(bucket["max"])
        if not (0 < lo <= mode <= hi):
            raise ValueError(
                f"ambulatory_visit_length.yaml ({country}): {name!r} requires 0 < min ({lo}) <= "
                f"mode ({mode}) <= max ({hi})"
            )

    default = data.get("default")
    if default is None:
        raise ValueError(f"ambulatory_visit_length.yaml ({country}): missing top-level 'default' block")
    _check_bucket("default", default)

    visit_types = data.get("visit_types", {}) or {}
    if not isinstance(visit_types, dict):
        raise ValueError(
            f"ambulatory_visit_length.yaml ({country}): 'visit_types' must be a dict, got {type(visit_types).__name__}"
        )
    for name, bucket in visit_types.items():
        _check_bucket(f"visit_types.{name}", bucket)


@lru_cache(maxsize=8)
def load_external_organizations(country: str) -> list[dict[str, Any]]:
    """Load the external referring / receiving hospital catalog for a country.

    Issue #924: JP-CLINS 診療情報提供書 (referral letter, LOINC 57133-1)
    Composition emit needs a pool of external Organizations to reference in
    the 910 (紹介先) section — previously both 920 and 910 collapsed to
    ``Organization/hospital-main`` for every referral. Returns the flat
    ``external_hospitals`` list from ``<country>/external_organizations.yaml``
    (list of dicts with ``id``, ``name``, ``type``, ``type_code``,
    ``type_display``, ``address``, ``institution_code``, ``phone``).

    Countries without the file (US today) get an empty list — callers must
    treat that as "no external-organization catalog available" and fall back
    to their prior emit behavior.
    """
    data = _load_yaml(_country_dir(country) / "external_organizations.yaml", fallback={})
    entries = data.get("external_hospitals", []) if isinstance(data, dict) else []
    return list(entries) if isinstance(entries, list) else []


@lru_cache(maxsize=8)
def load_facility_identity(country: str) -> dict[str, Any]:
    """The simulated hospital's own identity (Issue #3129): ``prefecture``,
    the 10-digit ``institution_code`` (医療機関コード) and the address's
    ``postal_code`` (Issue #3155) from
    ``<country>/facility_identity.yaml``; empty for a country without the
    file (US)."""
    data = _load_yaml(_country_dir(country) / "facility_identity.yaml", fallback={})
    hospital = data.get("hospital") if isinstance(data, dict) else None
    return dict(hospital) if isinstance(hospital, dict) else {}


@lru_cache(maxsize=8)
def load_encounter_type_profiles(country: str) -> dict[str, dict[str, Any]]:
    """Profile-mandated Encounter structure per CIF encounter type
    (Issue #3155): ``class`` (``system_key`` / ``code``), ``profile`` and
    ``service_provider`` from ``<country>/encounter_type_profiles.yaml``;
    empty for a country without the file (US)."""
    data = _load_yaml(_country_dir(country) / "encounter_type_profiles.yaml", fallback={})
    if not isinstance(data, dict):
        return {}
    return {str(k): dict(v) for k, v in data.items() if k != "metadata" and isinstance(v, dict)}


@lru_cache(maxsize=8)
def load_checkup_questionnaire(country: str) -> dict[str, Any]:
    """Health-checkup questionnaire answers derived from the record (Issue
    #3163): ``item_code_system``, ``category``, ``questionnaires`` (checkup
    type -> item keys) and ``items`` from
    ``<country>/checkup_questionnaire.yaml``; empty for a country without the
    file (US)."""
    data = _load_yaml(_country_dir(country) / "checkup_questionnaire.yaml", fallback={})
    if not isinstance(data, dict) or not data.get("items"):
        return {}
    items = {str(k): dict(v) for k, v in data["items"].items()}
    questionnaires = {str(k): [str(i) for i in v or []] for k, v in (data.get("questionnaires") or {}).items()}
    unknown = sorted({i for v in questionnaires.values() for i in v} - set(items))
    if unknown:
        raise ValueError(f"checkup_questionnaire.yaml: questionnaires name unknown items {unknown}")
    return {
        "item_code_system": str(data["item_code_system"]),
        "category": str(data["category"]),
        "questionnaires": questionnaires,
        "items": items,
    }


@lru_cache(maxsize=8)
def load_checkup_report_items(country: str) -> dict[str, Any]:
    """Health-checkup results as report Observations (Issue #3154):
    ``observation_profile``, ``code_system``, ``items`` (internal lab
    name -> item code), ``measurement_items`` (lab name -> category of a
    body measurement, Issue #3167) and the profile's shape rules from
    ``<country>/checkup_report_items.yaml``; empty for a country without
    the file (US)."""
    data = _load_yaml(_country_dir(country) / "checkup_report_items.yaml", fallback={})
    if not isinstance(data, dict) or not data.get("items"):
        return {}
    return {
        "observation_profile": str(data["observation_profile"]),
        "identifier_system": str(data.get("identifier_system") or ""),
        "forbidden_elements": [str(e) for e in data.get("forbidden_elements") or []],
        "category_max": int(data.get("category_max") or 0),
        "code_system": str(data["code_system"]),
        "items": {str(k): str(v) for k, v in data["items"].items()},
        "measurement_items": {str(k): str(v) for k, v in (data.get("measurement_items") or {}).items()},
    }


@lru_cache(maxsize=8)
def load_practitioner_qualifications(country: str) -> dict[str, Any]:
    """Load JP MHLW national-license qualification + license-number tables
    (Issue #962).

    Returned shape:

        {
          "code_system": "urn:oid:...",
          "license_identifier_salt": "practitioner-license-2026",
          "qualification_codes": {
             "physician": {"code": "MedicalDoctor", "display": "医師"},
             ...
          },
          "physician_specialty_boards": {
             "cardiology": {"code": "CardiologySpecialist",
                            "display": "循環器専門医"},
             ...
          },
          "license_identifiers": {
             "physician": {"system": "http://...",
                            "label": "医籍番号", "prefix": "第",
                            "suffix": "号", "digits": 6},
             ...
          },
        }

    Empty dict if the file is absent (US, `_template`) — callers then skip
    the JP-CLINS qualification / license identifier emit and fall back to
    the existing v2-0360 / text-only qualification path.
    """
    return _load_yaml(_country_dir(country) / "practitioner_qualifications.yaml", fallback={})


@lru_cache(maxsize=8)
def load_identity_config(country: str) -> dict[str, Any]:
    """Load resident identifier / insurance numbering config for a country (AD-54).

    Returns payer representative sets, age-banded card/insurance rates, household
    correlation, and insurance category distribution. Empty dict if absent (e.g. US,
    which keeps its existing insurance handling in Phase 1).
    """
    return _load_yaml(_country_dir(country) / "identity.yaml", fallback={})


class _ClosedPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: str = Field(pattern=r"^\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{2}-\d{2}$")


class _FixedHoliday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    month: int = Field(ge=1, le=12)
    day: int = Field(ge=1, le=31)
    from_year: int = 0


class _NthWeekdayHoliday(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    month: int = Field(ge=1, le=12)
    weekday: int = Field(ge=0, le=6)
    n: int = Field(ge=-1, le=5)


class _FederalHolidays(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fixed: list[_FixedHoliday] = Field(default_factory=list)
    nth_weekday: list[_NthWeekdayHoliday] = Field(default_factory=list)


class ClinicCalendar(BaseModel):
    """Shape of ``locale/<country>/clinic_calendar.yaml`` (Issue #3018)."""

    model_config = ConfigDict(extra="forbid")

    closed_weekdays: list[int] = Field(default_factory=list)
    closed_periods: list[_ClosedPeriod] = Field(default_factory=list)
    # Year -> closed public holidays as "MM-DD" (JP: the Cabinet Office list).
    holidays: dict[int, list[str]] = Field(default_factory=dict)
    # Rule-based federal holidays (US).
    federal_holidays: _FederalHolidays | None = None


@lru_cache(maxsize=4)
def load_clinic_calendar(country: str) -> dict[str, Any]:
    """The country's outpatient clinic calendar (Issue #3018): closed weekdays,
    closed periods and public holidays. A country without the file has no
    closed day."""
    raw = _load_yaml(_country_dir(country) / "clinic_calendar.yaml", fallback={})
    return ClinicCalendar.model_validate(raw or {}).model_dump()


def resident_insurer_number(country: str, scheme: str, prefecture: str, city: str) -> str:
    """保険者番号 of the ``scheme`` insurer serving a residence (Issue #3015):
    the identity.yaml ``payers[scheme]`` entry for the ``prefecture`` (and,
    when the entry names one, the ``city``) — 国民健康保険 by municipality,
    後期高齢者医療 by prefecture. ``""`` when no entry serves the residence."""
    for entry in (load_identity_config(country).get("payers", {}) or {}).get(scheme) or []:
        if entry.get("prefecture") and entry["prefecture"] != prefecture:
            continue
        if entry.get("city") and entry["city"] != city:
            continue
        if entry.get("prefecture"):
            return str(entry["number"])
    return ""
