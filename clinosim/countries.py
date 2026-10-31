"""Country-code predicates (Issue #2210).

The lowest layer of the package: no clinosim imports, so ``clinosim.types``
can use them without depending on ``clinosim.modules``. Re-exported by
``clinosim.modules._shared`` for existing callers.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml

__all__ = ["country_slot", "is_jp", "is_us", "lang_for", "lang_name", "output_language_instruction"]


@lru_cache(maxsize=16)
def is_jp(country: str) -> bool:
    """True when the country code refers to Japan (case-insensitive).

    Canonical JP-gating predicate (common-logic unification, 2026-07-02).
    Replaces the divergent inline idioms (``country == "JP"`` /
    ``country.lower() == "jp"`` / ``str(country).upper() == "JP"``) so every
    module gates on the same normalization.

    Perf (2026-10-17): ``lru_cache`` because this predicate is called
    ~56M times during a p=10000 5-year FHIR export, with ≤ 2 distinct
    inputs per export in practice. Cache size 16 covers all realistic
    input shapes (``"US"`` / ``"JP"`` / lower / mixed-case variants).
    """
    return str(country).strip().lower() == "jp"


@lru_cache(maxsize=16)
def is_us(country: str) -> bool:
    """True when the country code refers to the United States (case-insensitive).

    Sibling to ``is_jp``. Locale loaders with only US/JP data files use
    ``is_us(country) or is_jp(country)`` to gate on "supported country" and
    return ``{}`` otherwise, rather than silently falling back to US data
    for an unrecognized country (locale-loader unsupported-country contract,
    2026-07-02 grand design review; ``care_level.load_rates`` is the
    original compliant precedent this generalizes).
    """
    return str(country).strip().lower() == "us"


_COUNTRY_LANGUAGE_YAML = Path(__file__).parent / "locale" / "shared" / "country_language.yaml"


@lru_cache(maxsize=1)
def _country_language_yaml() -> dict:
    try:
        raw = yaml.safe_load(_COUNTRY_LANGUAGE_YAML.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        raw = {}
    return raw if isinstance(raw, dict) else {}


@lru_cache(maxsize=1)
def _country_language_map() -> dict[str, str]:
    """Lower-case country code -> ISO-639-1 language, from ``country_language.yaml``."""
    raw = _country_language_yaml()
    mapping = raw.get("country_language") or {} if isinstance(raw, dict) else {}
    return {str(k).strip().lower(): str(v).strip().lower() for k, v in mapping.items()}


@lru_cache(maxsize=32)
def lang_for(country: str) -> str:
    """Output language for a country code (case-insensitive; Issue #2274).

    The single country -> language derivation: YAML-driven
    (``locale/shared/country_language.yaml``), English for an unmapped or
    empty country.
    """
    return _country_language_map().get(str(country or "").strip().lower(), "en")


def country_slot(country: str, *, scheme: Literal["code", "legacy_japan"] = "code") -> str:
    """Section key for per-country YAML blocks (case-insensitive, US default).

    ``scheme="code"`` gives ``"jp"`` / ``"us"``; ``scheme="legacy_japan"``
    gives the disease-YAML spelling ``"japan"`` / ``"us"``.
    """
    if is_jp(country):
        return "japan" if scheme == "legacy_japan" else "jp"
    return "us"


def lang_name(lang: str, *, in_lang: str | None = None) -> str:
    """Name of language ``lang`` written in ``in_lang`` (default: ``lang`` itself).

    From ``language_names`` in ``country_language.yaml`` (Issue #2278); an
    unregistered language is named as English.
    """
    names = _country_language_yaml().get("language_names") or {}
    target = str(lang or "").strip().lower()
    entry = names.get(target) or names.get("en") or {}
    written_in = str(in_lang or (target if target in names else "en")).strip().lower()
    return str(entry.get(written_in) or entry.get("en") or "English")


def output_language_instruction(lang: str) -> str:
    """Instruction telling an LLM to write in ``lang``, written in ``lang``;
    English for an unregistered language (Issue #2278)."""
    table = _country_language_yaml().get("output_language_instruction") or {}
    return str(table.get(str(lang or "").strip().lower()) or table.get("en") or "Write in English.")
