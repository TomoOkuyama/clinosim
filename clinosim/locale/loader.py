"""Locale data loader — single access point for all country/language-specific data.

Directory structure (country-based):
  locale/
    japan/
      names.yaml, terminology_lab.yaml, code_mapping_lab.yaml, formatting.yaml
    us/
      names.yaml, terminology_lab.yaml, code_mapping_lab.yaml, formatting.yaml
    shared/
      naming_rules.yaml
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
