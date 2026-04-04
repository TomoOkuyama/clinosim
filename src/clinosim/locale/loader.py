"""Locale data loader — single access point for all country/language-specific data.

Provides:
  - Person names (surnames, given names with weights)
  - Clinical terminology (display names for ICD, LOINC, RxNorm, etc.)
  - Code mappings (internal code → standard code system)
  - Formatting rules (date, time, units)
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_LOCALE_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def load_names(country: str) -> dict[str, Any]:
    """Load person name data for a country."""
    path = _LOCALE_DIR / "names" / f"{_country_filename(country)}.yaml"
    return _load_yaml(path, fallback=_FALLBACK_NAMES)


@lru_cache(maxsize=16)
def load_naming_rules(country: str) -> dict[str, Any]:
    """Load naming rules for a country (name order, components, household rules)."""
    all_rules = _load_yaml(_LOCALE_DIR / "names" / "naming_rules.yaml", fallback={})
    country_key = _country_filename(country)
    return all_rules.get(country_key, all_rules.get("us", {}))  # fallback to US


@lru_cache(maxsize=32)
def load_terminology(code_system: str, language: str) -> dict[str, str]:
    """Load display names for a code system in a language.

    Example: load_terminology("icd10", "ja") -> {"J18.9": "肺炎、詳細不明", ...}
    """
    path = _LOCALE_DIR / "terminology" / f"{code_system}_{language}.yaml"
    return _load_yaml(path, fallback={})


@lru_cache(maxsize=32)
def load_code_mapping(from_system: str, to_system: str) -> dict[str, str]:
    """Load code mapping between two systems.

    Example: load_code_mapping("internal", "jlac10") -> {"CRP": "5C070", ...}
    """
    path = _LOCALE_DIR / "code_mapping" / f"{from_system}_to_{to_system}.yaml"
    return _load_yaml(path, fallback={})


@lru_cache(maxsize=8)
def load_formatting(country: str) -> dict[str, Any]:
    """Load formatting rules for a country (date, time, units)."""
    path = _LOCALE_DIR / "formatting" / f"{_country_filename(country)}.yaml"
    return _load_yaml(path, fallback=_FALLBACK_FORMATTING)


def _country_filename(country: str) -> str:
    return {"JP": "japan", "US": "us"}.get(country, country.lower())


def _load_yaml(path: Path, fallback: Any = None) -> Any:
    if path.exists():
        with open(path) as f:
            return yaml.safe_load(f) or fallback
    return fallback if fallback is not None else {}


_FALLBACK_NAMES: dict[str, Any] = {
    "surnames": [{"kanji": "Test", "kana": "テスト", "weight": 1}],
    "given_names_male": [{"kanji": "Taro", "kana": "タロウ", "weight": 1}],
    "given_names_female": [{"kanji": "Hanako", "kana": "ハナコ", "weight": 1}],
}

_FALLBACK_FORMATTING: dict[str, Any] = {
    "date_format": "yyyy-MM-dd",
    "time_format": "24h",
    "temperature_unit": "C",
    "weight_unit": "kg",
    "height_unit": "cm",
}
