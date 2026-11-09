"""Template-rendering primitive helpers for narrative generation.

Second mechanical slice of the META #1633 P6 narrative-package
decomposition (first was ``_localization.py``). These helpers are the
pre-``TemplateNarrativeGenerator`` building blocks that resolve
narrative labels, roster-member display names, home-medication name
strings, locale-aware template-field picks, vital-value formatting,
placeholder substitution, and the safety-skip summary line.

They move from ``template_generator.py`` with zero behaviour change;
``template_generator`` re-exports every name via explicit
``from … import X as X`` aliases so (a) existing external callers and
the god class in that module keep their imports working, and (b) mypy
treats them as deliberately re-exported (attr-defined gate).
"""

from __future__ import annotations

import logging
import string
from datetime import datetime, timedelta
from typing import Any

from clinosim.locale.i18n import t
from clinosim.locale.localized import language_slot, localized_field
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import practitioner_name
from clinosim.modules.document.narrative._safety_skips import safety_skip_line
from clinosim.types.document import NarrativeContext

logger = logging.getLogger(__name__)


# Issue #819 follow-up: staff-id → name + role suffix resolution for
# narrative templates. Used by the small number of builders that inject
# `nurse_id` / `physician_id` verbatim into the narrative text seen by
# the LLM. Without this the LLM saw raw ids (`DR-CA-002`, `NS-OR-004`)
# and preserved them into its output — my PR #828 caught them at
# Composition FHIR-emit time but DocumentReference attachments
# (Progress Notes, Nursing Records, ED Notes) were untouched, producing
# a 68% staff-id leak in the deployed cohort.


def allergen_display(allergy: Any, lang: str) -> str:
    """Display name of an allergy's substance, or "" for an NKA marker.

    The CIF ``Allergy`` carries only ``allergen_code`` (SNOMED substance);
    every narrative section resolves it here (Issue #2272).
    """
    from clinosim.codes import lookup as code_lookup

    if bool(_o(allergy, "is_nka", False)):
        return ""
    code = _o(allergy, "allergen_code", "") or ""
    return code_lookup("snomed-ct", code, lang) if code else ""


def _resolve_staff_name(staff_id: str, roster_map: dict[str, dict]) -> str:
    """Return `<name>` from ``roster_map``, or ``""`` when the id is not
    resolvable (Issue #2270: a raw staff id is not shown in user-facing
    text; ``clinosim.modules._shared.practitioner_name``).

    Never fabricates a name for an unknown id (mirrors the same rule as
    the sibling FHIR-emit walker `_localize_practitioner_ids_in_text`
    in `composition.py`).

    The role suffix (「看護師」/「(physician)」 …) is intentionally
    omitted: every narrative callsite reaches this helper through an
    outer template that already carries the role indicator
    (``Assigned nurse: {name}``, ``担当看護師: {name}``,
    ``Primary surgeon: {surgeon}`` …). Appending the suffix again
    produced "Assigned nurse: George York (physician)" /
    "担当看護師: 田川 智美 看護師" with the role stated twice — the
    Phase 1d-71 review across all 29 narrative doc types found this
    at every staff-name emit site.

    Examples::

        _resolve_staff_name("NS-OR-004", roster)  → "小松 凜"
        _resolve_staff_name("DR-CA-002", roster)  → "加瀬 幸男"
        _resolve_staff_name("XYZ-999", {})        → ""
    """
    return practitioner_name(staff_id, roster_map)


def _render_home_med_name(m: Any, lang: str = "en") -> str:
    """Extract the display name of a home medication for narrative text.

    Handles the two shapes `current_medications` items appear as here:
    - `HomeMedication` instance (in-memory, sim-time)
    - `dict` (re-loaded from CIF JSON in the narrative pass — the pydantic
      TypeAdapter round-trip runs only in memoize; the narrative pass reads
      raw JSON via CIFReader)

    Introduced in #452 PR 1; the `str` fallback (legacy fixture support) was
    dropped in PR 3 once every writer emits `HomeMedication`.

    v9 (2026-08-17): when ``lang == "ja"``, resolve English drug names to
    canonical katakana via the shared `_localize_drug_name` helper (same
    228-entry dictionary the FHIR emit uses). v8 template pasted raw
    English tokens ("Amlodipine, Enalapril") into JA narratives.
    """
    raw = str(m.get("drug_name") or m.get("drug") or "").strip() if isinstance(m, dict) else m.drug_name
    if not raw:
        return raw
    # Issue #2271: the CIF carries the catalog's name in each language
    # (`drug_name_<lang>`); use it before re-translating the English name.
    stored = localized_field(m, "drug_name", lang).strip()
    if stored and stored != raw.strip():
        return stored
    # Lazy import to avoid the document → output → document circular at
    # module load; same pattern used in replacement_strategy.py.
    from clinosim.locale.free_text import localize_drug_name

    return localize_drug_name(raw, lang)


def _pick_localized(tmpl: Any, key_base: str, lang: str, ctx: NarrativeContext | None = None) -> str:
    """Locale-aware field access fix for multi-language templates. locale-aware field access.

    Reads the ``key_base`` language map from tmpl (attribute or dict
    access), returning an empty string + a warning log on missing. The silent ja fallback that
    previously caused US (en) narratives to contain Japanese characters is
    retired: a structurally empty section is preferable to silent locale
    contamination.

    When ``ctx`` is provided when ``ctx`` is provided, ``{placeholder}`` tokens in the
    template text are substituted via ``_fill_template_placeholders`` (the
    encounter YAML narrative templates carry them; they never reached output
    before context wired ctx.encounter_protocol).
    """
    if tmpl is None:
        return ""

    def _get(name: str) -> Any:
        return tmpl.get(name) if isinstance(tmpl, dict) else getattr(tmpl, name, None)

    # Template fields are language maps (Issues #2506, #2507). A template is
    # used in exactly the requested language; with no text in that language
    # the caller composes the section from CIF state (no English fallback for
    # authored prose).
    entry = _get(key_base)
    value = language_slot(entry, lang)
    if not value:
        logger.warning("template field %s.%s missing on %s", key_base, lang, type(tmpl).__name__)
        return ""
    text = str(value)
    if ctx is not None:
        text = _fill_template_placeholders(text, ctx, lang)
    return text


# Placeholders _fill_template_placeholders can resolve today (chain 1a
# statics + chain 1b T4 vitals). Everything else ({lab_summary_ja},
# {severity_desc_en}, {weight}, ...) makes the whole section fall back to the
# locale generic phrase.
_KNOWN_PLACEHOLDERS = frozenset({"chief_complaint_ja", "chief_complaint_en"})

# Language-suffixed placeholders resolved per language (Issue #2871):
# ``{onset_<lang>}`` (symptom onset) and ``{appearance_<lang>}`` (ED general
# appearance by triage level).
_ONSET_PREFIX = "onset_"
_APPEARANCE_PREFIX = "appearance_"


def symptom_onset(ctx: NarrativeContext) -> tuple[str, int]:
    """``(unit, n)``: how many hours / days before arrival the presenting
    problem began (Issue #2871).

    The unit and the inclusive range come from the encounter protocol's
    ``narrative.onset`` (``DEFAULT_SYMPTOM_ONSET`` when it declares none);
    ``n`` is drawn RNG-neutrally, keyed on the encounter, so every section of
    the visit's documents states the same onset.
    """
    from clinosim.determinism import sha_index
    from clinosim.modules.encounter.protocol import DEFAULT_SYMPTOM_ONSET

    narrative = _o(ctx.encounter_protocol, "narrative", None) if ctx.encounter_protocol else None
    spec = _o(narrative, "onset", None) if narrative is not None else None
    unit = str(_o(spec, "unit", "") or DEFAULT_SYMPTOM_ONSET.unit)
    low, high = _o(spec, "range", None) or DEFAULT_SYMPTOM_ONSET.range
    enc_id = str(_o(ctx.encounter, "encounter_id", "") or "") if ctx.encounter is not None else ""
    n = int(low) + sha_index(f"{enc_id}|symptom-onset", int(high) - int(low) + 1)
    return unit, n


def _onset_phrase(unit: str, n: int, lang: str) -> str:
    key = f"symptom_onset.{unit}_one" if n == 1 else f"symptom_onset.{unit}"
    return t(key, lang, n=n)


def _appearance_phrase(ctx: NarrativeContext, lang: str) -> str:
    """General appearance for the triage level the ED note shows, or ``""``
    when the level is unknown."""
    from clinosim.modules.document.narrative.renderers._ed_helpers import ed_triage_level

    return t(f"ed_appearance.level_{ed_triage_level(ctx)}", lang)


def _language_placeholders(fields: set[str], ctx: NarrativeContext) -> dict[str, str]:
    """Resolve the ``{onset_<lang>}`` / ``{appearance_<lang>}`` placeholders
    present in ``fields`` (plus ``{onset_days}`` for a day-unit onset);
    unresolvable ones are left out so the caller falls back whole-section."""
    resolved: dict[str, str] = {}
    onset: tuple[str, int] | None = None
    for name in fields:
        if name == "onset_days":
            onset = onset or symptom_onset(ctx)
            if onset[0] == "days":
                resolved[name] = str(onset[1])
        elif name.startswith(_ONSET_PREFIX):
            onset = onset or symptom_onset(ctx)
            resolved[name] = _onset_phrase(onset[0], onset[1], name.removeprefix(_ONSET_PREFIX))
        elif name.startswith(_APPEARANCE_PREFIX):
            phrase = _appearance_phrase(ctx, name.removeprefix(_APPEARANCE_PREFIX))
            if phrase:
                resolved[name] = phrase
    return {k: v for k, v in resolved.items() if v}


# Numeric vitals placeholders are resolved from ctx.vitals. numeric vitals placeholders resolved from ctx.vitals
# .. Placeholder name → structural-CIF vital_signs field.
# YAML inventory today (grep over encounter reference_data): {sbp} {dbp}
# {hr} {temp}; {spo2}/{rr} are covered ahead of authoring. A placeholder is
# "known" only when a non-null reading exists for the stub's day — otherwise
# the whole-section fallback (adv-1 I-2) is preserved.
_VITAL_PLACEHOLDER_FIELDS: dict[str, str] = {
    "sbp": "systolic_bp",
    "dbp": "diastolic_bp",
    "hr": "heart_rate",
    "temp": "temperature_celsius",
    "spo2": "spo2",
    "rr": "respiratory_rate",
}


def _format_vital_value(placeholder: str, value: Any) -> str:
    """Clinical display format: temp → 1 decimal, everything else → integer."""
    if placeholder == "temp":
        return f"{float(value):.1f}"
    return str(int(round(float(value))))


def _resolve_vital_placeholders(ctx: NarrativeContext, wanted: set[str]) -> dict[str, str]:
    """T4: resolve vitals placeholders from ctx.vitals for the stub's day.

    Readings are ranked by day distance to (admission date + ctx.day_index),
    ties broken by original list order (structural CIF vital_signs order is
    chronological + deterministic — deterministic seeding, no RNG). Per placeholder, the
    nearest reading with a non-null value wins; unresolvable placeholders are
    simply absent from the result (caller falls back whole-section).
    """
    if not wanted:
        return {}
    vitals = list(ctx.vitals or [])
    if not vitals:
        return {}

    admission_dt = None
    if ctx.encounter is not None:
        raw = _o(ctx.encounter, "admission_datetime", None)
        if isinstance(raw, datetime):
            admission_dt = raw
        elif raw:
            try:
                admission_dt = datetime.fromisoformat(str(raw))
            except ValueError:
                admission_dt = None
    target_date = admission_dt.date() + timedelta(days=ctx.day_index) if admission_dt is not None else None

    def _day_distance(vital: Any) -> int:
        if target_date is None:
            return 0
        raw_ts = _o(vital, "timestamp", None)
        ts: datetime | None
        if isinstance(raw_ts, datetime):
            ts = raw_ts
        else:
            try:
                ts = datetime.fromisoformat(str(raw_ts)) if raw_ts else None
            except ValueError:
                ts = None
        if ts is None:
            return 10_000  # unparseable timestamps rank last
        return abs((ts.date() - target_date).days)

    ranked = sorted(enumerate(vitals), key=lambda pair: (_day_distance(pair[1]), pair[0]))
    resolved: dict[str, str] = {}
    for placeholder in wanted:
        field_name = _VITAL_PLACEHOLDER_FIELDS[placeholder]
        for _, vital in ranked:
            value = _o(vital, field_name, None)
            if value is None:
                continue
            try:
                resolved[placeholder] = _format_vital_value(placeholder, value)
            except (TypeError, ValueError):
                continue  # non-numeric junk — try the next reading
            break
    return resolved


def _fill_template_placeholders(
    text: str, ctx: NarrativeContext, lang: str, extra: dict[str, str] | None = None
) -> str:
    """Substitute `{placeholder}` tokens in encounter-template text.

    Known placeholders:
      - ``{onset_<lang>}`` → the symptom onset phrase ("about 3 hours before
        arrival" / "2 days ago"); ``{onset_days}`` → the day count of a
        day-unit onset (``symptom_onset``, Issue #2871).
      - ``{appearance_<lang>}`` → general appearance by the ED triage level.
      - ``{chief_complaint_ja}`` / ``{chief_complaint_en}`` → the encounter
        protocol's own ``chief_complaint`` multi-language dict.
      - ``{sbp}`` / ``{dbp}`` / ``{hr}`` / ``{temp}`` / ``{spo2}`` / ``{rr}``
        (vital signs resolution) → nearest non-null reading in ``ctx.vitals`` for the
        stub's day (``_resolve_vital_placeholders``).
      - any name in ``extra`` (a value the calling section composed itself).

    adv-1 I-2: if the text carries ANY placeholder outside the known set —
    including a vitals placeholder with NO resolvable reading — the WHOLE
    text falls back to the locale generic phrase .. The
    earlier per-placeholder generic substitution produced broken sentences
    ("BP No special findings/No special findings mmHg").
    """
    if "{" not in text:
        return text
    generic = t("fallback.generic_fallback", lang)
    try:
        fields = {fname for _, fname, _, _ in string.Formatter().parse(text) if fname is not None}
    except ValueError:
        # Malformed braces (e.g. literal "{" in clinical text) — emit as-is
        # rather than raise; never fail narrative generation on template data.
        return text
    if not fields:
        return text
    vital_values = _resolve_vital_placeholders(ctx, fields & _VITAL_PLACEHOLDER_FIELDS.keys())
    extra_values = {k: v for k, v in (extra or {}).items() if k in fields and v}
    language_values = _language_placeholders(fields - _KNOWN_PLACEHOLDERS - extra_values.keys(), ctx)
    if not fields <= (_KNOWN_PLACEHOLDERS | vital_values.keys() | extra_values.keys() | language_values.keys()):
        return generic
    cc = _o(ctx.encounter_protocol, "chief_complaint", {}) if ctx.encounter_protocol else {}
    if not isinstance(cc, dict):
        cc = {}
    mapping = {
        "chief_complaint_ja": str(cc.get("ja") or "") or generic,
        "chief_complaint_en": str(cc.get("en") or "") or generic,
        **vital_values,
        **language_values,
        **extra_values,
    }
    try:
        return text.format_map(mapping)
    except (KeyError, ValueError, IndexError):
        # Positional "{}" fields or an unexpected format spec — emit as-is;
        # never fail narrative generation on template data.
        return text


# Generic fallback phrases per locale — Phase 1d-7: content moved to
# ``narrative_phrases.yaml`` (section ``fallback:``). The three module
# constants below are still assigned so callers referencing them by
# bare name inside per-language conditional blocks continue to work;
# the values now come from the language-agnostic phrase catalog.
_GENERIC_FALLBACK_JA = t("fallback.generic_fallback", "ja")
_GENERIC_FALLBACK_EN = t("fallback.generic_fallback", "en")
_GENERIC_ASSESSMENT_JA = t("fallback.generic_assessment", "ja")
_GENERIC_ASSESSMENT_EN = t("fallback.generic_assessment", "en")
_GENERIC_PLAN_JA = t("fallback.generic_plan", "ja")
_GENERIC_PLAN_EN = t("fallback.generic_plan", "en")

# JP/EN disposition-label map for `build_discharge_details`. Kept at
# module scope because the equivalent function-local ``UPPER_CASE`` binding
# would trigger the N806 lint rule.
# Phase 1d-32: ``_JA_DISPO_LABEL`` / ``_EN_DISPO_LABEL`` moved to
# ``clinosim/locale/shared/narrative_labels.yaml`` under
# ``discharge_disposition``. Callers resolve via ``_label``.


def _render_safety_skips_line(skips: list[dict], lang: str) -> str:
    """Render an assessment-and-plan addendum listing drug-safety events
    (avoid / hold / substitute / switch / deescalate) that fired for
    the current encounter.

    Empty skips → empty string. One line per skip. Called from the plan
    section renderers of both progress_note and outpatient SOAP so the
    physician's clinical reasoning is visible in the deterministic
    template output — not only in the LLM-driven narrative (Task 10/11).

    Issue #1066 (drug_safety) — sibling of B9 progress_note density gap.
    Issue #1403 (S114) extended `event_type` from `avoid` to five values
    (avoid / hold / substitute / switch / deescalate). Pre-#1416
    template rendered EVERY skip with `avoid` phrasing regardless of
    event_type — the hold / substitute / switch / deescalate events
    were mis-narrated as pair-conflict avoidances. This renderer now
    dispatches per event_type through ``safety_skip_line``, shared with the
    LLM prompt context (Issue #2519).
    """
    if not skips:
        return ""

    # Phase 1c-5 (2026-09-23): JA drug-name localization is a locale-
    # specific data pipeline (katakana translation via `load_narrative_display_dict`)
    # — kept behind a ``lang == "ja"`` gate. Two pre-fix failure modes:
    # (1) ``considered_ja`` / ``substituted_with_ja`` sometimes unset;
    # (2) when set, sometimes falls back to raw English (chronic_medications.
    # yaml lacks ``drug_ja`` so ``discharge_rx._register_medication`` copies
    # the EN name). Routing through ``_localize_drug_name`` normalises
    # both. Katakana input passes through the substring-matcher unchanged,
    # so already-localized values are idempotent. Lazy import + broad
    # except mirrors ``discontinue_flip._log_treatment_change`` so an
    # i18n failure never breaks the narrative render.
    def _drug(value: str | None) -> str:
        """Lang-aware drug-name katakana wrapper — no-op for lang
        without a lookup table. Broad except keeps a narrative
        render from failing on an i18n edge case (mirrors
        `discontinue_flip._log_treatment_change`)."""
        if not value:
            return ""
        try:
            from clinosim.locale.free_text import localize_drug_name

            return localize_drug_name(value, lang) or value
        except Exception:  # noqa: BLE001
            return value

    return "\n".join(safety_skip_line(s, lang, prefix="safety_skips", drug_name=_drug) for s in skips)


# English HPI onset phrases per severity — the disease YAML
# `hpi_template.onset_pattern` is Japanese-only, so the EN locale must
# synthesize its own text rather than fall back to the Japanese source
# (which would leak CJK into US Composition `.section[].text.div`).
# HPI onset templates now live in
# `clinosim/locale/shared/narrative_phrases.yaml::hpi.onset.{mild,moderate,severe}`
# (post-#1880 review, hardcoded-audit Finding 17). Resolved via
# `clinosim.locale.i18n.t("hpi.onset.<severity>", lang="en")`.


def _hpi_onset_en(severity: str) -> str:
    """Resolve an EN HPI onset template by severity via narrative_phrases.yaml.

    Falls back to the "moderate" phrasing when the severity is unknown,
    matching the pre-#1880 `_HPI_ONSET_EN.get(ctx.severity) or
    _HPI_ONSET_EN["moderate"]` idiom at the one call site in
    `template_generator._render_hpi_onset`.
    """
    from clinosim.locale.i18n import t

    phrase = t(f"hpi.onset.{severity}", "en")
    if phrase.startswith("hpi.onset."):
        # i18n miss returns the key verbatim — fall back to "moderate".
        phrase = t("hpi.onset.moderate", "en")
    return phrase


# Nursing section fallback phrases

# ADMISSION_CARE_PLAN (Phase 2) fallback phrases

# NUTRITION_CARE_PLAN (Phase 2) fallback phrases

# REHABILITATION_PLAN (Phase 2) fallback phrases live in
# `narrative_phrases.yaml` under `fallback:` (`rp_goals_fallback`,
# `rp_policy_fallback`, …) — resolved by `t()` at render time.


# Nursing shift labels, keyed by the neutral shift key stored in
# structural CIF (ClinicalDocument.shift → NarrativeContext.shift). Labels are
# resolved here at render time by language .
# CIF). Keys must cover engine.SHIFT_SCHEDULE exactly (guarded by
# tests/unit/modules/document/narrative/test_template_generator_3shift.py).

# ED section fallback phrases

# Issue #982: family-history relationship display labels. HL7 v3-RoleCode
# canonical Japanese labels ("母"/"父"/"兄弟姉妹") — mirrors the FHIR
# `_build_relationship_codeable` map in
# clinosim/modules/output/fhir_r4/demographics/family_history.py so the
# narrative and the FHIR resource render the same label per relative.


# Issue #1327: neutral-observation phrase pool for the inpatient
# progress_note subjective fallback (no abnormal vitals today). Keyed on
# stay-phase (early / mid / late / eve). Rotated deterministically by
# ``day_index`` so consecutive days differ. Every phrase describes the
# day's clinical hold without asserting an unmodeled symptom — a nurse's
# neutral-observation vocabulary, not fabrication.
# Phase 1d-17: ``_INPATIENT_SUBJECTIVE_POOL_JA / _EN`` dict tables moved
# to ``clinosim/locale/shared/inpatient_subjective_pool.yaml`` and loaded
# via ``load_inpatient_subjective_pool()``. See
# ``_pick_stable_progress_phrase`` below.

# Issue #981: ED disposition reasoning-phrase templates. Selected from the
# admission diagnosis / acuity when the raw disposition code alone would
# leave the narrative bare ("自宅退院。" without a why).

# Fallback reasoning phrases per acuity keyword when no admit diagnosis
# is available (kept short — the disposition sentence must stay compact).

# Arrival mode display

# NKDA phrases per locale

# Social history smoking labels

# Alcohol use labels
# v6 (2026-08-16): `social` is a first-class token emitted by the
# population layer alongside none/heavy; without an explicit mapping it
# was falling back to "unknown", erasing information from JP narratives.

# Occupation labels (v6, 2026-08-16). Population layer emits raw
# English tokens (retired, office, manufacturing, …); v5
# `build_social_history` pasted them verbatim into JP narratives, so
# 96-yo 女性 の 職業 が 「retired」 と英字で残っていた。These maps close
# the gap. `_OCCUPATION_*.get(k, k)` — unmapped values fall back to the
# raw token so unknown occupations still render (defensive default).

# Phase 1d-1 (2026-09-23): narrative-vocabulary tables were extracted
# from this module into ``clinosim/locale/shared/narrative_*.yaml`` so
# adding a new language is a data change, not a code change. The
# helper functions below are unchanged in API — they resolve the
# ``ja``/``en`` display via ``clinosim.locale.loader.load_narrative_*``
# and fall back to the humanised slug when a key is unmapped.
#
# History (kept for grep):
# - _COMPLICATION_JA/EN → narrative_complications.yaml (Phase 1c-2/5/6/7)
# - _LAB_NAME_JA/EN     → lab_display.yaml (Phase 1c-2/4/5/7; one table since #2267)
# - _LAB_FLAG_JA        → narrative_lab_flags.yaml     (Phase 1c-5)


# Phase 1d-2 (2026-09-23): the vocabulary-lookup pattern is
# language-agnostic — ``lang`` is the free-form ISO-639-1 style code
# passed directly to ``resolve_localized_display`` as a dict key. There
# is no ``if is_ja: … else: …`` binary here, so adding a new target
# language is purely a YAML data change (extend each entry with
# ``<lang>: <display>``) — no code edit required in this module.


# Narrative localization helpers were extracted to ``_localization.py``
# as the first slice of the META #1633 P6 narrative-package
# decomposition. The imports at the top of this module re-export
# ``_localize_*``,
# ``_PROC_TYPE_LOCALE_CACHE`` and ``_load_proc_type_locale`` so
# external callers (``discharge_rx.py``, ``replacement_strategy.py``)
# and the god class below keep their imports working unchanged.


# SOAP section labels live in `narrative_labels.yaml` under
# `soap_label:` (`subjective` / `objective` / `assessment` / `plan`)
# — resolved by `_label()` at render time.
