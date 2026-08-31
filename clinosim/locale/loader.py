"""Locale data loader — single access point for all country/language-specific data.

Holds only culture/country-dependent data. Terminology/display files were migrated
to clinosim/codes/ (international code systems); they no longer live under locale/.

Directory structure (country-based):
  locale/
    jp/
      names.yaml, addresses.yaml, demographics.yaml, formatting.yaml,
      identity.yaml, immunization_schedule.yaml, code_mapping_*.yaml
    us/
      (same shape as jp/)
    shared/
      naming_rules.yaml, chronic_medications.yaml, chronic_followup.yaml,
      drug_names_ja.yaml
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_LOCALE_DIR = Path(__file__).parent

# ISO 3166-1 alpha-2 lowercase
_COUNTRY_DIR_MAP = {"JP": "jp", "US": "us"}


def _country_dir(country: str) -> Path:
    # P2-14: `_template` scaffold directory MUST NOT be usable
    # as a country. Reject any code that resolves to a leading-underscore
    # folder — those are reserved for structural scaffolds (see
    # `docs/add-your-country.md`).
    dir_name = _COUNTRY_DIR_MAP.get(country, country.lower())
    if dir_name.startswith("_"):
        raise ValueError(
            f"country={country!r} resolves to reserved scaffold folder "
            f"{dir_name!r}. Country codes must map to a real locale."
        )
    return _LOCALE_DIR / dir_name


def _validate_demographics(data: dict) -> None:
    """Validate demographics.yaml at load time — fail loud on weight violations.

    Checks the OPTIONAL lifestyle_distribution block (smoking + alcohol per
    sex_key). The fallback ``_FALLBACK_DEMOGRAPHICS`` has no lifestyle block,
    so a missing block is a valid state (skip). When the block IS present,
    validate that each distribution has only non-negative weights with sum > 0 —
    these are the preconditions for
    ``normalize_probabilities(..., fallback="raise")`` at the
    ``population/engine.py`` callsites (smoking_dist :170, alcohol_dist :180).
    """
    if not isinstance(data, dict):
        raise ValueError(f"demographics.yaml: top-level must be a dict, got {type(data).__name__}")
    lifestyle = data.get("lifestyle_distribution")
    if lifestyle is None:
        return  # OK: optional block absent
    if not isinstance(lifestyle, dict):
        raise ValueError(f"demographics.yaml: lifestyle_distribution must be a dict, got {type(lifestyle).__name__}")
    for behavior in ("smoking", "alcohol"):
        per_sex = lifestyle.get(behavior)
        if per_sex is None:
            continue  # OK: behavior absent
        if not isinstance(per_sex, dict):
            raise ValueError(
                f"demographics.yaml: lifestyle_distribution.{behavior} must be a dict, got {type(per_sex).__name__}"
            )
        for sex_key, dist in per_sex.items():
            if not isinstance(dist, dict):
                raise ValueError(
                    f"demographics.yaml: lifestyle_distribution.{behavior}."
                    f"{sex_key!r} must be a dict, got {type(dist).__name__}"
                )
            weights: list[float] = []
            for level, w in dist.items():
                try:
                    w_f = float(w)
                except (TypeError, ValueError) as exc:
                    raise ValueError(
                        f"demographics.yaml: lifestyle_distribution.{behavior}."
                        f"{sex_key!r}.{level!r} weight non-numeric: {w!r}"
                    ) from exc
                if w_f < 0:
                    raise ValueError(
                        f"demographics.yaml: lifestyle_distribution.{behavior}."
                        f"{sex_key!r}.{level!r} has negative weight {w_f}"
                    )
                weights.append(w_f)
            if weights and sum(weights) <= 0:
                raise ValueError(
                    f"demographics.yaml: lifestyle_distribution.{behavior}.{sex_key!r} has zero-sum weights {weights}"
                )


def _validate_names(data: dict) -> None:
    """Validate names.yaml — surnames + given_names lists with non-negative weights.

    Tolerates the ``_FALLBACK_NAMES`` dict (which has small but valid weights).
    For each list present (``surnames`` / ``given_names_male`` /
    ``given_names_female``), requires each weight to be non-negative and the sum
    to be > 0 (precondition for ``normalize_probabilities(..., fallback="raise")``
    in population/engine.py callsites :485 and :517). An absent list is OK
    (validator does not require all three).
    """
    if not isinstance(data, dict):
        raise ValueError(f"names.yaml: top-level must be a dict, got {type(data).__name__}")
    for key in ("surnames", "given_names_male", "given_names_female"):
        items = data.get(key)
        if items is None:
            continue  # OK: optional list absent
        if not isinstance(items, list):
            raise ValueError(f"names.yaml: {key!r} must be a list, got {type(items).__name__}")
        if not items:
            continue  # OK: empty list (upstream normalize_probabilities raises on empty)
        weights: list[float] = []
        for entry in items:
            if not isinstance(entry, dict):
                raise ValueError(f"names.yaml: {key!r} entry must be a dict, got {entry!r}")
            try:
                w = float(entry.get("weight", 0))
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"names.yaml: {key!r}.{entry.get('name')!r} weight non-numeric: {entry.get('weight')!r}"
                ) from exc
            if w < 0:
                raise ValueError(f"names.yaml: {key!r}.{entry.get('name')!r} has negative weight {w}")
            weights.append(w)
        if weights and sum(weights) <= 0:
            raise ValueError(f"names.yaml: {key!r} has zero-sum weights")


def _validate_addresses(data: dict) -> None:
    """Validate addresses.yaml — cities list with non-negative weights.

    Tolerates missing / empty cities (upstream ``_generate_household_address``
    has a ``if not cities: return`` guard). When cities are present, requires
    non-negative weights with sum > 0 (precondition for
    ``normalize_probabilities(..., fallback="raise")`` at
    population/engine.py:664).
    """
    if not isinstance(data, dict):
        raise ValueError(f"addresses.yaml: top-level must be a dict, got {type(data).__name__}")
    cities = data.get("cities")
    if cities is None:
        return  # OK: empty fallback ({}) takes this path
    if not isinstance(cities, list):
        raise ValueError(f"addresses.yaml: 'cities' must be a list, got {type(cities).__name__}")
    if not cities:
        return  # OK: empty list (upstream guards against use)
    weights: list[float] = []
    for entry in cities:
        if not isinstance(entry, dict):
            raise ValueError(f"addresses.yaml: cities entry must be a dict, got {entry!r}")
        try:
            w = float(entry.get("weight", 1))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"addresses.yaml: cities entry {entry.get('city')!r} weight non-numeric: {entry.get('weight')!r}"
            ) from exc
        if w < 0:
            raise ValueError(f"addresses.yaml: cities entry {entry.get('city')!r} has negative weight {w}")
        weights.append(w)
    if sum(weights) <= 0:
        raise ValueError("addresses.yaml: cities has zero-sum weights")


@lru_cache(maxsize=16)
def load_names(country: str) -> dict[str, Any]:
    """Load person name data for a country."""
    data = _load_yaml(_country_dir(country) / "names.yaml", fallback=_FALLBACK_NAMES)
    _validate_names(data)
    return data


@lru_cache(maxsize=16)
def load_naming_rules(country: str) -> dict[str, Any]:
    """Load naming rules for a country from shared/naming_rules.yaml."""
    all_rules = _load_yaml(_LOCALE_DIR / "shared" / "naming_rules.yaml", fallback={})
    dir_name = _COUNTRY_DIR_MAP.get(country, country.lower())
    return all_rules.get(dir_name, all_rules.get("us", {}))


@lru_cache(maxsize=32)
def load_terminology(domain: str, country: str) -> dict[str, str]:
    """Load display names for a domain (lab, diagnosis, drug, procedure).

    Example: load_terminology("lab", "JP") -> {"CRP": "C反応性蛋白", ...}
    """
    return _load_yaml(_country_dir(country) / f"terminology_{domain}.yaml", fallback={})


@lru_cache(maxsize=32)
def load_code_mapping(domain: str, country: str) -> dict[str, str]:
    """Load code mapping for a domain.

    Example: load_code_mapping("lab", "JP") -> {"CRP": "5C070", ...}
    """
    return _load_yaml(_country_dir(country) / f"code_mapping_{domain}.yaml", fallback={})


@lru_cache(maxsize=8)
def load_formatting(country: str) -> dict[str, Any]:
    """Load formatting rules for a country (date, time, units)."""
    return _load_yaml(_country_dir(country) / "formatting.yaml", fallback=_FALLBACK_FORMATTING)


@lru_cache(maxsize=8)
def _load_demographics_cached(country: str) -> dict[str, Any]:
    """Internal cached loader for raw demographics YAML (no mutation)."""
    data = _load_yaml(_country_dir(country) / "demographics.yaml", fallback=_FALLBACK_DEMOGRAPHICS)
    _validate_demographics(data)
    return data


def load_demographics(country: str) -> dict[str, Any]:
    """Load demographic data for population generation.

    Injects ``_country`` into the returned dict so downstream consumers
    (e.g. activate_patient) can determine locale without an extra argument.
    The underlying YAML is cached; this function returns a fresh shallow copy
    each call so callers may safely mutate the top-level dict.
    """
    result = dict(_load_demographics_cached(country))
    result["_country"] = country
    return result


@lru_cache(maxsize=1)
def load_chronic_medications() -> dict[str, Any]:
    """Load chronic condition home medications and monitoring rules.

    Issue #458: import-time route vocabulary validation. Same silent-no-op
    class as the disease / encounter YAMLs; an unknown `route:` string here
    would silently emit `{"text": VALUE}` with no SNOMED coding on the FHIR
    side.
    """
    data = _load_yaml(_LOCALE_DIR / "shared" / "chronic_medications.yaml", fallback={})
    _validate_chronic_medications_route_vocabulary(data)
    return data


def _iter_route_values(data: Any) -> Iterator[str]:
    """Yield every `route:` string found anywhere in a nested YAML structure.

    Third copy of this walker (sibling to disease/protocol.py and
    encounter/protocol.py). Kept local so the `locale` package retains its
    "loader lives with the data" convention and does not depend on either.
    """
    if isinstance(data, dict):
        for k, v in data.items():
            if k == "route" and isinstance(v, str):
                yield v
            else:
                yield from _iter_route_values(v)
    elif isinstance(data, list):
        for item in data:
            yield from _iter_route_values(item)


def _validate_chronic_medications_route_vocabulary(data: Any) -> None:
    """Delegate to the single-sourced canonical validator (Issue #458)."""
    from clinosim.modules.output.fhir_r4.lib.reference_data import validate_yaml_route_value

    for raw in _iter_route_values(data):
        validate_yaml_route_value(raw, source="chronic_medications.yaml")


@lru_cache(maxsize=1)
def load_perinatal_config() -> dict[str, Any]:
    """Load perinatal delivery configuration (Issue #957 Tier-3-B).

    Consumers query the ``encounter`` block for admission/discharge
    diagnosis + LOS + department, the ``procedure`` block for the
    JP/US billing code emitted on the delivery encounter, and the
    ``scheduling`` block for the delivery-month range used by the
    healthcare-calendar delivery-event scheduler.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "perinatal.yaml", fallback={})


@lru_cache(maxsize=1)
def load_chemo_regimens() -> dict[str, Any]:
    """Load chemotherapy regimen library + per-cancer assignment table.

    Issue #957 Tier-3-A: cycle-based chemotherapy scheduling. Consumers
    (population healthcare-calendar generator, chemo_visit emit path)
    query the top-level ``regimens`` dict for cycle interval / drugs /
    course_cycles, ``by_cancer`` for the per-cancer-code assignment
    probability distribution, ``procedure`` for the JP/US billing code
    on the emitted Procedure resource, and ``encounter`` for the visit
    reason string.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "chemo_regimens.yaml", fallback={})


@lru_cache(maxsize=8)
def load_addresses(country: str) -> dict[str, Any]:
    """Load address/phone data for a country."""
    data = _load_yaml(_country_dir(country) / "addresses.yaml", fallback={})
    _validate_addresses(data)
    return data


@lru_cache(maxsize=8)
def load_reference_ranges(country: str) -> dict[str, Any]:
    """Load lab reference range data for a country.

    Returns dict with 'source_url', 'source_name', and 'ranges' keys.
    Example: load_reference_ranges("JP") -> {"ranges": {"CRP": [{"low": 0, ...}], ...}}
    """
    return _load_yaml(_country_dir(country) / "reference_range_lab.yaml", fallback={})


@lru_cache(maxsize=1)
def load_chronic_followup() -> dict[str, Any]:
    """Load chronic disease outpatient follow-up schedules."""
    return _load_yaml(_LOCALE_DIR / "shared" / "chronic_followup.yaml", fallback={})


@lru_cache(maxsize=1)
def load_iv_infusion_defaults() -> dict[str, Any]:
    """Load per-drug default IV infusion rate / bolus duration catalog.

    Referenced by ``clinosim.modules.output.fhir_r4.lib.common
    .resolve_iv_infusion_default`` when emitting ``MedicationRequest
    .dosageInstruction.doseAndRate.rateQuantity`` (continuous drips) or
    ``dosageInstruction.timing.repeat.duration`` (intermittent bolus) for
    IV-route orders — Issue #966.

    Returned shape:

        {
          "drugs":  {<normalized name>: {"mode": ..., "rate_value": N, ...}},
          "aliases": {<shorthand>: <catalog key>},
          "default": {"mode": "bolus", "duration_min": 30},
        }

    Single source of truth for tunable clinical constants
    (feedback_constants_live_in_external_config.md); the Python side holds
    only mode dispatch logic and the fallback default block.
    """
    return _load_yaml(_LOCALE_DIR / "shared" / "iv_infusion_defaults.yaml", fallback={})


_FALLBACK_ENCOUNTER_DISPOSITION: dict[str, Any] = {
    "admit_source": {
        "system_key": "hl7-admit-source",
        "jp_clins_value_set": "http://jpfhir.jp/fhir/core/ValueSet/JP_AdmitSource_VS",
        "fallback_code": "other",
    },
    "discharge_disposition": {
        "system_key": "hl7-discharge-disposition",
        "jp_clins_value_set": "http://jpfhir.jp/fhir/core/ValueSet/JP_DischargeDisposition_VS",
        "fallback_code": "home",
        "deceased_code": "exp",
    },
}


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


@lru_cache(maxsize=1)
def load_med_terms_ja() -> dict[str, dict[str, str]]:
    """Load JP medication-term tables ({"categories": {...}, "terms": {...}}).

    Order is preserved from the YAML (substitutions are order-sensitive).
    Canonical loader for the FHIR adapter localization layer (was previously a
    raw ``yaml.safe_load`` inlined in ``output/_fhir_localization.py``).
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "med_terms_ja.yaml", fallback={})
    return {
        "categories": raw.get("categories", {}) or {},
        "terms": raw.get("terms", {}) or {},
    }


@lru_cache(maxsize=1)
def load_drug_names_ja() -> dict[str, str]:
    """Load English→Japanese drug name mapping (case-insensitive lowercased keys)."""
    raw = _load_yaml(_LOCALE_DIR / "shared" / "drug_names_ja.yaml", fallback={})
    return {k.lower(): v for k, v in raw.items()}


@lru_cache(maxsize=1)
def load_department_display() -> dict[str, dict[str, str]]:
    """Load department display table ({key: {en, ja}})."""
    raw = _load_yaml(_LOCALE_DIR / "shared" / "department_display.yaml", fallback={})
    return raw.get("departments", {}) or {}


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


def _load_yaml(path: Path, fallback: Any = None) -> Any:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or fallback
    return fallback if fallback is not None else {}


_FALLBACK_NAMES: dict[str, Any] = {
    "surnames": [{"name": "Test", "weight": 1}],
    "given_names_male": [{"name": "John", "weight": 1}],
    "given_names_female": [{"name": "Jane", "weight": 1}],
}

_FALLBACK_FORMATTING: dict[str, Any] = {
    "date_format": "yyyy-MM-dd",
    "time_format": "24h",
    "temperature_unit": "C",
    "weight_unit": "kg",
    "height_unit": "cm",
}

_FALLBACK_DEMOGRAPHICS: dict[str, Any] = {
    "average_household_size": 2.5,
    "age_distribution": {
        "0-14": 0.18,
        "15-24": 0.13,
        "25-34": 0.14,
        "35-44": 0.13,
        "45-54": 0.13,
        "55-64": 0.13,
        "65-74": 0.09,
        "75-84": 0.05,
        "85-99": 0.02,
    },
    "blood_type": {"O": 0.44, "A": 0.42, "B": 0.10, "AB": 0.04},
    "chronic_prevalence": {},
}
