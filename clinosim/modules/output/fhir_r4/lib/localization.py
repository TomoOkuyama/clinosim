"""JP/EN localization layer for the FHIR R4 adapter (FA-1 Phase 1).

Houses lazy-loaded localization tables, drug/department/procedure display
helpers, and the shared JP display dictionaries used by
``fhir_r4_adapter.py``. The adapter re-exports every symbol defined here so
existing imports keep working.

This module must NOT import ``fhir_r4_adapter`` (no circular import).
"""

from __future__ import annotations

import re

from clinosim.codes import lookup as code_lookup
from clinosim.countries import lang_for
from clinosim.locale.loader import load_department_display as _load_department_display
from clinosim.locale.loader import load_med_terms as _load_med_terms
from clinosim.locale.loader import load_med_terms_ja as _load_med_terms_ja
from clinosim.locale.loader import load_narrative_display_dict as _load_narrative_display_dict
from clinosim.locale.table import LocalizedTable
from clinosim.modules._shared import is_jp, is_us

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

    return department_display(dept, lang_for(country))


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


# Issue #3025: an internal slug (snake_case order / lab / exam / clinical-course
# key) inside generated text, not followed by "/" (a rate unit) or part of a
# URL / identifier.
_TEXT_SLUG = re.compile(r"(?<![\w/.:#@=-])[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+(?![\w/.-])")


def slug_display(slug: str, lang: str) -> str:
    """The display of an internal slug in ``lang`` (Issue #3025): the
    clinical-course archetype table, else the lab table, else the
    imaging-exam table, else the slug read as words (underscores as
    spaces) — never the raw key (code-mapping spec section 6)."""
    from clinosim.locale.loader import (
        imaging_exam_display,
        lab_display,
        load_narrative_archetypes,
        resolve_localized_display,
    )

    archetype = (load_narrative_archetypes() or {}).get(slug)
    if archetype:
        return resolve_localized_display(archetype, lang, fallback=slug.replace("_", " "))
    words = slug.replace("_", " ")
    lab = lab_display(slug, lang, fallback="")
    if lab:
        return lab
    exam = imaging_exam_display(slug, lang)
    return exam or words


def display_slugs_in_text(text: str, lang: str) -> str:
    """``text`` with every internal slug replaced by its display
    (:func:`slug_display`; Issue #3025). Text without a slug is unchanged."""
    if not text or "_" not in text:
        return text
    return _TEXT_SLUG.sub(lambda m: slug_display(m.group(0), lang), text)
