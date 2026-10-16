"""Narrative localization helpers (JA / EN) for template-driven narrative
generation.

Split out of ``template_generator.py`` as the first mechanical slice of
the META #1633 P6 narrative-package decomposition. These are pure
helper functions whose behaviour is unchanged by the move; the former
module-level names remain re-exported from ``template_generator`` so
external callers (``discharge_rx.py``, ``replacement_strategy.py``)
and tests see no API change.

The ``_PROC_TYPE_LOCALE_CACHE`` module-level cache + ``_load_proc_
type_locale`` eager-load helper live here with ``_localize_proc_type``
because they are a cohesive unit; the cache's lazy-import of
``_BEDSIDE_PROCEDURES`` keeps template-generator import-time cost flat.
"""

from __future__ import annotations


def _localize_complication(name: str, lang: str) -> str:
    """Return the localized display for a complication token; fall back to
    the ``name.replace("_", " ")`` humanised form when the mapping is
    missing so a novel complication still surfaces something clinically
    readable rather than a machine slug.

    Whitespace-tokens in the input (space-separated composite English
    complications authored in disease YAML, e.g.
    ``"urinary tract infection"``) collapse to underscore-slug lookup
    (``urinary_tract_infection``) so both forms resolve to the same
    entry — matches the Phase 1c-5 behaviour.
    """
    if not name:
        return ""
    key = str(name).strip().lower()
    if not key:
        return ""
    key = "_".join(key.split())
    from clinosim.locale.loader import load_narrative_complications, resolve_localized_display

    return resolve_localized_display(
        load_narrative_complications().get(key, {}),
        lang,
        fallback=key.replace("_", " "),
    )


def _format_lab_unit_for_prose(unit: str | None) -> str:
    """Return a display-friendly form of a UCUM lab unit for narrative prose.

    UCUM allows dimensionless-annotation units of the form ``{annotation}``
    (curly braces are literal) — e.g. ``{INR}`` for PT-INR ratio,
    ``{score}`` for scored assessments — and lets any real unit carry a
    trailing ``/{annotation}`` clarifier (e.g. eGFR
    ``mL/min/{1.73_m2}``). These read as raw placeholders in narrative
    prose (``PT-INR 2.6 {INR}``, ``mL/min/{1.73_m2}``).

    Rules:
    - A pure-annotation unit ``{...}`` is treated as dimensionless and
      returns ``""`` — the accompanying value is self-describing.
    - A composite unit ``<real>/{...}`` strips the annotation clause
      (returns ``<real>``); the mL/min/1.73m² special-case is handled
      at its callsite for the ² typography, so this helper leaves the
      raw underscore/digit form untouched.
    - UCUM special-unit brackets ``[X]`` (e.g. ``mm[Hg]`` for mmHg,
      ``cm[H2O]`` for cmH2O) are stripped so blood-gas / airway-
      pressure units render as clinicians write them (`PaCO2 46.4
      mmHg` rather than `PaCO2 46.4 mm[Hg]`).
    - Otherwise the unit is returned verbatim.
    """
    if not unit:
        return ""
    u = str(unit).strip()
    if not u:
        return ""
    if u.startswith("{") and u.endswith("}"):
        return ""
    # Strip a trailing "/{annotation}" clause without touching the real
    # unit prefix.
    if u.endswith("}"):
        anno_start = u.rfind("/{")
        if anno_start > 0:
            u = u[:anno_start]
    # Strip UCUM special-unit brackets — `mm[Hg]` → `mmHg`,
    # `cm[H2O]` → `cmH2O`, `[in_i]` → `in_i`. The brackets carry no
    # information beyond marking a UCUM special unit family; prose
    # renders them without.
    if "[" in u and "]" in u:
        u = u.replace("[", "").replace("]", "")
    return u


def _localize_lab_name(name: str, lang: str) -> str:
    """Return the localized display for a lab_name token; fall back to
    the token as-is when unknown (some sim disease archetypes emit
    lab_names that predate this table)."""
    if not name:
        return ""
    key = str(name).strip().lower()
    if not key:
        return ""
    from clinosim.locale.loader import load_narrative_lab_names, resolve_localized_display

    return resolve_localized_display(
        load_narrative_lab_names().get(key, {}),
        lang,
        fallback=name,
    )


def _localize_lab_flag(flag: str, lang: str) -> str:
    """Localize an abnormal-flag marker for narrative display.

    JA output: ``critical`` / ``!`` → ``重篤``; ``H`` / ``L`` (single-
    letter JP hospital convention) pass through per YAML. EN / unknown
    lang: pass through untouched (the YAML has no ``en`` entry for
    single-letter flags — the lookup returns the input flag).
    """
    if not flag:
        return ""
    from clinosim.locale.loader import load_narrative_lab_flags, resolve_localized_display

    key = str(flag).strip().lower()
    # Fallback = raw flag: unmapped markers (H / L) pass through
    # untouched — matches the JP-hospital abnormal-flag convention.
    return resolve_localized_display(
        load_narrative_lab_flags().get(key, {}),
        lang,
        fallback=str(flag),
    )


# Phase 1c-6 (2026-09-23): procedure_type → localized display for the
# procedure_note ``術式区分:`` line and any other emit site that quotes
# a bedside procedure_type slug. Sourced from
# ``clinosim.modules.procedure.engine._BEDSIDE_PROCEDURES`` — the single
# source of truth for the (CPT / K-code / EN-name / JA-name) tuple.
# Lazy-imported once at first access to keep template_generator import-
# time cost flat and to avoid circular-import risk. Pre-fix, the JP
# p=10000 audit surfaced ~500 raw slug leaks (urinary_catheter /
# central_line / arterial_line / intubation / nasogastric_tube etc.)
# in the pn_procedure_name section.
_PROC_TYPE_LOCALE_CACHE: dict[str, dict[str, str]] = {}


def _load_proc_type_locale() -> None:
    if _PROC_TYPE_LOCALE_CACHE:
        return
    try:
        from clinosim.modules.procedure.engine import _BEDSIDE_PROCEDURES

        ja: dict[str, str] = {}
        en: dict[str, str] = {}
        for entry in _BEDSIDE_PROCEDURES:
            proc_type = str(entry[0])
            name_en = str(entry[3])
            name_ja = str(entry[4])
            if proc_type and name_ja:
                ja[proc_type.lower()] = name_ja
            if proc_type and name_en:
                en[proc_type.lower()] = name_en
        _PROC_TYPE_LOCALE_CACHE["ja"] = ja
        _PROC_TYPE_LOCALE_CACHE["en"] = en
    except Exception:  # noqa: BLE001 — never break narrative on i18n load
        _PROC_TYPE_LOCALE_CACHE["ja"] = {}
        _PROC_TYPE_LOCALE_CACHE["en"] = {}


def _localize_proc_type(proc_type: str, lang: str) -> str:
    """Return the localized display for a bedside procedure_type slug.

    Fallback: ``proc_type.replace("_", " ")`` humanised form when the
    slug is missing from ``_BEDSIDE_PROCEDURES`` (e.g. a delivery /
    chemotherapy_administration category outside the bedside set).
    """
    if not proc_type:
        return ""
    _load_proc_type_locale()
    key = str(proc_type).strip().lower()
    lang_key = "ja" if str(lang).lower().startswith("ja") else "en"
    return _PROC_TYPE_LOCALE_CACHE.get(lang_key, {}).get(key) or key.replace("_", " ")


# PMH severity / persistence / grade descriptor localization —
# vocab lives in ``clinosim/locale/shared/narrative_stage_tokens.yaml``
# (Phase 1d-1 extraction). Mirrors the LLM prompt Rule 5 A table in
# ``prompts/ja/narrative_seed_bundle.yaml`` so template and LLM output
# stay coherent.


def _localize_stage(stage: str, lang: str) -> str:
    """Localize a compound severity / persistence descriptor for JA.

    Whitespace-tokenises the stage string and translates each token
    via the YAML-backed table when JA; unknown tokens (numeric grades,
    proper-noun scales, unmapped words) pass through so a
    ``"Stage 1"`` or ``"NYHA III"`` string keeps its canonical form.
    Non-JA locales get the stage unchanged.
    """
    if not stage:
        return ""
    s = str(stage).strip()
    if not s:
        return s
    from clinosim.locale.loader import load_narrative_stage_tokens, resolve_localized_display

    table = load_narrative_stage_tokens()
    out: list[str] = []
    for tok in s.split():
        # Preserve any surrounding punctuation on the token boundary.
        prefix = tok[: len(tok) - len(tok.lstrip("(,.;:"))]
        suffix = tok[len(tok.rstrip("),.;:")) :]
        base = tok[len(prefix) : len(tok) - len(suffix)] if suffix else tok[len(prefix) :]
        # Fallback = untranslated base token so numeric grades / proper
        # scales (Stage 1 / NYHA III) pass through in every language.
        display = resolve_localized_display(table.get(base.lower(), {}), lang, fallback=base)
        out.append(f"{prefix}{display}{suffix}")
    return " ".join(out)


# Imaging order display-name localization — vocab lives in
# ``clinosim/locale/shared/narrative_imaging.yaml`` (Phase 1d-1
# extraction). Keys are lower-cased, whitespace/hyphen-normalised
# forms so semantic duplicates (``Chest_Xray_PA_Lateral`` and
# ``Chest X-ray PA and Lateral``) collapse to a single entry.


def _localize_imaging(name: str, lang: str) -> str:
    """Return the localized display for an imaging order token. Keys are
    matched case-insensitively after collapsing consecutive whitespace so
    both underscore-slug forms (``Chest_Xray_PA_Lateral``) and spaced
    variants (``Chest X-ray PA and Lateral``) resolve to the same entry.
    Unknown tokens fall back to a humanised slug (underscores → spaces)
    so a novel imaging code renders naturally rather than as a machine
    slug."""
    if not name:
        return ""
    key = str(name).strip().lower()
    if not key:
        return ""
    key = " ".join(key.split())  # collapse whitespace runs
    from clinosim.locale.loader import load_narrative_imaging, resolve_localized_display

    table = load_narrative_imaging()
    entry = table.get(key)
    if entry:
        hit = resolve_localized_display(entry, lang)
        if hit:
            return hit
    # Underscore-form fallback: try the underscored variant.
    alt = key.replace(" ", "_")
    entry = table.get(alt)
    if entry:
        hit = resolve_localized_display(entry, lang)
        if hit:
            return hit
    # Humanised fallback so a slug never leaks raw in prose.
    return name.replace("_", " ")


def _localize_op_approach(approach: str, lang: str) -> str:
    """Localize a surgical-approach token / composite phrase for the
    operative_note ``approach`` field. Vocab lives in
    ``clinosim/locale/shared/narrative_op_approach.yaml`` (Phase 1d-1).
    Falls back to the raw input when unmapped (matches pre-refactor
    behaviour of ``dict.get(key, key)``)."""
    if not approach:
        return ""
    key = str(approach).strip().lower()
    from clinosim.locale.loader import load_narrative_op_approach, resolve_localized_display

    return resolve_localized_display(
        load_narrative_op_approach().get(key, {}),
        lang,
        fallback=key,
    )


def _localize_op_implant(implant: str, lang: str) -> str:
    """Localize an implant / device string for the operative_note
    equipment field. Vocab lives in ``narrative_op_implants.yaml``
    (Phase 1d-1). Falls back to the raw input when unmapped."""
    if not implant:
        return ""
    key = str(implant).strip().lower()
    from clinosim.locale.loader import load_narrative_op_implants, resolve_localized_display

    return resolve_localized_display(
        load_narrative_op_implants().get(key, {}),
        lang,
        fallback=implant,
    )
