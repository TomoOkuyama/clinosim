"""Language-agnostic phrase translator (Phase 1d-4, 2026-09-23).

Rails-i18n-style ``t(key, lang, **params)`` unified translator. Backs
the migration of inline ``"XX" if is_ja else "YY"`` rendering branches
(283 sites across ``clinosim/modules/document/``) into YAML phrase
catalogs, so adding a new target language (fr / zh / ko / …) is a
data change — extend each entry in ``clinosim/locale/shared/
narrative_phrases.yaml`` (and future phrase-catalog YAMLs) with
``<lang>: <template>``.

Design principles (S120 codebase-wide rule):

1. **Language-agnostic**. ``lang`` is a free-form ISO-639-1 code
   used as a direct key. No binary ``is_ja`` check anywhere in the
   resolution path.
2. **Fallback chain**. ``entry[lang]`` → ``entry["en"]`` → key-as-
   string. EN falls back only when the requested language slot is
   missing from the YAML entry.
3. **Format templates via `str.format`**. Phrase entries carry
   ``{param}`` placeholders. Callers pass ``**params`` and the
   helper interpolates. Missing keys or shape mismatches fall
   through to the raw template (never raise into the caller).
4. **Dot-notation keys**. ``t("chief_complaint.encounter_reason",
   lang, cc=cc)`` navigates a nested YAML tree — same layout
   convention as Rails i18n / react-intl / vue-i18n.

The Phase 1d-2 ``resolve_localized_display(entry, lang, fallback)``
helper is the internal dict-lookup layer; ``t()`` is the format
template layer stacked on top.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from clinosim.locale.loader import _LOCALE_DIR, _load_yaml, resolve_localized_display


@lru_cache(maxsize=1)
def _load_phrase_catalog() -> dict[str, Any]:
    """Load the canonical narrative phrase catalog (Phase 1d-4).

    Structure: nested YAML tree with leaf entries of shape
    ``{lang: template}``. Callers reach a leaf via dot-notation
    (``chief_complaint.encounter_reason``).
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_phrases.yaml", fallback={})
    return raw or {}


def _resolve_key(catalog: dict[str, Any], key: str) -> dict[str, str] | None:
    """Navigate ``catalog`` with dot-notation ``key``. Returns the leaf
    ``{lang: template}`` dict, or None when the path is not a leaf."""
    node: Any = catalog
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    # Consider a leaf as any dict whose values are strings (or dict is
    # empty). Nested dicts (still tree branches) return None.
    if not isinstance(node, dict):
        return None
    if node and all(isinstance(v, str) for v in node.values()):
        return node
    return None


def t(key: str, lang: str, /, **params: object) -> str:
    """Translate a phrase key to the target language, interpolating
    ``**params`` via ``str.format``.

    Example::

        t("chief_complaint.encounter_reason", "ja", cc="発熱")
            → "来院理由: 発熱"
        t("chief_complaint.encounter_reason", "en", cc="fever")
            → "Encounter reason: fever"
        t("chief_complaint.encounter_reason", "fr", cc="fièvre")
            # fr slot missing, falls back to en template
            → "Encounter reason: fièvre"

    Resolution:
      1. ``entry[lang]`` — the caller's requested locale.
      2. ``entry["en"]`` — universal fallback (only when ``lang``
         slot is absent from the YAML entry).
      3. ``key`` itself — the last-ditch fallback so an unresolved
         phrase surfaces something readable rather than an empty
         string.

    Interpolation errors (missing ``**params`` key, index shape
    mismatch) return the raw template — the translator MUST NOT raise
    into rendering hot paths.
    """
    catalog = _load_phrase_catalog()
    entry = _resolve_key(catalog, key)
    template = resolve_localized_display(entry, lang, fallback=key)
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


__all__ = ["t"]
