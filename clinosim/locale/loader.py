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
    dir_name = _COUNTRY_DIR_MAP.get(country, country.lower())
    return _LOCALE_DIR / dir_name


@lru_cache(maxsize=16)
def load_names(country: str) -> dict[str, Any]:
    """Load person name data for a country."""
    return _load_yaml(_country_dir(country) / "names.yaml", fallback=_FALLBACK_NAMES)


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
    return _load_yaml(_country_dir(country) / "demographics.yaml", fallback=_FALLBACK_DEMOGRAPHICS)


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
    return _load_yaml(_country_dir(country) / "addresses.yaml", fallback={})


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
    "age_distribution": {"0-14": 0.18, "15-24": 0.13, "25-34": 0.14, "35-44": 0.13,
                         "45-54": 0.13, "55-64": 0.13, "65-74": 0.09, "75-84": 0.05, "85-99": 0.02},
    "blood_type": {"O": 0.44, "A": 0.42, "B": 0.10, "AB": 0.04},
    "chronic_prevalence": {},
}
