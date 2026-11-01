"""JP/EN localization layer for the FHIR R4 adapter (FA-1 Phase 1).

Houses lazy-loaded localization tables, drug/department/procedure display
helpers, and the shared JP display dictionaries used by
``fhir_r4_adapter.py``. The adapter re-exports every symbol defined here so
existing imports keep working.

This module must NOT import ``fhir_r4_adapter`` (no circular import).
"""

from __future__ import annotations

from functools import cache

from clinosim.codes import data_table
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_department_display as _load_department_display
from clinosim.locale.loader import load_med_terms as _load_med_terms
from clinosim.locale.loader import load_med_terms_ja as _load_med_terms_ja
from clinosim.locale.loader import load_narrative_display_dict as _load_narrative_display_dict
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


# FHIR JA label registries (_ROUTE_JA / _FREQ_JA / _FIXED_LABEL_JA) now
# live in `clinosim/codes/data/fhir-ja-labels.yaml`. The module-level
# aliases below are computed from the yaml at import time so existing
# consumers (`common.py::_validate_route_maps`, `build_route_concept`,
# `localize_fixed_label`) keep working with no call-site changes.
#
# Invariants still hold:
#   - Keys for `routes:` MUST be `_ROUTE_SNOMED` canonical form
#     (`_ROUTE_ALIASES` entries would be dead code).
#   - `_validate_route_maps()` in `common.py` guards both at import time.


@cache
def _fhir_ja_labels() -> dict[str, dict[str, str]]:

    raw = data_table("fhir-ja-labels")
    out: dict[str, dict[str, str]] = {}
    for section in ("routes", "frequencies", "fixed_labels"):
        rows = raw.get(section) or {}
        out[section] = {str(k): str(v) for k, v in rows.items() if isinstance(k, str)}
    return out


_ROUTE_JA: dict[str, str] = _fhir_ja_labels()["routes"]
_FREQ_JA: dict[str, str] = _fhir_ja_labels()["frequencies"]
_FIXED_LABEL_JA: dict[str, str] = _fhir_ja_labels()["fixed_labels"]


def localize_fixed_label(en_label: str, country: str) -> str:
    """Return the JA label for JP, the EN label otherwise.

    Small, focused helper for the FHIR fixed-label dictionary above. Fails
    loudly (silently returning the EN label unchanged) is intentional for
    US / non-JP paths — the same behavior every inline conditional used.
    New callers must add the EN key to ``_FIXED_LABEL_JA`` before use to
    make the JA branch fire.
    """
    from clinosim.modules._shared import is_jp

    if is_jp(country):
        return _FIXED_LABEL_JA.get(en_label, en_label)
    return en_label


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
