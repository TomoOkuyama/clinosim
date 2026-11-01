"""Free-text name translator (Issue #2367).

Translates a free-text medication / order string into the target language:
an exact lookup in the merged display dictionary (drug catalog names plus
the procedure-phrase, allergen, admin-form and imaging tables), then
replacement of every known name inside the string (longest first), then
dosage / route / frequency terms (``locale/shared/med_terms.yaml``).

It lives in the locale layer so the order, narrative and FHIR layers share
it without importing the FHIR output package. Each kind of name has its own
resolver over its own table (Issue #2408):

- ``localize_drug_name`` — drug catalog names, aliases and admin-form variants;
- ``localize_procedure_name`` — procedure phrases and imaging exams, exact
  match first; a composite procedure order string falls back to the
  free-text translator;
- ``localize_allergen_name`` — allergen and substance names;
- ``localize_free_text`` — every table, for genuinely free-text order strings.

Coded names do not come through here: a code's display is the code
system's own (``codes.display``, ``codes.snomed.snomed_display``).
"""

from __future__ import annotations

import re

from clinosim.countries import is_jp
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_allergen_display_dict as _load_allergen_display_dict
from clinosim.locale.loader import load_drug_display_dict as _load_drug_display_dict
from clinosim.locale.loader import load_med_terms as _load_med_terms
from clinosim.locale.loader import load_narrative_display_dict as _load_narrative_display_dict
from clinosim.locale.loader import load_procedure_display_dict as _load_procedure_display_dict
from clinosim.locale.loader import resolve_localized_display

__all__ = [
    "_DOSAGE_PATTERNS_CACHE",
    "_DRUG_PATTERNS_CACHE",
    "_drug_name_patterns",
    "_localize_dosage_terms",
    "_localize_drug_name",
    "_localize_rate_adjustment",
    "_split_rate_adjustment_suffix",
    "localize_allergen_name",
    "localize_drug_name",
    "localize_free_text",
    "localize_procedure_name",
]


# Pattern caches for the localization hot paths. Keyed on `(id(dict), lang)`
# so `_load_med_terms.cache_clear()` (tests) transparently invalidates the
# derived pattern cache: the next loader call returns a fresh dict object,
# `id()` differs, and the compiled-pattern rebuild kicks in. Phase 1d-3
# widened the cache key to include ``lang`` so future non-JA locales share
# the same cache without collisions.
_DOSAGE_PATTERNS_CACHE: dict[tuple[int, str], tuple[object, tuple[tuple[re.Pattern[str], str], ...]]] = {}
# Value keeps the table itself: an ``id`` is reused once its object is freed
# (a test's ``cache_clear()``), so a hit must also be the same table object.
_DRUG_PATTERNS_CACHE: dict[int, tuple[dict[str, str], tuple[tuple[re.Pattern[str], str], ...]]] = {}


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
    if hit is not None and hit[0] is tables:
        return hit[1]
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
    _DOSAGE_PATTERNS_CACHE[cache_key] = (tables, compiled)
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

    Returns the input unchanged for non-JP countries or empty notes; only
    JP output is localized (Issue #2273: "not US" is not "Japanese").
    """
    if not note_en or not is_jp(country):
        return note_en
    m = re.match(r"^(increase|decrease) rate by (\d+)%\s*$", note_en, re.IGNORECASE)
    if not m:
        return note_en
    return t(f"module_text.rate_{m.group(1).lower()}", "ja", pct=m.group(2))


def _drug_name_patterns(ja_dict: dict[str, str] | None = None) -> tuple[tuple[re.Pattern[str], str], ...]:
    """Pre-compile the name substring regex list once per table (longest
    first, so the longest match wins). Pre-#1062 the sort + ``re.compile`` ran
    on every call — ~21M compile operations on a JP p=1000 sim. Keyed on the
    table object's ``id`` so a test's ``cache_clear()`` rebuilds it."""
    table = _load_drug_display_dict() if ja_dict is None else ja_dict
    cached = _DRUG_PATTERNS_CACHE.get(id(table))
    if cached is not None and cached[0] is table:
        return cached[1]
    compiled = tuple(
        (re.compile(r"(?i)\b" + re.escape(k) + r"\b"), v) for k, v in sorted(table.items(), key=lambda x: -len(x[0]))
    )
    _DRUG_PATTERNS_CACHE[id(table)] = (table, compiled)
    return compiled


def _translate_ja(text: str, ja_dict: dict[str, str]) -> str:
    """Japanese of ``text`` over ``ja_dict``: exact match (case-insensitive,
    underscores as spaces, then without a ``category:`` prefix), else every
    known name inside the string replaced (longest first); dosage / route /
    frequency terms are translated last."""
    normalized = text.replace("_", " ")
    ja = ja_dict.get(normalized.lower())
    if ja:
        return _localize_dosage_terms(ja)
    cleaned = normalized.split(":", 1)[1].strip() if ":" in normalized else normalized
    ja = ja_dict.get(cleaned.lower())
    if ja:
        return _localize_dosage_terms(ja)
    result = normalized
    changed = False
    for pattern, ja_val in _drug_name_patterns(ja_dict):
        new_result, n = pattern.subn(ja_val, result)
        if n > 0:
            result = new_result
            changed = True
    return _localize_dosage_terms(result).strip() if changed or result != text else _localize_dosage_terms(text).strip()


def _localize_drug_name(drug_name: str, country: str) -> str:
    """Japanese of a drug name / medication order string when ``country`` is
    JP, over the drug table only (Issue #2408); unchanged otherwise."""
    if not is_jp(country) or not drug_name:
        return drug_name
    return _translate_ja(drug_name, _load_drug_display_dict())


def localize_drug_name(drug_name: str, lang: str) -> str:
    """Language-aware drug-name localizer — the public unified entry
    point that lets callers drop the ``if lang == "ja":`` guard.

    Returns ``drug_name`` unchanged when no per-locale drug-name
    lookup table exists for ``lang`` (today: any lang other than
    ``"ja"``). For ``lang == "ja"``, delegates to
    ``_localize_drug_name`` with the JP country signal.

    Adding a new target locale is a column add on each narrative display
    catalog (``names.<lang>`` on `drugs.yaml`, ``<lang>: display`` on each
    `clinosim-{procedure-phrase,allergen-substance,admin-form-display}.yaml`
    and `locale/shared/narrative_imaging.yaml`) plus this dispatcher's branch — no code
    change at the ~15 callers spread across ``template_generator`` /
    ``replacement_strategy`` / FHIR emitters.
    """
    if not drug_name or lang != "ja":
        return drug_name
    return _localize_drug_name(drug_name, "JP")


def localize_procedure_name(name: str, lang: str) -> str:
    """``name`` of a procedure or examination in ``lang``: the procedure /
    imaging table's entry, else (a composite order string such as "O2: Nasal
    cannula SpO2 >= 94%") the free-text translator. Unchanged when ``lang``
    has no tables (today: not ``ja``)."""
    if not name or lang != "ja":
        return name
    table = _load_procedure_display_dict()
    normalized = name.replace("_", " ").strip().lower()
    hit = table.get(normalized) or table.get(normalized.split(":", 1)[1].strip() if ":" in normalized else "")
    return _localize_dosage_terms(hit) if hit else localize_free_text(name, lang)


def localize_allergen_name(name: str, lang: str) -> str:
    """``name`` of an allergen or substance in ``lang`` (the allergen table),
    else ``name``. Unchanged when ``lang`` has no tables (today: not ``ja``)."""
    if not name or lang != "ja":
        return name
    return _load_allergen_display_dict().get(name.replace("_", " ").strip().lower()) or name


def localize_free_text(text: str, lang: str) -> str:
    """Translate a genuinely free-text order string into ``lang`` over every
    name table (Issue #2367). Returns ``text`` unchanged when ``lang`` has no
    tables (today: not ``ja``)."""
    if not text or lang != "ja":
        return text
    return _translate_ja(text, _load_narrative_display_dict())
