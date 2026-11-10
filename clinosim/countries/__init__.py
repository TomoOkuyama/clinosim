"""Country-code predicates (Issue #2210) and the country packages.

The lowest layer of the package: no clinosim imports, so ``clinosim.types``
can use them without depending on ``clinosim.modules``. Re-exported by
``clinosim.modules._shared`` for existing callers.

Country-only algorithms live in a subpackage named by the country code
(``clinosim.countries.jp``), registered as named implementations and
selected by the country profile (docs/design-guides/country-profile-spec.md
§4, Issue #3194). This module was a single file before; its API is
unchanged.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from clinosim.datafiles import load_data_yaml

__all__ = [
    "country_slot",
    "has_authored_narrative",
    "is_jp",
    "is_us",
    "lang_for",
    "lang_name",
    "output_language_instruction",
]


# "japan" is the legacy locale key the simulator carries as ``country_key``
# (disease YAML blocks, ``country_slot(scheme="legacy_japan")``); accepting it
# here gives one normalization for both spellings (Issue #2838).
_JP_SPELLINGS = frozenset({"jp", "japan"})


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
    return str(country).strip().lower() in _JP_SPELLINGS


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


_COUNTRY_LANGUAGE_YAML = Path(__file__).parent.parent / "locale" / "shared" / "country_language.yaml"


@lru_cache(maxsize=1)
def _country_language_yaml() -> dict:
    try:
        raw = load_data_yaml(_COUNTRY_LANGUAGE_YAML) or {}
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


def normalize_lang(lang: str | None) -> str:
    """The one normalization of a language argument (spec §5.1, Issue #2453):
    lower-cased; a country code becomes its language (``"JP"`` → ``ja``); a
    regional BCP-47 tag falls back to its primary subtag (``ja-JP`` → ``ja``);
    empty becomes ``en``. Shared by the codes and locale layers."""
    key = str(lang or "").strip().lower()
    if not key:
        return "en"
    mapped = _country_language_map().get(key)
    if mapped:
        return mapped
    return key.split("-", 1)[0]


@lru_cache(maxsize=16)
def country_code(country: str) -> str:
    """The upper-case ISO code of ``country`` (``"US"`` / ``"JP"``; the legacy
    key ``"japan"`` is ``"JP"``) from its country profile — the one
    normalisation every per-country lookup uses (Issue #3143). A country
    without a profile raises ``KeyError``; it never becomes the US."""
    from clinosim.country_profile import country_profile

    return country_profile(country).code


# Disease-YAML blocks spell Japan "japan" (Issue #2838); other countries use
# their lower-case code.
_LEGACY_SLOTS = {"jp": "japan"}


def country_slot(country: str, *, scheme: Literal["code", "legacy_japan"] = "code") -> str:
    """Section key for per-country YAML blocks (case-insensitive).

    ``scheme="code"`` gives the lower-case code (``"jp"`` / ``"us"``);
    ``scheme="legacy_japan"`` gives the disease-YAML spelling (``"japan"`` /
    ``"us"``). Unknown countries raise ``KeyError`` (:func:`country_code`).
    """
    slot = country_code(country).lower()
    return _LEGACY_SLOTS.get(slot, slot) if scheme == "legacy_japan" else slot


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


def has_authored_narrative(lang: str | None) -> bool:
    """Whether ``lang`` has authored narrative content (template trajectories,
    chief-complaint variants, CC/PE rewrite rules, lab-name post-processing)
    — ``authored_narrative_languages`` in ``country_language.yaml``. The
    narrative renderers gate those pipelines on this instead of comparing the
    language with a literal (Issue #2483)."""
    raw = _country_language_yaml()
    languages = raw.get("authored_narrative_languages") or [] if isinstance(raw, dict) else []
    return normalize_lang(lang) in {str(x).strip().lower() for x in languages}
