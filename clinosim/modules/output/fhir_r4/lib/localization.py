"""JP/EN localization layer for the FHIR R4 adapter (FA-1 Phase 1).

Houses lazy-loaded localization tables, drug/department/procedure display
helpers, and the shared JP display dictionaries used by
``fhir_r4_adapter.py``. The adapter re-exports every symbol defined here so
existing imports keep working.

This module must NOT import ``fhir_r4_adapter`` (no circular import).
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_department_display as _load_department_display
from clinosim.locale.loader import load_med_terms as _load_med_terms
from clinosim.locale.loader import load_med_terms_ja as _load_med_terms_ja
from clinosim.locale.loader import load_narrative_display_dict as _load_narrative_display_dict
from clinosim.locale.loader import resolve_localized_display
from clinosim.modules._shared import is_jp, is_us, resolve_lang

# expose the private-name loader aliases so mypy's strict export
# check passes at fhir_r4_adapter.py's import site.
__all__ = [
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


# Pattern caches for the localization hot paths. Keyed on `(id(dict), lang)`
# so `_load_med_terms.cache_clear()` (tests) transparently invalidates the
# derived pattern cache: the next loader call returns a fresh dict object,
# `id()` differs, and the compiled-pattern rebuild kicks in. Phase 1d-3
# widened the cache key to include ``lang`` so future non-JA locales share
# the same cache without collisions.
_DOSAGE_PATTERNS_CACHE: dict[tuple[int, str], tuple[tuple[re.Pattern[str], str], ...]] = {}
_DRUG_PATTERNS_CACHE: dict[str, object] = {"dict_id": None, "value": None}


def _dosage_term_patterns(lang: str = "ja") -> tuple[tuple[re.Pattern[str], str], ...]:
    """Pre-compile med-term (category + term) regex patterns once per process.

    Pre-#1062 the sort + ``re.compile`` ran on every
    ``_localize_dosage_terms`` call — 183 terms × 104,581 calls on a JP
    p=1000 sim = ~19M compile operations, ~45s wall. Sorting
    descending-by-length once and returning the compiled patterns as a
    tuple lets the hot-path skip both.

    Phase 1d-3 (2026-09-23): the per-language display is resolved via
    ``resolve_localized_display`` at compile time (not per-call), so
    adding a new locale extends the YAML with ``<lang>: <display>`` and
    ``_localize_dosage_terms(text, "<lang>")`` picks it up. An entry
    with no ``<lang>`` slot and no ``en`` slot is dropped from the
    pattern list (nothing to substitute for that language).
    """
    tables = _load_med_terms()
    cache_key = (id(tables), lang)
    hit = _DOSAGE_PATTERNS_CACHE.get(cache_key)
    if hit is not None:
        return hit
    patterns: list[tuple[re.Pattern[str], str]] = []
    # Category prefixes first, longest-match-wins, case-insensitive.
    for cat, entry in sorted(tables["categories"].items(), key=lambda x: -len(x[0])):
        display = resolve_localized_display(entry, lang, fallback="")
        if display and display != cat:
            patterns.append((re.compile(r"(?i)\b" + re.escape(cat) + r"\b"), display))
    # Dose/route/frequency terms: case-sensitive for all-caps abbreviations
    # (PRN, PO, IV) so the terminal-lower-case token "po" in "clopidogrel"
    # does not collide, case-insensitive otherwise.
    for term, entry in sorted(tables["terms"].items(), key=lambda x: -len(x[0])):
        display = resolve_localized_display(entry, lang, fallback="")
        if not display or display == term:
            continue
        if term.isupper():
            patterns.append((re.compile(r"\b" + re.escape(term) + r"\b"), display))
        else:
            patterns.append((re.compile(r"(?i)\b" + re.escape(term) + r"\b"), display))
    compiled = tuple(patterns)
    _DOSAGE_PATTERNS_CACHE[cache_key] = compiled
    return compiled


def _localize_dosage_terms(text: str, lang: str = "ja") -> str:
    """Translate common medical abbreviations and dosage terms to the
    target language. Word-level replacements with case-insensitive
    matching for common terms.

    Phase 1d-3 (2026-09-23): the second parameter accepts any ISO-639-1
    code. When ``lang`` has no substitution entries (e.g. ``en``, or a
    locale that has not yet been populated in ``med_terms.yaml``) the
    input is passed through unchanged — no code branch is needed. The
    default remains ``"ja"`` to keep existing single-arg callers
    byte-identical during migration.
    """
    for pattern, display in _dosage_term_patterns(lang):
        text = pattern.sub(display, text)
    return text


# Rate-adjustment suffix pattern for continuous-infusion medications.
# Disease YAMLs (e.g. pulmonary_embolism.yaml Day-2 heparin drip) may emit
# `dose: "increase_rate_by_20%"` which upstream concatenates to display_name as
# `"Unfractionated_Heparin increase_rate_by_20%"`. That protocol notation belongs
# in dosageInstruction, not in medicationCodeableConcept.text — otherwise the
# code_mapping token loop fails to hit the base drug name and the coding is
# emitted uncoded.
_RATE_ADJUSTMENT_SUFFIX_RE = re.compile(
    r"\s*[_ ](increase|decrease)[_ ]rate[_ ]by[_ ](\d+)%\s*$",
    re.IGNORECASE,
)


def _split_rate_adjustment_suffix(drug_name: str) -> tuple[str, str]:
    """Split a drug display name into (base_drug_name, rate_adjustment_note).

    Returns ("", "") for empty input; returns (drug_name, "") when no
    adjustment suffix is present.

    Examples::

        >>> _split_rate_adjustment_suffix("Unfractionated_Heparin increase_rate_by_20%")
        ('Unfractionated_Heparin', 'increase rate by 20%')
        >>> _split_rate_adjustment_suffix("Norepinephrine decrease rate by 15%")
        ('Norepinephrine', 'decrease rate by 15%')
        >>> _split_rate_adjustment_suffix("Acetaminophen 500mg PO")
        ('Acetaminophen 500mg PO', '')
    """
    if not drug_name:
        return "", ""
    m = _RATE_ADJUSTMENT_SUFFIX_RE.search(drug_name)
    if not m:
        return drug_name, ""
    base = drug_name[: m.start()].rstrip(" _")
    direction = m.group(1).lower()
    percent = m.group(2)
    return base, f"{direction} rate by {percent}%"


def _localize_rate_adjustment(note_en: str, country: str) -> str:
    """Localize an English rate-adjustment note produced by ``_split_rate_adjustment_suffix``.

    Returns the input unchanged for US or empty notes.
    """
    if not note_en or is_us(country):
        return note_en
    m = re.match(r"^(increase|decrease) rate by (\d+)%\s*$", note_en, re.IGNORECASE)
    if not m:
        return note_en
    direction_ja = "増量" if m.group(1).lower() == "increase" else "減量"
    return f"注入速度を{m.group(2)}%{direction_ja}"


def _drug_name_patterns() -> tuple[tuple[re.Pattern[str], str], ...]:
    """Pre-compile the drug-name substring regex list once per process.

    Pre-#1062 the sort + ``re.compile`` ran on every ``_localize_drug_name``
    call — 267 drugs × 78,474 calls on a JP p=1000 sim = ~21M compile
    operations, ~48s wall. Sorting descending-by-length once (longest match
    wins for substring replacement) and pre-compiling collapses the slow
    fall-through path to a plain list iteration + `pattern.subn` per entry.
    Cache-invalidation notes on ``_DOSAGE_PATTERNS_CACHE`` apply here too.
    """
    ja_dict = _load_narrative_display_dict()
    if _DRUG_PATTERNS_CACHE["dict_id"] == id(ja_dict):
        return _DRUG_PATTERNS_CACHE["value"]  # type: ignore[return-value]
    compiled = tuple(
        (re.compile(r"(?i)\b" + re.escape(k) + r"\b"), v) for k, v in sorted(ja_dict.items(), key=lambda x: -len(x[0]))
    )
    _DRUG_PATTERNS_CACHE["dict_id"] = id(ja_dict)
    _DRUG_PATTERNS_CACHE["value"] = compiled
    return compiled


def _localize_drug_name(drug_name: str, country: str) -> str:
    """Resolve drug name to Japanese when country=JP.

    Matches drug names against the dictionary, handling:
    - Exact match (case-insensitive, underscore→space normalized)
    - Category prefix: "category: Drug ..." → "<ja> ..."
    - Any drug name substring found anywhere in the text (longest match wins)
    - Dosage/route/frequency terms translated at end
    """
    if is_us(country) or not drug_name:
        return drug_name
    ja_dict = _load_narrative_display_dict()
    # Normalize underscores to spaces for matching
    normalized = drug_name.replace("_", " ")
    # Try exact match on normalized (case-insensitive)
    ja = ja_dict.get(normalized.lower())
    if ja:
        return _localize_dosage_terms(ja)
    # Try exact match on cleaned (prefix stripped) version
    cleaned = normalized
    if ":" in cleaned:
        cleaned = cleaned.split(":", 1)[1].strip()
    ja = ja_dict.get(cleaned.lower())
    if ja:
        return _localize_dosage_terms(ja)
    # Replace ALL known drug name occurrences (longest-first to avoid partial matches)
    # Use case-insensitive regex replacement
    result = normalized
    changed = False
    for pattern, ja_val in _drug_name_patterns():
        new_result, n = pattern.subn(ja_val, result)
        if n > 0:
            result = new_result
            changed = True
    # Always translate dosage terms
    return (
        _localize_dosage_terms(result).strip()
        if changed or result != drug_name
        else _localize_dosage_terms(drug_name).strip()
    )  # noqa: E501


def localize_drug_name(drug_name: str, lang: str) -> str:
    """Language-aware drug-name localizer — the public unified entry
    point that lets callers drop the ``if lang == "ja":`` guard.

    Returns ``drug_name`` unchanged when no per-locale drug-name
    lookup table exists for ``lang`` (today: any lang other than
    ``"ja"``). For ``lang == "ja"``, delegates to
    ``_localize_drug_name`` with the JP country signal.

    Adding a new target locale is a column add on each narrative display
    catalog (``names.<lang>`` on `drugs.yaml`, ``<lang>: display`` on each
    `clinosim-{imaging-exam-name,procedure-phrase,allergen-substance,
    admin-form-display}.yaml`) plus this dispatcher's branch — no code
    change at the ~15 callers spread across ``template_generator`` /
    ``replacement_strategy`` / FHIR emitters.
    """
    if not drug_name or lang != "ja":
        return drug_name
    return _localize_drug_name(drug_name, "JP")


def _dept_display(dept: str, country: str) -> str:
    """Resolve a department key to its display name for the target country.

    Falls back to a title-cased key when the department is not in the table.
    """
    lang = resolve_lang(country)
    entry = _load_department_display().get(dept, {})
    return entry.get(lang) or dept.replace("_", " ").title()


# Occupation display is now in `clinosim/locale/shared/occupation_display.yaml`
# — load via `clinosim.locale.loader.load_occupation_display()` which returns
# `{slug: {en, ja}}` (post-#1880 review, hardcoded-audit Finding 5).


def _occupation_display_ja() -> dict[str, str]:
    """Flatten the slug → ja string view of `occupation_display.yaml`."""
    from clinosim.locale.loader import load_occupation_display

    return {slug: row.get("ja", slug) for slug, row in load_occupation_display().items()}


def _occupation_display_en() -> dict[str, str]:
    """Flatten the slug → en string view of `occupation_display.yaml`."""
    from clinosim.locale.loader import load_occupation_display

    return {slug: row.get("en", slug) for slug, row in load_occupation_display().items()}


# --- Shared display dictionaries for JP localization ---
#
# The eleven HL7-adjacent JA display registries previously inlined here
# now live in `clinosim/codes/data/hl7-display-ja.yaml`. The module-level
# aliases below are computed from the yaml at import time so every
# existing consumer (`_localize_display`, downstream builder modules
# importing by name) keeps working with no call-site changes.


@cache
def _hl7_display_ja() -> dict[str, dict[str, str]]:
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "hl7-display-ja.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, dict[str, str]] = {}
    for section in (
        "class_display",
        "category_display",
        "severity_display",
        "interpretation_display",
        "relationship_display",
        "org_type_display",
        "location_type_display",
        "location_name",
        "participation_type_display",
        "act_priority_display",
        "diagnosis_role_display",
    ):
        rows = raw.get(section) or {}
        out[section] = {str(k): str(v) for k, v in rows.items() if isinstance(k, str)}
    return out


_CLASS_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["class_display"]
_CATEGORY_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["category_display"]
_SEVERITY_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["severity_display"]
_INTERPRETATION_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["interpretation_display"]
_RELATIONSHIP_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["relationship_display"]
_ORG_TYPE_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["org_type_display"]
_LOCATION_TYPE_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["location_type_display"]
_LOCATION_NAME_JA: dict[str, str] = _hl7_display_ja()["location_name"]
_PARTICIPATION_TYPE_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["participation_type_display"]
_ACT_PRIORITY_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["act_priority_display"]
_DIAGNOSIS_ROLE_DISPLAY_JA: dict[str, str] = _hl7_display_ja()["diagnosis_role_display"]


# Procedure names (from disease YAML procedure.type) — EN→JA
def _procedure_display(code: str, lang: str, fallback: str = "") -> str:
    """Look up procedure display in k-codes.yaml / cpt.yaml.

    Tries k-codes first (JP codes) then cpt (US codes). Falls back to the
    provided `fallback` string if neither has an entry.
    """
    if not code:
        return fallback
    for system_key in ("k-codes", "cpt"):
        disp = code_lookup(system_key, code, lang)
        if disp and disp != code:
            return disp
    return fallback


def _localize_display(value: str, country: str, dictionary: dict[str, str]) -> str:
    """Look up JP display for an English value when country=JP.
    Returns original value if no mapping exists."""
    if not is_jp(country) or not value:
        return value
    return dictionary.get(value, value)


def _localize_interp(coded: dict[str, str], country: str) -> dict[str, str]:
    """Localize interpretation display dict in place (returns new dict)."""
    if not is_jp(country):
        return coded
    d = dict(coded)
    d["display"] = _INTERPRETATION_DISPLAY_JA.get(d.get("code", ""), d.get("display", ""))
    return d


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
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "fhir-ja-labels.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
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


@cache
def _clinician_role_rows() -> dict[str, dict[str, object]]:
    """Load `clinosim/codes/data/clinosim-clinician-role.yaml` as a
    role_key → row dict map."""
    import yaml

    path = Path(__file__).resolve().parents[4] / "codes" / "data" / "clinosim-clinician-role.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    rows = raw.get("roles") or {}
    out: dict[str, dict[str, object]] = {}
    for role_key, row in rows.items():
        if isinstance(row, dict):
            out[str(role_key)] = row
    return out


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
