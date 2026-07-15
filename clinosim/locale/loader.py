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

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_LOCALE_DIR = Path(__file__).parent

# ISO 3166-1 alpha-2 lowercase
_COUNTRY_DIR_MAP = {"JP": "jp", "US": "us"}


def _country_dir(country: str) -> Path:
    # session 48 P2-14: `_template` scaffold directory MUST NOT be usable
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
    """Load chronic condition home medications and monitoring rules."""
    return _load_yaml(_LOCALE_DIR / "shared" / "chronic_medications.yaml", fallback={})


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
