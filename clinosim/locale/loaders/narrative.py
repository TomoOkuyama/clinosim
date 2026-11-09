"""Narrative-renderer loader cluster (hardcoded-review Phase B1).

Factored out of ``clinosim/locale/loader.py``: all ``load_narrative_*``
functions plus the two shared helpers
(``_load_country_language_map`` + ``resolve_localized_display``) and
the composite ``load_narrative_display_dict`` free-text EN→JA display
builder.

Each loader reads a per-domain yaml under
``clinosim/locale/shared/narrative_*.yaml`` and returns a cached
``{slug: {lang: display}}`` tree. ``resolve_localized_display`` is the
cross-cutting ``{entry, lang} → display`` resolver with the three-tier
fallback chain (lang → en → fallback).

Re-exported verbatim through ``clinosim/locale/loader.py`` so every
existing ``from clinosim.locale.loader import <loader>`` import keeps
working.
"""

from __future__ import annotations

import re
from functools import cache, lru_cache
from typing import Any

from clinosim.locale._io import _LOCALE_DIR, _load_yaml
from clinosim.locale.localized import normalize_lang


@lru_cache(maxsize=1)
def _load_country_language_map() -> dict[str, str]:
    """Country code (lower-case) → ISO-639-1 language code map.

    Backs ``clinosim.modules._shared.lang_for``. Adding a new
    locale (fr / zh / …) is a one-line YAML edit here — no code
    change needed to route the country→lang resolution.
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "country_language.yaml", fallback={})
    m = raw.get("country_language", {}) if isinstance(raw, dict) else {}
    return {str(k).lower(): str(v).lower() for k, v in (m or {}).items()}


def resolve_localized_display(entry: dict[str, str] | None, lang: str, fallback: str = "") -> str:
    """Return the display for ``lang`` from a multi-language entry.

    ``entry`` is the ``{lang_code: display}`` dict authored in the
    per-domain narrative / llm-prompt YAMLs (Phase 1d-1 / 1d-2). The
    language code is passed through case-insensitively so a caller may
    hold ``"ja"`` / ``"JA"`` / ``"jp"`` / an ISO-639-1 code for any
    future locale (``"fr"``, ``"zh"``, ``"ko"``, …).

    Fallback chain:
        1. ``entry[lang]`` — the caller's requested locale.
        2. ``entry["en"]`` — the canonical universal fallback so a
           partially-populated entry still surfaces something readable
           for a future locale before its translations land.
        3. ``fallback`` — the caller's slug / humanised-key form.

    Design goal (S120 feedback, 2026-09-23): adding a new target
    language must not require a code change — extend each YAML entry
    with ``<lang>: <display>`` and pass the new lang code at the call
    site. The pre-Phase-1d-2 binary ``is_ja = lang.startswith("ja")``
    check baked "ja" and "en" into the source and would silently
    return English for a French request.
    """
    # Value selection lives in the one retrieval API (Issue #2395).
    from clinosim.locale.localized import localized

    return localized(entry, lang, fallback=fallback)


@lru_cache(maxsize=1)
def load_narrative_complications() -> dict[str, dict[str, str]]:
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_complications.yaml", fallback={})
    return raw.get("complications", {}) or {}


@lru_cache(maxsize=1)
def load_lab_display() -> dict[str, dict[str, Any]]:
    """The lab analyte display table, keyed by lower-cased lab token
    (``locale/shared/lab_display.yaml``, Issue #2267)."""
    raw = _load_yaml(_LOCALE_DIR / "shared" / "lab_display.yaml", fallback={})
    return raw.get("lab_names", {}) or {}


def lab_display(name: str, lang: str, *, style: str = "prose", fallback: str | None = None) -> str:
    """Display of lab token ``name`` (canonical lab name, panel or alternate
    spelling) for ``lang``, then English, then ``fallback`` (default: the
    token with ``_`` read as a space, so no slug reaches output).

    ``style="prose"`` is the clinician short form (narrative, LLM,
    DiagnosticReport.conclusion); ``style="formal"`` prefers the entry's
    ``formal`` names (FHIR ``code.text`` of analytes with no standard code).
    The one lab-name resolver for every output (Issue #2267)."""
    if not name:
        return ""
    token = str(name).strip()
    entry = load_lab_display().get("_".join(token.lower().split()))
    if fallback is None:
        fallback = token.replace("_", " ")
    if not entry:
        return fallback
    names = {k: v for k, v in entry.items() if k != "formal"}
    if style == "formal":
        names.update(entry.get("formal") or {})
    return resolve_localized_display(names, lang, fallback=fallback)


@lru_cache(maxsize=1)
def load_lab_result_terms() -> dict[str, dict[str, dict[str, str]]]:
    """Qualitative lab result wording (``locale/shared/lab_result_terms.yaml``, Issue #3031)."""
    raw = _load_yaml(_LOCALE_DIR / "shared" / "lab_result_terms.yaml", fallback={})
    return {k: v for k, v in (raw or {}).items() if k != "metadata"}


_DIPSTICK_GRADE_FIRST = re.compile(r"^(trace|\d\+|positive|negative)\s+([a-z]+)$", re.IGNORECASE)
_DIPSTICK_ANALYTE_FIRST = re.compile(r"^([a-z]+)\s+(trace|\d\+|positive|negative)$", re.IGNORECASE)
_BLOOD_TYPE_RESULT = re.compile(r"^(A|B|AB|O)([+-]);\s*antibody screen negative$")
_DRUG_SCREEN_POSITIVE = re.compile(r"^positive:\s*(.+)$", re.IGNORECASE)


def lab_result_display(value: Any, lang: str) -> Any:
    """A qualitative lab result in ``lang`` (Issue #3031): "2+ leukocytes,
    trace blood" -> 白血球(2+)、尿潜血(±); "Positive: opiates" -> 陽性: アヘン類;
    "A+; antibody screen negative" -> A型 Rh(+)、不規則抗体スクリーニング陰性.
    The stored wording when the language has no entry (English), and any
    non-string value unchanged."""
    if not isinstance(value, str) or not value.strip():
        return value
    from clinosim.locale.i18n import t

    terms = load_lab_result_terms()

    def term(section: str, key: str) -> str:
        entry = (terms.get(section) or {}).get(key.strip().lower()) or {}
        return resolve_localized_display(entry, lang, fallback="") if entry.get(normalize_lang(lang)) else ""

    text = value.strip()
    whole = term("results", text)
    if whole:
        return whole
    sep = t("list_sep.serial", lang)
    blood = _BLOOD_TYPE_RESULT.match(text)
    if blood:
        typed = term("phrases", "blood_type")
        screen = term("phrases", "antibody_screen_negative")
        if typed and screen:
            return typed.format(abo=blood.group(1), rh=blood.group(2)) + sep + screen
        return value
    drugs = _DRUG_SCREEN_POSITIVE.match(text)
    if drugs:
        positive = term("results", "positive")
        names = [term("drug_classes", d) or d.strip() for d in drugs.group(1).split(",")]
        return f"{positive}: {sep.join(names)}" if positive else value
    parts: list[str] = []
    for part in text.split(","):
        part = part.strip()
        m = _DIPSTICK_GRADE_FIRST.match(part)
        grade, analyte = (m.group(1), m.group(2)) if m else (None, None)
        if m is None:
            m2 = _DIPSTICK_ANALYTE_FIRST.match(part)
            if m2:
                analyte, grade = m2.group(1), m2.group(2)
        name = term("dipstick", analyte) if analyte else ""
        if not name or grade is None:
            parts.append(term("results", part) or part)
            continue
        parts.append(f"{name}({term('grades', grade) or grade})")
    out = sep.join(parts)
    return out if out != sep.join(p.strip() for p in text.split(",")) else value


def load_condition_stage_labels() -> dict[str, dict[str, str]]:
    """Condition stage labels (``locale/shared/condition_stage_labels.yaml``, Issue #3032)."""
    raw = _load_yaml(_LOCALE_DIR / "shared" / "condition_stage_labels.yaml", fallback={})
    return raw.get("stages", {}) or {}


def condition_stage_display(stage: str, lang: str) -> str:
    """A condition's stage label in ``lang`` (Issue #3032): "Mild persistent"
    -> 軽症持続型, "AJCC III" -> III期. The stored label for a language with no
    entry (English) and for a label the table does not list."""
    if not stage:
        return stage
    entry = load_condition_stage_labels().get(str(stage).strip()) or {}
    return resolve_localized_display(entry, lang, fallback=str(stage))


@lru_cache(maxsize=1)
def load_narrative_lab_flags() -> dict[str, dict[str, str]]:
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_lab_flags.yaml", fallback={})
    return raw.get("lab_flags", {}) or {}


@lru_cache(maxsize=1)
def load_narrative_stage_tokens() -> dict[str, dict[str, str]]:
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_stage_tokens.yaml", fallback={})
    return raw.get("stage_tokens", {}) or {}


@lru_cache(maxsize=1)
def load_narrative_imaging() -> dict[str, dict[str, str]]:
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_imaging.yaml", fallback={})
    return raw.get("imaging", {}) or {}


def imaging_exam_display(exam_id: str, lang: str) -> str:
    """Display name of an imaging exam in ``lang`` from the one imaging-exam
    table (``narrative_imaging.yaml``; Issue #2268), used by FHIR and narrative.

    Keys match case-insensitively after collapsing whitespace, in both the
    spaced and the underscore form (``Chest_Xray_PA_Lateral`` and ``chest xray
    pa lateral``). A missing language falls back to English; an unknown exam
    is humanised (underscores → spaces) so a slug never reaches the output.
    """
    if not " ".join(str(exam_id or "").split()):
        return ""
    from clinosim.locale.table import ImagingExamTable

    return ImagingExamTable("narrative_imaging.imaging", load_narrative_imaging, humanize_unknown=True).get(
        str(exam_id), lang
    )


def order_test_display(test: str, lang: str) -> str:
    """Display of the test an order names (a lab, a panel, an imaging exam)
    in ``lang`` for order-reason text (Issue #3024): the lab table, else the
    imaging-exam table (which humanises an unknown slug), so a reason never
    shows the internal test key or, in Japanese, an English analyte name
    the tables translate."""
    if not str(test or "").strip():
        return ""
    return lab_display(str(test), lang, fallback="") or imaging_exam_display(str(test), lang)


@lru_cache(maxsize=1)
def load_fhir_text_translations() -> dict[str, dict[str, dict[str, str]]]:
    """Translation tables for FHIR text — ``route``, ``frequency`` and
    ``fixed_label`` sections (``locale/shared/fhir_text_translations.yaml``,
    Issue #2459)."""
    raw = _load_yaml(_LOCALE_DIR / "shared" / "fhir_text_translations.yaml", fallback={})
    return {k: v for k, v in (raw or {}).items() if k != "metadata"}


@lru_cache(maxsize=1)
def load_narrative_op_approach() -> dict[str, dict[str, str]]:
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_op_approach.yaml", fallback={})
    return raw.get("op_approach", {}) or {}


@lru_cache(maxsize=1)
def load_narrative_op_implants() -> dict[str, dict[str, str]]:
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_op_implants.yaml", fallback={})
    return raw.get("op_implants", {}) or {}


@lru_cache(maxsize=1)
def load_narrative_archetypes() -> dict[str, dict[str, str]]:
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_archetypes.yaml", fallback={})
    return raw.get("archetypes", {}) or {}


@lru_cache(maxsize=1)
def load_vocabulary() -> dict[str, dict[str, dict[str, str]]]:
    """The social-history / encounter vocabularies (occupation, smoking,
    alcohol, arrival mode): one ``{slug: {lang: display}}`` table each, in
    ``locale/shared/vocabulary.yaml`` (Issue #2269). The narrative-label and
    LLM-prompt-label bundles take these sections from here."""
    return _load_yaml(_LOCALE_DIR / "shared" / "vocabulary.yaml", fallback={}) or {}


def _bundle_table(stem: str, loader: Any, section: str) -> Any:
    """The ``LocalizedTable`` of one section of a label bundle (Issue #2471)."""
    from clinosim.locale.table import LocalizedTable, _section

    return LocalizedTable(f"{stem}.{section}", _section(loader, section))


def vocab_display(vocab: str, slug: str, lang: str, *, fallback: str = "") -> str:
    """Display of ``slug`` in vocabulary ``vocab`` for ``lang`` (then English,
    then ``fallback``); slugs match case-insensitively (Issue #2269)."""
    return _bundle_table("vocabulary", load_vocabulary, vocab).get(str(slug), lang, fallback=fallback)


def prompt_label(section: str, token: str, lang: str, *, fallback: str = "") -> str:
    """Entry ``token`` (case-insensitive) of an ``llm_prompt_labels.yaml``
    section in ``lang``, then English, then ``fallback`` (Issue #2396)."""
    return _bundle_table("llm_prompt_labels", load_llm_prompt_labels, section).get(
        str(token).strip().lower(), lang, fallback=fallback
    )


def narrative_label(section: str, key: str, lang: str, fallback: str = "") -> str:
    """Entry ``key`` of a narrative-label section in ``lang`` (then English,
    then ``fallback``, else the key). Case-preserving with a lower-cased
    fallback so HL7-style codes (``"MTH"``) and snake_case slugs both resolve.
    The one ``_label`` implementation behind the narrative and newborn
    emitters (Issue #2269)."""
    return _bundle_table("narrative_labels", load_narrative_labels, section).get(
        str(key), lang, fallback=fallback or str(key)
    )


@lru_cache(maxsize=1)
def load_narrative_labels() -> dict[str, dict[str, dict[str, str]]]:
    """Load the multi-language narrative-renderer label bundle (Phase 1d-15).

    Structure: ``{section: {slug: {lang: display}}}``. Sections cover
    the 12 module-level ``_XXX_JA`` / ``_XXX_EN`` dict constants
    previously embedded in
    ``clinosim/modules/document/narrative/template_generator.py``
    (shift_labels / family_relation /
    ed_acuity_reason / arrival_mode / smoking / alcohol / occupation
    / rp_therapy_type / rp_progress / rp_participation / rp_phase).

    Adding a new target language is a data change across each
    ``{lang: display}`` entry — the loader is language-agnostic.
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "narrative_labels.yaml", fallback={})
    return {**(raw or {}), **load_vocabulary()}


@lru_cache(maxsize=1)
def load_inpatient_subjective_pool() -> dict[str, list[dict[str, str]]]:
    """Load the inpatient progress_note fallback subjective phrase pool (Phase 1d-17).

    Structure: ``{phase: [{lang: phrase}, ...]}``. Phases are
    ``early / mid / late / eve`` (stay-phase heuristic from
    ``_pick_stable_progress_phrase``). The list index is shared
    across languages so seed-reproducibility is preserved (same
    day_index rotation position → same slot in each lang). Adding
    a new target language extends each entry with ``<lang>: <phrase>``.

    Was ``_INPATIENT_SUBJECTIVE_POOL_JA/EN`` module-level dict tables
    in ``clinosim/modules/document/narrative/template_generator.py``.
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "inpatient_subjective_pool.yaml", fallback={})
    return raw or {}


@lru_cache(maxsize=1)
def load_llm_prompt_labels() -> dict[str, dict[str, dict[str, str]]]:
    """Load the LLM-prompt-time locale label bundle (Phase 1d-2).

    Structure: ``{section: {slug: {lang: display}}}``. Sections are the
    16 CIF-enum-token categories consumed by
    ``replacement_strategy._build_extra_context`` (encounter_type,
    disposition, severity, oxygen_device, arrival_mode, risk_level,
    barthel_band, lab_name, smoking, alcohol, marital, employment,
    occupation, race, ethnicity, insurance). Adding a new target
    language is a data change across each ``{lang: display}`` entry —
    the loader is language-agnostic.
    """
    raw = _load_yaml(_LOCALE_DIR / "shared" / "llm_prompt_labels.yaml", fallback={})
    return {**(raw or {}), **load_vocabulary()}


def _add_table(out: dict[str, str], rows: Any, lang: str) -> None:
    """Add ``{EN: {lang: text}}`` translation rows to ``out`` (lower-case EN
    key; first entry wins; rows without ``lang`` are skipped)."""
    for en, entry in (rows or {}).items():
        en_lower = (en or "").strip().lower()
        value = entry.get(lang) if isinstance(entry, dict) else None
        text = value.strip() if isinstance(value, str) else ""
        if en_lower and text and en_lower not in out:
            out[en_lower] = text


@cache
def _drug_catalog_display_dict(lang: str = "ja") -> dict[str, str]:
    """EN → ``lang`` names and aliases of the drug catalog (``codes/data/drugs.yaml``)."""
    out: dict[str, str] = {}
    try:
        from clinosim.codes.drugs import all_drug_ids, resolve_drug

        drug_ids: tuple[str, ...] = all_drug_ids()
    except Exception:
        drug_ids = ()
    for drug_id in drug_ids:
        try:
            rec = resolve_drug(drug_id)
        except Exception:
            continue
        en_lower = (rec.names.get("en") or "").strip().lower()
        name = (rec.names.get(lang) or "").strip()
        if en_lower and name and en_lower not in out:
            out[en_lower] = name
        for alias in rec.aliases:
            alias_lower = (alias or "").strip().lower()
            if alias_lower and name and alias_lower not in out:
                out[alias_lower] = name
    return out


@cache
def load_drug_display_dict(lang: str = "ja") -> dict[str, str]:
    """EN → ``lang`` drug names (Issues #2408, #2458): the drug catalog's
    names and aliases (``codes/data/drugs.yaml``), then the
    administration-form display variants (``clinosim-admin-form-display.yaml``:
    Calcitonin nasal spray, ...)."""
    out = dict(_drug_catalog_display_dict(lang))
    _add_table(
        out, _load_yaml(_LOCALE_DIR / "shared" / "clinosim-admin-form-display.yaml", fallback={}).get("displays"), lang
    )
    return out


@cache
def load_procedure_display_dict(lang: str = "ja") -> dict[str, str]:
    """EN → ``lang`` procedure and examination names (Issues #2408, #2458):
    the imaging exam table (``locale/shared/narrative_imaging.yaml``, spaced
    form), then ``clinosim-procedure-phrase.yaml``."""
    out: dict[str, str] = {}
    for slug, entry in load_narrative_imaging().items():
        en_lower = " ".join(str(slug).replace("_", " ").strip().lower().split())
        value = entry.get(lang) if isinstance(entry, dict) else None
        text = value.strip() if isinstance(value, str) else ""
        if en_lower and text and en_lower not in out:
            out[en_lower] = text
    _add_table(
        out, _load_yaml(_LOCALE_DIR / "shared" / "clinosim-procedure-phrase.yaml", fallback={}).get("procedures"), lang
    )
    return out


@cache
def load_allergen_display_dict(lang: str = "ja") -> dict[str, str]:
    """EN → ``lang`` allergen and substance names (``clinosim-allergen-substance.yaml``)."""
    out: dict[str, str] = {}
    _add_table(
        out,
        _load_yaml(_LOCALE_DIR / "shared" / "clinosim-allergen-substance.yaml", fallback={}).get("substances"),
        lang,
    )
    return out


@cache
def load_narrative_display_dict(lang: str = "ja") -> dict[str, str]:
    """EN → ``lang`` dictionary of every kind of name, for genuinely
    free-text order strings only (``locale.free_text.localize_free_text``).
    A name of a known kind goes through its own table (Issue #2408).

    Precedence (first entry wins): drug catalog names and aliases, imaging
    exams, procedure phrases, allergen substances, administration-form
    displays — the order the tables were merged in before the split.
    """
    merged = dict(_drug_catalog_display_dict(lang))
    for table in (load_procedure_display_dict(lang), load_allergen_display_dict(lang), load_drug_display_dict(lang)):
        for k, v in table.items():
            merged.setdefault(k, v)
    return merged
