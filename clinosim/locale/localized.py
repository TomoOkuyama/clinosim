"""The one retrieval API for localized strings and fields (Issue #2395).

Fallback order, for every localized source (code-mapping spec §6): the
requested language, then English, then the caller's explicit ``fallback``.
Never Japanese or another language, never the key, a raw code or a slug —
a missing English entry is a data bug that a test should catch.

- ``localized(entry, lang, *, fallback)`` — a ``{lang: text}`` entry (a bare
  string is language-neutral and returned as is).
- ``localized_field(record, base, lang, *, fallback)`` — ``<base>_<lang>``
  fields on a dict or object; English is ``<base>_en`` or the bare ``<base>``.
- ``label(catalog, section, key, lang, *, fallback)`` — an entry of a
  vocabulary catalog ``{section: {key: {lang: text}}}``.

``lang`` is matched case-insensitively and may be a country code (``"JP"``),
which maps to its language through ``countries.lang_for``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from clinosim.countries import normalize_lang

__all__ = ["label", "localized", "localized_field", "normalize_lang"]


def localized(entry: Any, lang: str | None, *, fallback: str = "") -> str:
    """Text of ``entry`` in ``lang``, else English, else ``fallback``."""
    if isinstance(entry, str):
        return entry
    if not isinstance(entry, Mapping) or not entry:
        return fallback
    for key in (normalize_lang(lang), "en"):
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return fallback


def localized_field(record: Any, base: str, lang: str | None, *, fallback: str = "") -> str:
    """``record.<base>_<lang>``, else English (``<base>_en`` or bare ``<base>``),
    else ``fallback``. ``record`` may be a mapping or an object."""

    def get(name: str) -> str:
        value = record.get(name) if isinstance(record, Mapping) else getattr(record, name, None)
        return str(value) if value else ""

    code = normalize_lang(lang)
    if code != "en":
        hit = get(f"{base}_{code}")
        if hit:
            return hit
    return get(f"{base}_en") or get(base) or fallback


def label(catalog: Mapping[str, Any], section: str, key: str, lang: str | None, *, fallback: str = "") -> str:
    """Entry ``catalog[section][key]`` in ``lang`` (then English, then ``fallback``)."""
    entries = catalog.get(section) if isinstance(catalog, Mapping) else None
    entry = entries.get(key) if isinstance(entries, Mapping) else None
    return localized(entry, lang, fallback=fallback)
