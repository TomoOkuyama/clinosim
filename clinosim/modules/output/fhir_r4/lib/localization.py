"""JP/EN localization layer for the FHIR R4 adapter (FA-1 Phase 1).

Houses lazy-loaded localization tables, drug/department/procedure display
helpers, and the shared JP display dictionaries used by
``fhir_r4_adapter.py``. The adapter re-exports every symbol defined here so
existing imports keep working.

This module must NOT import ``fhir_r4_adapter`` (no circular import).
"""

from __future__ import annotations

from clinosim.codes import lookup as code_lookup
from clinosim.countries import lang_for
from clinosim.locale.loader import load_department_display as _load_department_display
from clinosim.locale.loader import load_med_terms as _load_med_terms
from clinosim.locale.loader import load_med_terms_ja as _load_med_terms_ja
from clinosim.locale.loader import load_narrative_display_dict as _load_narrative_display_dict
from clinosim.locale.table import LocalizedTable
from clinosim.modules._shared import is_jp, is_us, resolve_lang

# expose the private-name loader aliases so mypy's strict export
# check passes at fhir_r4_adapter.py's import site.
__all__ = [
    "_DOSAGE_PATTERNS_CACHE",
    "_DRUG_PATTERNS_CACHE",
    "_drug_name_patterns",
    "_localize_dosage_terms",
    "_localize_drug_name",
    "_localize_rate_adjustment",
    "_split_rate_adjustment_suffix",
    "localize_drug_name",
    "_load_department_display",
    "_load_narrative_display_dict",
    "_load_med_terms",
    "_load_med_terms_ja",
    "code_lookup",
    "is_jp",
    "is_us",
    "resolve_lang",
]

# ``_load_med_terms_ja`` / ``_load_narrative_display_dict`` / ``_load_department_display``
# are thin re-export aliases of the canonical cached locale loaders. They are
# re-exported by ``fhir_r4_adapter.py`` (public import path) and exercised by
# tests via ``.cache_clear()`` / ``.cache_info()`` — sharing the underlying
# lru_cache object keeps those APIs working.


# The free-text translator moved to the locale layer (Issue #2367); these
# names are re-exported for the FHIR emitters and their tests.
from clinosim.locale.free_text import (  # noqa: E402
    _DOSAGE_PATTERNS_CACHE,
    _DRUG_PATTERNS_CACHE,
    _drug_name_patterns,
    _localize_dosage_terms,
    _localize_drug_name,
    _localize_rate_adjustment,
    _split_rate_adjustment_suffix,
    localize_drug_name,
)


def _dept_display(dept: str, country: str) -> str:
    """Display name of a department for the target country: the shared
    department table, then English, then the humanised key (Issue #2270)."""
    from clinosim.locale.loader import department_display

    return department_display(dept, resolve_lang(country))


# Occupation display is the `occupation` section of
# `clinosim/locale/shared/vocabulary.yaml`, shared with narrative and LLM
# prompts (Issue #2269) — load via `clinosim.locale.loader.load_occupation_display()`.


# Procedure names (from disease YAML procedure.type) — EN→JA
def _procedure_display(code: str, lang: str, fallback: str = "") -> str:
    """Look up procedure display in k-codes.yaml / cpt.yaml.

    Tries k-codes first (JP codes) then cpt (US codes). Falls back to the
    provided `fallback` string if neither has an entry.
    """
    from clinosim.codes.procedures import procedure_code_display

    return procedure_code_display([code], lang) or fallback


# FHIR text translation tables (Issue #2459): English route / frequency
# tokens and fixed labels → other languages, in
# `clinosim/locale/shared/fhir_text_translations.yaml`. Translation tables: an
# English request (or a language without an entry) gets the token as written.
# `common.py::_validate_route_maps()` checks the `route` keys at import time.
def _fhir_text_table(section: str) -> LocalizedTable:
    from clinosim.locale.loader import load_fhir_text_translations
    from clinosim.locale.table import _section

    return LocalizedTable(
        f"fhir_text_translations.{section}", _section(load_fhir_text_translations, section), "translation-table"
    )


ROUTE_TEXT = _fhir_text_table("route")
FREQUENCY_TEXT = _fhir_text_table("frequency")
FIXED_LABEL_TEXT = _fhir_text_table("fixed_label")


def localize_fixed_label(en_label: str, country: str) -> str:
    """``en_label`` in the country's language (``FIXED_LABEL_TEXT``), else as
    written. New callers add the English label to the ``fixed_label`` table."""
    return FIXED_LABEL_TEXT.get(en_label, lang_for(country), fallback=en_label)


def _clinician_role_rows() -> dict[str, dict[str, object]]:
    """Role key → row of `clinosim/codes/data/clinosim-clinician-role.yaml`
    (``clinosim.locale.loader.load_clinician_roles``, Issue #2270)."""
    from clinosim.locale.loader import load_clinician_roles

    return dict(load_clinician_roles())


def _role_prefix_map_ja() -> dict[str, dict[str, str]]:
    """Return the role → {qual_code, qual_display, prefix} map derived
    from `clinosim/codes/data/clinosim-clinician-role.yaml`. Rows without
    a `qualification:` entry (narrative-only roles like certified_nurse)
    are omitted; callers already treat a missing key as "no FHIR
    qualification materialised".
    """
    rows = _clinician_role_rows()
    out: dict[str, dict[str, str]] = {}
    for role_key, row in rows.items():
        qual = row.get("qualification") if isinstance(row, dict) else None
        if not isinstance(qual, dict):
            continue
        out[role_key] = {
            "qual_code": str(qual.get("code", "")),
            "qual_display": str(qual.get("display", "")),
            "prefix": "",
        }
    return out


# BACKWARDS-COMPAT: `_ROLE_PREFIX_MAP_JA` is retained as a thin
# module-level attribute computed from the yaml so existing imports in
# `demographics/practitioner.py` and `fhir_r4/lib/inline_bb.py` keep
# working. New code should call `_role_prefix_map_ja()` directly.
_ROLE_PREFIX_MAP_JA: dict[str, dict[str, str]] = _role_prefix_map_ja()
