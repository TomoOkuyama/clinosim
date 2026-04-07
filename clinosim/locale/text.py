"""Multi-language text resolution for YAML fields.

Supports two formats:
  1. Direct string: "Chest pain" → always returns this string
  2. Language dict:
       en: "Chest pain"
       ja: "胸痛"
     → returns the matching language, falls back to English

Usage:
    from clinosim.locale.text import resolve_text
    chief = resolve_text(yaml_data.get("chief_complaint"), language="ja")
"""

from __future__ import annotations

from typing import Any

# Language code mapping
_COUNTRY_TO_LANG = {"US": "en", "JP": "ja"}


def resolve_text(value: Any, language: str = "", country: str = "") -> str:
    """Resolve a YAML text field to the appropriate language.

    Args:
        value: Either a string or a dict with language keys (en, ja, etc.)
        language: Target language code ("en", "ja")
        country: Country code ("US", "JP") — used if language not specified

    Returns:
        The text in the requested language, or English fallback.
    """
    if value is None:
        return ""

    # Direct string → return as-is (backward compatible)
    if isinstance(value, str):
        return value

    # Dict with language keys
    if isinstance(value, dict):
        lang = language or _COUNTRY_TO_LANG.get(country, "en")
        # Try exact match
        if lang in value:
            return str(value[lang])
        # Try English fallback
        if "en" in value:
            return str(value["en"])
        # Return first available
        for v in value.values():
            if isinstance(v, str):
                return v

    return str(value)
