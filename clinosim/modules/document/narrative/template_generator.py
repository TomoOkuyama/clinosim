"""Template-based narrative generator for clinical document narratives.

Stage 1 default generator producing deterministic narrative text from CIF
+ disease YAML + reference data. No LLM dependency. Dispatches by
DocumentTypeSpec.format_type to one of 3 renderers.

Multi-day fallback chain for text resolution:
  1. disease_protocol.narrative.physical_exam_findings[archetype][day_N]
  2. reference_data findings[disease_id][archetype][day_N]
  3. same chain at prior days (N-1, N-2, ..., 0)
  4. baseline reference data [archetype][day_N] with same fallback
  5. generic phrase fallback ("特記事項なし" / "No special findings")

Never raise, never return empty narrative field.

EN locale note: when a disease YAML field has only "ja" (no "en" key), the
generator falls back to the "ja" text and notes this in facts_used as
"<path>:ja_only_fallback". For fields with both "en" and "ja" (e.g.
discharge_instructions), the target_lang key is used directly. This is
preferable to fabricating English text for JP-clinical-context disease YAMLs.

Jinja2-like substitution: all template substitution is via Python
str.format_map() with named placeholders. Templates that
require computed values (e.g. "{onset_days_ago}日前より") use a fixed
reasonable default (3 days) when onset cannot be derived from CIF without
complex date arithmetic.
"""

from __future__ import annotations

import hashlib
import logging
import string
from datetime import datetime, timedelta
from typing import Any

from clinosim.codes import get_display as code_display
from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.disease.localization import target_los_config
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE,
    NARRATIVE_BMI_OBESITY_MILD_MAX_EXCLUSIVE,
    NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE,
    NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD,
    NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD,
    NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD,
    NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD,
    NARRATIVE_HBA1C_BORDERLINE_THRESHOLD,
    NARRATIVE_HBA1C_DIABETES_THRESHOLD,
    NARRATIVE_LDL_BORDERLINE_THRESHOLD,
    NARRATIVE_LDL_ELEVATED_THRESHOLD,
    NARRATIVE_LDL_HIGH_THRESHOLD,
    NUTRITION_ENERGY_KCAL_PER_KG_MIDPOINT,
    NUTRITION_PROTEIN_G_PER_KG_MIDPOINT,
)
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.reference_data_loaders import (
    load_chief_complaint_variants,
    load_discharge_instructions,
    load_hpi_pertinent_negatives,
    load_physical_exam_findings,
)
from clinosim.types.document import DocumentType, FormatType, NarrativeContext, NarrativeOutput


def _label(section: str, key: str, lang: str, fallback: str = "") -> str:
    """Look up a narrative-label section entry in the language-agnostic
    ``load_narrative_labels`` bundle. Returns ``fallback`` when the
    slug is unknown; the fallback chain (``entry[lang]`` →
    ``entry["en"]`` → ``fallback``) is provided by
    ``resolve_localized_display`` per the S120 rule.

    Key resolution is case-preserving with a lower-cased fallback so
    both HL7-style uppercase codes (``"MTH"`` / ``"FTH"``) and
    snake_case slugs (``"day_shift"`` / ``"morning"``) resolve without
    the caller normalising."""
    from clinosim.locale.loader import load_narrative_labels, resolve_localized_display

    section_entries = load_narrative_labels().get(section, {})
    entry = section_entries.get(str(key)) or section_entries.get(str(key).lower())
    return resolve_localized_display(entry, lang, fallback=fallback or str(key))


logger = logging.getLogger(__name__)


# Issue #819 follow-up: staff-id → name + role suffix resolution for
# narrative templates. Used by the small number of builders that inject
# `nurse_id` / `physician_id` verbatim into the narrative text seen by
# the LLM. Without this the LLM saw raw ids (`DR-CA-002`, `NS-OR-004`)
# and preserved them into its output — my PR #828 caught them at
# Composition FHIR-emit time but DocumentReference attachments
# (Progress Notes, Nursing Records, ED Notes) were untouched, producing
# a 68% staff-id leak in the deployed cohort.


def _resolve_staff_name(staff_id: str, roster_map: dict[str, dict], lang: str) -> str:
    """Return `<name>` + role suffix from ``roster_map``, or the raw
    ``staff_id`` when the id is not resolvable.

    Never fabricates a name for an unknown id (mirrors the same rule as
    the sibling FHIR-emit walker `_localize_practitioner_ids_in_text`
    in `composition.py`).

    Examples::

        _resolve_staff_name("NS-OR-004", roster, "ja")  → "小松 凜 看護師"
        _resolve_staff_name("DR-CA-002", roster, "en") → "加瀬 幸男 (physician)"
        _resolve_staff_name("XYZ-999", {}, "ja")        → "XYZ-999"
    """
    if not staff_id:
        return staff_id
    staff = roster_map.get(staff_id) if roster_map else None
    if not staff:
        return staff_id
    name = staff.get("name") or ""
    if not name:
        return staff_id
    prefix = staff_id.split("-", 1)[0] if "-" in staff_id else ""
    suffix = _label("staff_role_suffix", prefix, lang, fallback="")
    if not suffix:
        return name
    return t("common.staff_name_with_role", lang, name=name, suffix=suffix)


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
    if isinstance(m, dict):
        raw = str(m.get("drug_name") or m.get("drug") or "").strip()
    else:
        raw = m.drug_name
    if not raw or lang != "ja":
        return raw
    # Lazy import to avoid the document → output → document circular at
    # module load; same pattern used in replacement_strategy.py.
    from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

    return _localize_drug_name(raw, "JP")


def _pick_localized(tmpl: Any, key_base: str, lang: str, ctx: NarrativeContext | None = None) -> str:
    """Locale-aware field access fix for multi-language templates. locale-aware field access.

    Reads `<key_base>_<lang>` from tmpl (attribute or dict access), returning
    an empty string + a warning log on missing. The silent ja fallback that
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
    field = f"{key_base}_{lang}"
    if isinstance(tmpl, dict):
        value = tmpl.get(field)
    else:
        value = getattr(tmpl, field, None)
    if value is None or value == "":
        logger.warning("template locale field %s missing on %s", field, type(tmpl).__name__)
        return ""
    text = str(value)
    if ctx is not None:
        text = _fill_template_placeholders(text, ctx, lang)
    return text


# Placeholders _fill_template_placeholders can resolve today (chain 1a
# statics + chain 1b T4 vitals). Everything else ({lab_summary_ja},
# {severity_desc_en}, {weight}, ...) makes the whole section fall back to the
# locale generic phrase.
_KNOWN_PLACEHOLDERS = frozenset({"onset_days", "chief_complaint_ja", "chief_complaint_en"})

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


def _fill_template_placeholders(text: str, ctx: NarrativeContext, lang: str) -> str:
    """Substitute `{placeholder}` tokens in encounter-template text.

    Known placeholders:
      - ``{onset_days}`` → fixed default 3 ( see module
        docstring: computed values use a fixed reasonable default until they
        can be derived from CIF).
      - ``{chief_complaint_ja}`` / ``{chief_complaint_en}`` → the encounter
        protocol's own ``chief_complaint`` multi-language dict.
      - ``{sbp}`` / ``{dbp}`` / ``{hr}`` / ``{temp}`` / ``{spo2}`` / ``{rr}``
        (vital signs resolution) → nearest non-null reading in ``ctx.vitals`` for the
        stub's day (``_resolve_vital_placeholders``).

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
    if not fields <= (_KNOWN_PLACEHOLDERS | vital_values.keys()):
        return generic
    cc = _o(ctx.encounter_protocol, "chief_complaint", {}) if ctx.encounter_protocol else {}
    if not isinstance(cc, dict):
        cc = {}
    mapping = {
        "onset_days": "3",
        "chief_complaint_ja": str(cc.get("ja") or "") or generic,
        "chief_complaint_en": str(cc.get("en") or "") or generic,
        **vital_values,
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

# JP/EN disposition-label map for `_build_discharge_details`. Kept at
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
    dispatches per event_type, mirroring the LLM Rule 2 cadence
    (`replacement_strategy._build_extra_context`).
    """
    if not skips:
        return ""
    lines: list[str] = []

    # Phase 1c-5 (2026-09-23): JA drug-name localization is a locale-
    # specific data pipeline (katakana translation via drug_names_ja.yaml)
    # — kept behind a ``lang == "ja"`` gate. Two pre-fix failure modes:
    # (1) ``considered_ja`` / ``substituted_with_ja`` sometimes unset;
    # (2) when set, sometimes falls back to raw English (chronic_medications.
    # yaml lacks ``drug_ja`` so ``discharge_rx._register_medication`` copies
    # the EN name). Routing through ``_localize_drug_name`` normalises
    # both. Katakana input passes through the substring-matcher unchanged,
    # so already-localized values are idempotent. Lazy import + broad
    # except mirrors ``discontinue_flip._log_treatment_change`` so an
    # i18n failure never breaks the narrative render.
    def _ja_drug(value: str | None) -> str:
        if not value:
            return ""
        try:
            from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

            return _localize_drug_name(value, "JP") or value
        except Exception:  # noqa: BLE001
            return value

    # Localized-field selectors: prefer ``<field>_<lang>`` (JA only
    # populates this slot; EN falls straight through to the base field).
    def _localized_field(s: dict, base: str) -> str:
        return str(s.get(f"{base}_{lang}") or s.get(base) or "")

    for s in skips:
        event = str(s.get("event_type") or "avoid").lower()
        considered = _localized_field(s, "considered")
        conflict = _localized_field(s, "avoided_due_to")
        substituted = _localized_field(s, "substituted_with")
        if lang == "ja":
            considered = _ja_drug(considered)
            substituted = _ja_drug(substituted)

        day = s.get("stopped_on_day")
        day_phrase = (
            t("safety_skips.day_phrase_specific", lang, day=int(day))
            if day
            else t("safety_skips.day_phrase_default", lang)
        )

        if event == "hold":
            key = "safety_skips.hold"
        elif event == "substitute":
            key = "safety_skips.substitute_with_sub" if substituted else "safety_skips.substitute_no_sub"
        elif event == "switch":
            key = "safety_skips.switch_with_sub" if substituted else "safety_skips.switch_no_sub"
        elif event == "deescalate":
            key = "safety_skips.deescalate_with_sub" if substituted else "safety_skips.deescalate_no_sub"
        else:  # avoid (default + explicit)
            key = "safety_skips.avoid_with_sub" if substituted else "safety_skips.avoid_no_sub"
        lines.append(
            t(key, lang, considered=considered, conflict=conflict, substituted=substituted, day_phrase=day_phrase)
        )
    return "\n".join(lines)


# English HPI onset phrases per severity — the disease YAML
# `hpi_template.onset_pattern` is Japanese-only, so the EN locale must
# synthesize its own text rather than fall back to the Japanese source
# (which would leak CJK into US Composition `.section[].text.div`).
# Per-disease English wording quality is deferred to the LLM narrative
# pass; these generic phrases are clinically neutral and locale-appropriate.
_HPI_ONSET_EN: dict[str, str] = {
    "mild": "Patient reports gradual onset of symptoms over the preceding days.",
    "moderate": "Patient reports symptoms developing over several days with progressive worsening.",
    "severe": "Patient reports rapid symptom worsening prompting today's presentation.",
}

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
# `_build_social_history` pasted them verbatim into JP narratives, so
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
# - _LAB_NAME_JA/EN     → narrative_lab_names.yaml     (Phase 1c-2/4/5/7)
# - _LAB_FLAG_JA        → narrative_lab_flags.yaml     (Phase 1c-5)


# Phase 1d-2 (2026-09-23): the vocabulary-lookup pattern is
# language-agnostic — ``lang`` is the free-form ISO-639-1 style code
# passed directly to ``resolve_localized_display`` as a dict key. There
# is no ``if is_ja: … else: …`` binary here, so adding a new target
# language is purely a YAML data change (extend each entry with
# ``<lang>: <display>``) — no code edit required in this module.


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


# SOAP section labels per locale
_SOAP_JA = ("S（主観）", "O（客観）", "A（評価）", "P（計画）")
_SOAP_EN = ("S:", "O:", "A:", "P:")


def _lookup_nursing_content(ctx: NarrativeContext, field: str, lang: str, cap: int) -> tuple[list[str], list[str]]:
    """Session 104 Tier 2: merge acute-disease + chronic-ICD10 nursing
    content items for the given field
    (``"nursing_diagnoses" / "care_plan" / "patient_education"``).

    Merge order: acute (from ``ctx.disease_protocol.disease_id``) first,
    chronic (from ``ctx.patient.chronic_conditions[].code``) second.
    Items are deduplicated by exact-string equality and capped at
    ``cap`` items total. Facts-used trace lists the two sources
    consulted so the downstream ``facts_used`` field stays honest.

    Returns ``(items, facts)``. When the YAML is unavailable or
    matches nothing, returns ``([], [])`` — callers fall back to their
    existing sentinel-fallback strings (byte-identical to the
    pre-session-104 chronic-only path for non-pilot encounters).
    """
    from clinosim.modules.document.reference_data_loaders import (
        load_nursing_content,
    )

    try:
        data = load_nursing_content()
    except (FileNotFoundError, ValueError, OSError):
        return [], []

    items: list[str] = []
    facts: list[str] = []
    seen: set[str] = set()

    # --- Acute-first: ctx.disease_protocol.disease_id anchor ----------
    disease_id = ""
    if ctx.disease_protocol is not None:
        disease_id = getattr(ctx.disease_protocol, "disease_id", "") or ""
    acute_axis = data.get("acute_disease") or {}
    if disease_id and disease_id in acute_axis:
        entry = acute_axis[disease_id]
        acute_items = (entry.get(field) or {}).get(lang) or []
        for x in acute_items:
            if not x or x in seen:
                continue
            items.append(x)
            seen.add(x)
            if len(items) >= cap:
                break
        if items:
            facts.append("ctx.disease_protocol.disease_id")

    # --- Chronic-second: ctx.patient.chronic_conditions ---------------
    chronic_axis = data.get("chronic_icd10") or {}
    conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient is not None else []
    added_chronic = False
    for c in conds[:5]:
        if len(items) >= cap:
            break
        code = _o(c, "code", "") or (c if isinstance(c, str) else "")
        prefix = str(code).split(".")[0].upper() if code else ""
        entry = chronic_axis.get(prefix)
        if not entry:
            continue
        chronic_items = (entry.get(field) or {}).get(lang) or []
        for x in chronic_items:
            if not x or x in seen:
                continue
            items.append(x)
            seen.add(x)
            added_chronic = True
            if len(items) >= cap:
                break
    if added_chronic:
        facts.append("ctx.patient.chronic_conditions")

    return items, facts


def _filter_vitals_for_day(vitals: list, day_index: int, encounter: Any) -> list:
    """Return vitals belonging to day ``day_index`` of the stay.

    v6 (2026-08-16): CIF vital_signs records store ISO ``timestamp`` but
    ``day`` is typically None. The naive day-field filter therefore let
    admission-day vitals leak into every day's context, producing "T=38.1°C
    repeated for 15 consecutive progress notes" hallucinations (POP-000075).

    v7 (session 104, Issue #1166): timestamp bucketing now uses
    **calendar day** offset rather than 24h-window offset. Pre-v7 the
    delta computation was ``(ts - adm_dt).days`` which floors sub-daily
    admission times: an admission at 2026-03-19T20:23 (evening) bucketed
    2026-03-20T23:55 vitals AND 2026-03-21T18:00 vitals into the same
    day_index=1 slot (both fall within 24-48h of admission). The
    resulting doc labeled "Hospital day 2" (= day_index=1) then showed
    vitals from two calendar days, causing the LLM to write "new fever
    spike to 38.5°C" (a day 2026-03-21 reading) inside an Objective
    section that displayed the 2026-03-20 evening T=36.8°C reading —
    a subtle Grounding drift that reads as fabrication.

    v7 changes the offset to ``(ts.date() - adm_dt.date()).days`` so
    day_index=N aligns with the Nth calendar day since admission
    (day_index=0 = admission calendar day, day_index=1 = next calendar
    day, etc.). This matches the ``hospital_day_label`` rendering
    (``"hospital day {day_index+1}"``) that the LLM sees, so a doc
    labeled "Hospital day 2" surfaces exactly the 2026-03-20 vitals
    and never the 2026-03-21 spike.

    Resolution order:
      1. If any record has an explicit ``day`` field, match on it.
      2. Otherwise derive a calendar-day offset from ``timestamp.date()``
         minus ``encounter.admission_datetime.date()``.
      3. If neither exists, fall back to the first record (initial vitals).
    """
    vitals = list(vitals or [])
    if not vitals:
        return []
    # 1. Explicit day field
    tagged = [v for v in vitals if _o(v, "day", None) == day_index]
    if tagged:
        return tagged
    any_tagged = any(_o(v, "day", None) is not None for v in vitals)
    if any_tagged:
        # Some records have day, none matched → this day has none.
        return []
    # 2. Calendar-day offset fallback
    adm_raw = _o(encounter, "admission_datetime", None) if encounter is not None else None
    adm_dt = _parse_iso_datetime(adm_raw)
    if adm_dt is None:
        # Use earliest timestamp as day-0 anchor
        candidates: list[datetime] = [
            c for c in (_parse_iso_datetime(_o(v, "timestamp", None)) for v in vitals) if c is not None
        ]
        if candidates:
            adm_dt = min(candidates)
    if adm_dt is None:
        return vitals[:1]
    adm_date = adm_dt.date()
    picks: list = []
    for v in vitals:
        ts = _parse_iso_datetime(_o(v, "timestamp", None))
        if ts is None:
            continue
        # Session-104 v7: calendar-day bucket, not 24h-window bucket.
        offset = (ts.date() - adm_date).days
        if offset == day_index:
            picks.append(v)
    if picks:
        return picks
    return vitals[:1]


# Issue #961 extension: RNG-neutral autopsy sampling (used by both the
# 死亡診断書 autopsy_status section and the 死亡退院サマリー
# autopsy_status_and_findings section so the two documents agree per
# encounter). Cutoff p=0.07 gives ~7% autopsy rate matching the low
# end of JMA / MHLW real-world autopsy statistics for JP acute care.
# SHA256 keyed on (encounter_id, patient_id, "autopsy") is deterministic
# across regens and does not consume the master RNG
# (feedback_rng_neutral_additive_field).
_DDS_AUTOPSY_PROB_CUTOFF = int((1 << 64) * 0.07)


def _autopsy_performed_sha256(ctx: NarrativeContext) -> bool:
    """Deterministic per-encounter autopsy sample. See module comment above."""
    import hashlib

    enc_id = _o(getattr(ctx, "encounter", None), "encounter_id", "") or ""
    pat_id = getattr(ctx.patient, "patient_id", "") if ctx.patient else ""
    key = f"{enc_id}|{pat_id}|autopsy".encode()
    h = int.from_bytes(hashlib.sha256(key).digest()[:8], "big")
    return h < _DDS_AUTOPSY_PROB_CUTOFF


def _age_at(ctx: NarrativeContext) -> int | None:
    """Age of ``ctx.patient`` at the ``ctx.encounter`` date.

    ``PatientProfile.age`` is a static field set at cohort-generation
    time. Encounters happen months to years later along the simulation
    window, so reading ``patient.age`` directly under-reports by 1-2 y
    (birthday not yet passed / multi-year window). Prefer this helper
    on any narrative that quotes the patient's age at a specific visit
    (Issue #1173: 95.1% of SOAP progress-note headers off-by-1-or-2).

    Returns the correctly-aged integer when both ``date_of_birth`` and
    encounter date are available; falls back to ``patient.age`` when
    either is missing.
    """
    patient = getattr(ctx, "patient", None)
    if patient is None:
        return None
    static_age = _o(patient, "age", None)
    dob_raw = _o(patient, "date_of_birth", None)
    if dob_raw is None:
        return static_age
    # #1173 verify follow-up (2nd pass): CIF can carry `date_of_birth`
    # as either a `date` object (typed CIF) or an ISO string like
    # `"1990-06-25"` (CIF reader on serialized JSON). `dob.year` on a
    # string raises AttributeError which the try/except below silently
    # swallowed, and the helper fell back to static age — so 94-96% of
    # SOAP headers still reported the stale age. Normalize string DOB
    # here so both representations reach the year arithmetic.
    from datetime import date as _date

    dob: _date | None
    if isinstance(dob_raw, str):
        try:
            dob = _date.fromisoformat(dob_raw[:10])
        except ValueError:
            return static_age
    elif hasattr(dob_raw, "year") and hasattr(dob_raw, "month") and hasattr(dob_raw, "day"):
        dob = dob_raw
    else:
        return static_age
    enc = getattr(ctx, "encounter", None)
    ref_dt = _o(enc, "admission_datetime", None) if enc is not None else None
    if ref_dt is None:
        return static_age
    try:
        if isinstance(ref_dt, str):
            ref = _date.fromisoformat(ref_dt[:10])
        elif isinstance(ref_dt, datetime):
            ref = ref_dt.date()
        else:
            ref = ref_dt
        years = ref.year - dob.year - (1 if (ref.month, ref.day) < (dob.month, dob.day) else 0)
        if years < 0:
            return static_age
        return years
    except (AttributeError, TypeError, ValueError):
        return static_age


def _parse_iso_datetime(raw: Any) -> datetime | None:
    """Best-effort parse of an ISO 8601 datetime string / datetime object."""
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    s = raw.strip()
    if not s:
        return None
    # Python's fromisoformat handles the common cases; tolerate trailing Z.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Fall back to date-only strings
        try:
            return datetime.fromisoformat(s[:10])
        except ValueError:
            return None


# ─────────────────────────────────────────────────────────────────
# Issue #979 / #980: CC × physical_examination consistency helpers
# ─────────────────────────────────────────────────────────────────
#
# Template-first fix (per user directive): the physical_examination narrative
# must be internally coherent with the chief_complaint from CIF alone, without
# an LLM refinement pass. Two problem classes were observed at seed 1000
# p=2000 (Issue #980):
#   * 39 records: CC 意識障害 + PE 意識清明
#   * 47 records: CC 呼吸困難 + PE 呼吸音清明
#
# Fix: after `_format_physical_exam` produces its per-body-system prose, run
# it through `_apply_cc_pe_consistency`, which detects altered-consciousness
# or severe-dyspnea CC and rewrites the matching PE clause with a clinically
# plausible finding drawn from a small pool by SHA256(encounter_id) — this
# keeps the transform deterministic and RNG-neutral
# (feedback_rng_neutral_additive_field).

# Consciousness keywords in the chief_complaint that should invalidate a
# subsequent 「意識清明」 in the physical exam. Matched as literal substrings
# on the JP chief_complaint text.
_CC_ALTERED_CONSCIOUSNESS_KEYWORDS: tuple[str, ...] = (
    "意識障害",
    "意識消失",
    "意識レベル低下",
    "意識もうろう",
    "昏睡",
)

# Severe-dyspnea keywords that should invalidate a subsequent 「呼吸音清明」.
_CC_SEVERE_DYSPNEA_KEYWORDS: tuple[str, ...] = (
    "呼吸困難",
    "息苦しさ",
    "息苦しい",
    "喘鳴",
)

# Right-side negation tokens: if any of these follows the keyword within the
# next few characters, treat the keyword as negated (「意識障害なし」等) and
# leave PE prose unchanged.
_CC_NEGATION_TOKENS_RIGHT: tuple[str, ...] = (
    "なし",
    "無し",
    "認めず",
    "認めない",
    "否定",
    "なく",
)
# Left-side negation prefixes are rare in JP chief_complaint text but included
# for defensiveness (「否定的な意識障害」等 is uncommon; usually stated as
# postfixed 「なし」).

# PE prose fragments to replace. We match the exact catalog text emitted by
# `_format_physical_exam` (per `clinosim/modules/document/reference_data/
# physical_exam_findings.yaml` + disease YAML). "意識清明" appears both alone
# and inside longer phrases; the replacement rewrites the whole clause up to
# the next 、/。/, .
_PE_ALTERED_CONSCIOUSNESS_POOL_JA: tuple[str, ...] = (
    "GCS E3V4M5 (12/15)、JCS I-2 相当の応答遅延あり",
    "JCS I-2、簡単な問いかけには応答するも見当識低下あり",
    "GCS E3V5M6 (14/15)、傾眠傾向",
    "JCS II-10、呼びかけで開眼、内容曖昧",
)
_PE_SEVERE_DYSPNEA_POOL_JA: tuple[str, ...] = (
    "両肺 wheeze 聴取、呼気延長あり",
    "呼吸促迫、両側 crackles 聴取",
    "呼気時 wheeze 著明、SpO2 低下",
    "頻呼吸、努力呼吸あり、両側 rhonchi 聴取",
)


def _cc_keyword_positively_present(cc_text: str, keywords: tuple[str, ...]) -> bool:
    """Return True if any keyword appears in ``cc_text`` and is NOT negated
    by a right-adjacent negation token (なし / 認めず / 否定 / etc.).

    Detection window: 6 characters after the keyword's end. This matches the
    JP chief_complaint style seen in practice — negation follows immediately
    (「意識障害なし」「呼吸困難認めず」).
    """
    if not cc_text:
        return False
    for kw in keywords:
        start = 0
        while True:
            idx = cc_text.find(kw, start)
            if idx < 0:
                break
            end = idx + len(kw)
            tail = cc_text[end : end + 6]
            if not any(neg in tail for neg in _CC_NEGATION_TOKENS_RIGHT):
                return True
            start = end
    return False


def _pick_from_pool_by_encounter(pool: tuple[str, ...], enc_id: str, salt: str) -> str:
    """Deterministic pool pick keyed on (encounter_id, salt).

    RNG-neutral (SHA256, does not consume master RNG). Same encounter always
    picks the same phrase — so byte-diff-across-regens holds.
    """
    import hashlib

    key = f"{enc_id or 'ENC-UNKNOWN'}|{salt}".encode()
    idx = hashlib.sha256(key).digest()[0] % len(pool)
    return pool[idx]


def _rewrite_pe_clause(text: str, trigger_substrings: tuple[str, ...], replacement: str) -> str:
    """Rewrite each clause in ``text`` that contains any trigger substring.

    ``text`` is the joined per-body-system prose from `_format_physical_exam`
    — clauses are separated by 「。」 for JA (see `_format_physical_exam`
    return). Body-system labels ("一般状態:", "呼吸器:", …) sit at the head
    of each clause; we preserve the label and replace only the value portion
    after the first "：" or ": ".

    Returns ``text`` unchanged if no trigger fires.
    """
    if not text:
        return text
    clauses = text.split("。")
    changed = False
    for i, clause in enumerate(clauses):
        if not any(t in clause for t in trigger_substrings):
            continue
        # Split "label: value" on the first ": " (or "：") and keep the label.
        # `_format_physical_exam` uses ASCII ": " (see lines 5181-5183).
        if ": " in clause:
            label, _sep, _ = clause.partition(": ")
            clauses[i] = f"{label}: {replacement}"
            changed = True
        else:
            # No label prefix — replace the whole clause.
            clauses[i] = replacement
            changed = True
    if not changed:
        return text
    return "。".join(clauses)


class TemplateNarrativeGenerator:
    """Stage 1 default narrative generator.

    Produces deterministic narrative text from CIF + disease YAML + reference
    data. No LLM calls. Dispatches by DocumentTypeSpec.format_type.

    See module docstring for fallback chain and locale policy details.
    """

    def generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Dispatch by spec.format_type and return NarrativeOutput."""
        if spec.format_type == FormatType.FREE_TEXT:
            return self._render_free_text(ctx, spec)
        elif spec.format_type == FormatType.COMPOSITION:
            return self._render_composition_sections(ctx, spec)
        elif spec.format_type == FormatType.QUESTIONNAIRE_RESPONSE:
            return self._render_structured_form(ctx, spec)
        else:
            raise ValueError(f"Unsupported format_type: {spec.format_type}")

    # ─────────────────────────────────────────────────────────────────
    # Renderer: FREE_TEXT (PROGRESS_NOTE)
    # ─────────────────────────────────────────────────────────────────

    def _render_free_text(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build free-text narrative, dispatching on ctx.document_type.

        New types dispatch to specialized renderers; everything else
        falls through to the existing PROGRESS_NOTE SOAP renderer.
        """
        if ctx.document_type == DocumentType.NURSING_SHIFT_NOTE:
            return self._render_nursing_shift_note_text(ctx, spec)
        if ctx.document_type == DocumentType.ED_TRIAGE_NOTE:
            return self._render_ed_triage_note_text(ctx, spec)
        return self._render_progress_note_text(ctx, spec)

    def _render_progress_note_text(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build a SOAP-style progress note as plain text (PROGRESS_NOTE)."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        soap_labels = _SOAP_JA if is_ja else _SOAP_EN

        # daily_trajectory / physical_exam_findings values (disease YAML +
        # reference_data) are JP-only strings. The EN locale must not read
        # the JP source directly — instead synthesize English SOAP text
        # from CIF facts (chronic conditions, abnormal labs, active meds,
        # complications). Issue #1074 B9 (session 99): EN branch now uses
        # ``_compose_progress_assessment_from_state`` /
        # ``_compose_progress_plan_from_state`` state-composers which
        # produce patient-specific per-day text instead of the generic
        # fallback (baseline: 19.4 % ``Clinical assessment ongoing`` +
        # 7.8 % ``Continue current management`` across 1,409 progress
        # notes at US p=2000 seed=500).
        if not is_ja:
            facts.append("composed:progress_note_soap_en")
            # Issue #1155 (session-103): subjective + objective previously
            # short-circuited to "No special findings" on every EN
            # inpatient progress note. Now use the CIF-derived composers
            # (subjective covers hospital day / fever / desat; objective
            # uses today's vitals line already known to be locale-neutral).
            composed_subj = self._compose_progress_subjective_from_state(ctx)
            _obj_vitals = self._compose_pe_vitals_line(ctx)
            subjective = composed_subj or _GENERIC_FALLBACK_EN
            objective = _obj_vitals if _obj_vitals else _GENERIC_FALLBACK_EN
            if composed_subj:
                facts.append("ctx.progress_subjective.state_composed.en")
            if _obj_vitals:
                facts.append(f"ctx.vitals[day_{ctx.day_index}].en")
            # Assessment + plan now use the state-composers so each day of
            # each encounter carries patient-specific reasoning.
            composed_assess = self._compose_progress_assessment_from_state(ctx)
            composed_plan = self._compose_progress_plan_from_state(ctx)
            assessment = composed_assess or _GENERIC_ASSESSMENT_EN
            plan = composed_plan or _GENERIC_PLAN_EN
            if composed_assess:
                facts.append("ctx.progress_assessment.state_composed.en")
            if composed_plan:
                facts.append("ctx.progress_plan.state_composed.en")
        else:
            # Resolve daily trajectory for this day (with fallback chain)
            traj, traj_source = self._resolve_daily_trajectory_with_source(
                ctx, ctx.clinical_course_archetype, ctx.day_index
            )
            if traj_source:
                facts.append(traj_source)

            _generic_s = _GENERIC_FALLBACK_JA
            _generic_a = _GENERIC_ASSESSMENT_JA
            _generic_p = _GENERIC_PLAN_JA
            # v9 (2026-08-17) density fix: _resolve_daily_trajectory_with_source
            # returns a placeholder dict (「特記事項なし」/「経過観察中」/「治療
            # 継続」) when the disease YAML has no daily_trajectory. Treat those
            # placeholders as if the value were absent so the state-composers
            # can inject CIF-derived content instead of a 6-char fallback
            # winning silently.
            _placeholders = {_generic_s, _generic_a, _generic_p, ""}

            def _prefer(traj_value: str | None, composed: str, generic: str) -> str:
                if traj_value and traj_value not in _placeholders:
                    return traj_value
                return composed or generic

            subjective = _prefer(traj.get("subjective"), self._compose_progress_subjective_from_state(ctx), _generic_s)
            _obj_raw = traj.get("objective")
            objective = _obj_raw if (_obj_raw and _obj_raw not in _placeholders) else _generic_s
            assessment = _prefer(traj.get("assessment"), self._compose_progress_assessment_from_state(ctx), _generic_a)
            plan = _prefer(traj.get("plan"), self._compose_progress_plan_from_state(ctx), _generic_p)

            # v6 blocker fix (2026-08-16): prepend today's numeric vitals
            # snapshot to `objective` for inpatient progress_note. `objective`
            # is by-design non-LLM (see progress_note spec), so the template
            # itself must carry per-day BP/HR/RR/SpO2/T; otherwise it collapses
            # to a static disease_YAML string across all days of a stay.
            today_vitals_line = self._compose_today_vitals_line(ctx)
            if today_vitals_line:
                facts.append("ctx.vitals.today")
                objective = f"{today_vitals_line}。{objective}"

            # Add physical exam findings to the objective section (JP only,
            # EN skips to prevent CJK leak — sibling of _build_physical_examination fix)
            phys_exam = self._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
            if phys_exam:
                facts.append(f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}")
            phys_summary = self._format_physical_exam(phys_exam, ctx.severity, lang)
            if phys_summary:
                objective = f"{objective}。{phys_summary}"

        # Issue #1066 (drug_safety): append avoidance-and-substitution
        # reasoning to plan when this encounter carries safety_skip_log
        # entries. Same content flows into the LLM prompt via Task 10/11.
        skips_addendum = _render_safety_skips_line(getattr(ctx, "safety_skips", None) or [], lang)
        if skips_addendum:
            plan = f"{plan}\n{skips_addendum}" if plan else skips_addendum
            facts.append("ctx.safety_skips")

        # Build SOAP note. Also populate `sections` so the section-level LLM
        # replacement pipeline can operate on progress_note (session 88j
        # Tier 1 uplift). `raw_text_rejoin` metadata carries the label /
        # section pairs so `_apply_template_seed_strategy` can rebuild
        # `raw_text` from the possibly-replaced sections for FREE_TEXT
        # documents (DocumentReference emit reads `raw_text`, not sections).
        sep = "\n"
        section_order = [
            (soap_labels[0], "subjective", subjective),
            (soap_labels[1], "objective", objective),
            (soap_labels[2], "assessment", assessment),
            (soap_labels[3], "plan", plan),
        ]
        sections = {key: body for _, key, body in section_order}
        raw_text = sep.join(f"{label} {body}" for label, _, body in section_order)

        # Always add at least ctx reference
        facts.append("ctx.day_index")
        facts.append("ctx.clinical_course_archetype")

        return NarrativeOutput(
            raw_text=raw_text,
            sections=sections,
            metadata={
                "generator": "template",
                "lang": lang,
                "day_index": ctx.day_index,
                "raw_text_rejoin": {
                    "separator": sep,
                    # ordered list of (label, section_key) so the post-LLM
                    # rejoin preserves S / O / A / P sequence + labels.
                    "order": [(label, key) for label, key, _ in section_order],
                },
            },
            facts_used=facts,
        )

    # ─────────────────────────────────────────────────────────────────
    # Renderer: COMPOSITION (ADMISSION_HP, DISCHARGE_SUMMARY)
    # ─────────────────────────────────────────────────────────────────

    def _render_composition_sections(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build section dict per spec.composition_sections."""
        facts: list[str] = []
        sections: dict[str, str] = {}

        section_builders = {
            # Stage 1 sections
            "chief_complaint": self._build_chief_complaint,
            "hpi": self._build_hpi,
            "past_medical_history": self._build_past_medical_history,
            "medications_at_home": self._build_medications_at_home,
            "allergies": self._build_allergies,
            "social_history": self._build_social_history,
            "family_history": self._build_family_history,
            "physical_examination": self._build_physical_examination,
            "assessment_and_plan": self._build_assessment_and_plan,
            "admission_summary": self._build_admission_summary,
            "hospital_course": self._build_hospital_course,
            "discharge_diagnoses": self._build_discharge_diagnoses,
            "discharge_medications": self._build_discharge_medications,
            "discharge_instructions": self._build_discharge_instructions,
            "follow_up": self._build_follow_up,
            # ADMISSION_NURSING_ASSESSMENT sections
            "nursing_history": self._build_nursing_history,
            "adl_assessment": self._build_adl_assessment,
            "risk_assessments": self._build_risk_assessments,
            "nursing_diagnosis": self._build_nursing_diagnosis,
            "care_plan": self._build_care_plan,
            # NURSING_DISCHARGE_SUMMARY sections
            "admission_status": self._build_nursing_admission_status,
            "nursing_interventions_provided": self._build_nursing_interventions_provided,
            "patient_education": self._build_patient_education,
            "discharge_readiness": self._build_discharge_readiness,
            # OUTPATIENT_SOAP sections (reads encounter_protocol.narrative)
            "subjective": self._build_outpatient_subjective,
            "objective": self._build_outpatient_objective,
            "assessment": self._build_outpatient_assessment,
            "plan": self._build_outpatient_plan,
            # ED_NOTE sections
            "triage_details": self._build_triage_details,
            "physical_exam": self._build_ed_physical_exam,
            "ed_workup": self._build_ed_workup,
            "disposition": self._build_ed_disposition,
            # ADMISSION_CARE_PLAN sections (LOINC 18776-5)
            "ward_and_room": self._build_acp_ward_and_room,
            "other_staff": self._build_acp_other_staff,
            "diagnosis": self._build_acp_diagnosis,
            "symptoms": self._build_acp_symptoms,
            "treatment_plan": self._build_acp_treatment_plan,
            "test_schedule": self._build_acp_test_schedule,
            "surgery_schedule": self._build_acp_surgery_schedule,
            "estimated_los": self._build_acp_estimated_los,
            "special_nutrition_management": self._build_acp_special_nutrition_management,
            "other_plans": self._build_acp_other_plans,
            # NUTRITION_CARE_PLAN sections (LOINC 80791-7)
            "ward_and_physician": self._build_ncp_ward_and_physician,
            "dietitian": self._build_ncp_dietitian,
            "nutrition_risk": self._build_ncp_nutrition_risk,
            "nutrition_assessment": self._build_ncp_nutrition_assessment,
            "nutrition_goals": self._build_ncp_nutrition_goals,
            "nutrition_supply": self._build_ncp_nutrition_supply,
            "dysphagia_diet": self._build_ncp_dysphagia_diet,
            "dietary_content": self._build_ncp_dietary_content,
            "nutrition_counseling": self._build_ncp_nutrition_counseling,
            "other_issues": self._build_ncp_other_issues,
            "reassessment_timing": self._build_ncp_reassessment_timing,
            "discharge_evaluation": self._build_ncp_discharge_evaluation,
            # P2-13 PR2a: JP-CLINS discharge summary sections (JP only)
            "admission_reason": self._build_admission_reason,
            "admission_details": self._build_admission_details,
            "admission_diagnoses": self._build_admission_diagnoses,
            "present_illness": self._build_present_illness,
            # JP-CLINS eDS discharge-side section builder. The other 4
            # discharge-side keys (hospital_course / discharge_diagnoses /
            # discharge_medications / discharge_instructions) reuse the
            # shared stage 1 entries above.
            "discharge_details": self._build_discharge_details,
            # P2-13 PR2b: JP-CLINS referral sections (JP only)
            "referring_institution": self._build_referring_institution,
            "referral_destination": self._build_referral_destination,
            "referral_purpose": self._build_referral_purpose,
            "diagnoses_and_complaint": self._build_diagnoses_and_complaint,
            "present_illness_ref": self._build_present_illness_ref,
            # P2-13 PR3: JP-eCheckup checkup report sections (JP only, opt-in)
            "checkup_lab_results": self._build_checkup_lab_results,
            "checkup_questionnaire": self._build_checkup_questionnaire,
            # REHABILITATION_PLAN sections (LOINC 34823-5)
            "patient_and_diagnosis": self._build_rp_patient_and_diagnosis,
            "rehab_team": self._build_rp_rehab_team,
            "functional_status": self._build_rp_functional_status,
            "basic_movement": self._build_rp_basic_movement,
            "session_frequency": self._build_rp_session_frequency,
            "goals": self._build_rp_goals,
            "policy": self._build_rp_policy,
            "discharge_estimate": self._build_rp_discharge_estimate,
            "explanation_consent": self._build_rp_explanation_consent,
            # Issue #961: DEATH_CERTIFICATE sections (LOINC 64297-5).
            "immediate_cause_of_death": self._build_dc_immediate_cause,
            "duration_of_immediate_cause": self._build_dc_duration_of_immediate_cause,
            "underlying_cause_of_death": self._build_dc_underlying_cause,
            "contributing_conditions": self._build_dc_contributing_conditions,
            "manner_of_death": self._build_dc_manner_of_death,
            "autopsy_status": self._build_dc_autopsy_status,
            # Issue #961 extension: DEATH_DISCHARGE_SUMMARY sections
            # (LOINC 18842-5 with title 死亡退院サマリー). Every section
            # produces a clinically-defensible template narrative from
            # CIF facts (admission dates, LOS, diagnoses, complications,
            # working diagnoses, autopsy sample) — LLM refinement is
            # opt-in polish, not a requirement for narrative validity.
            "admission_state": self._build_dds_admission_state,
            "treatment_course": self._build_dds_treatment_course,
            "terminal_course": self._build_dds_terminal_course,
            "circumstances_of_death": self._build_dds_circumstances_of_death,
            "cause_of_death": self._build_dds_cause_of_death,
            "complications_and_comorbidities": self._build_dds_complications_and_comorbidities,
            "family_communication": self._build_dds_family_communication,
            "autopsy_status_and_findings": self._build_dds_autopsy_status_and_findings,
            # Issue #991: OPERATIVE_NOTE sections (LOINC 11504-8). Each
            # builder scopes to the encounter's primary surgical procedure
            # via `_primary_surgical_procedure`; missing data degrades to
            # a fallback string rather than fabrication.
            "op_procedure_name": self._build_op_procedure_name,
            "op_anesthesia": self._build_op_anesthesia,
            "op_surgeon": self._build_op_surgeon,
            "op_findings": self._build_op_findings,
            "op_course": self._build_op_course,
            "op_specimens": self._build_op_specimens,
            "op_blood_loss": self._build_op_blood_loss,
            "op_equipment": self._build_op_equipment,
            "op_postop_plan": self._build_op_postop_plan,
            # Issue #992: PROCEDURE_NOTE sections (LOINC 28570-0). Keys
            # are ``pn_``-prefixed so they never collide with the
            # generic ``course`` / ``complications`` / ``specimens``
            # slugs a future document type may reuse.
            "pn_procedure_name": self._build_pn_procedure_name,
            "pn_consent": self._build_pn_consent,
            "pn_performer": self._build_pn_performer,
            "pn_analgesia": self._build_pn_analgesia,
            "pn_course": self._build_pn_course,
            "pn_complications": self._build_pn_complications,
            "pn_specimens": self._build_pn_specimens,
            "pn_postop_plan": self._build_pn_postop_plan,
        }

        # P2-13 PR2a: use the JP-specific section list when country=JP so
        # JP-CLINS Composition emit finds the 5 required sections
        # (admission_reason / admission_details / admission_diagnoses /
        # chief_complaint / present_illness) instead of the US 6-section set.
        section_list = spec.composition_sections_for(ctx.locale.upper())
        for section in section_list:
            builder = section_builders.get(section)
            if builder is not None:
                text, section_facts = builder(ctx)
                sections[section] = text
                facts.extend(section_facts)
            else:
                # Unknown section — generic fallback
                lang = ctx.target_lang
                sections[section] = _GENERIC_FALLBACK_JA if lang == "ja" else _GENERIC_FALLBACK_EN

        return NarrativeOutput(
            sections=sections,
            metadata={"generator": "template", "lang": ctx.target_lang},
            facts_used=facts,
        )

    # ─────────────────────────────────────────────────────────────────
    # Renderer: QUESTIONNAIRE_RESPONSE (infrastructure stub)
    # ─────────────────────────────────────────────────────────────────

    def _render_structured_form(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """QUESTIONNAIRE_RESPONSE infrastructure stub (not yet implemented).

        Returns empty structured dict with metadata indicating stub stage.
        (Not yet implemented).
        """
        return NarrativeOutput(
            structured={},
            metadata={
                "generator": "template",
                "lang": ctx.target_lang,
                "stage": "infrastructure_stub",
            },
            facts_used=[],
        )

    # ─────────────────────────────────────────────────────────────────
    # Section builders (COMPOSITION)
    # ─────────────────────────────────────────────────────────────────

    def _build_chief_complaint(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build chief_complaint section.

        v9 (2026-08-17): resolution order — actual encounter data first,
        then encounter_protocol / disease_protocol template, then a
        hardcoded fallback. v8 skipped encounter.chief_complaint entirely
        and jumped straight to protocol data, so real CIF entries like
        「手/腕の熱傷（部分層）」 or "Severe wheezing" were silently
        replaced by the hardcoded fallback 「発熱・全身倦怠感」 (density
        audit 2026-08-17 found this on every admission_hp / discharge_summary
        / ed_note whose disease_protocol had no `chief_complaint` slot).

        Priority chain:
          1. encounter.chief_complaint / encounter.chief_complaint_ja  (真の CIF、最優先)
          2. encounter_protocol.narrative.ed_note_template.chief_complaint_*
             (ED_NOTE only; encounter-level narrative override)
          3. disease_protocol.chief_complaint                          (疾患 default)
          4. hardcoded fallback「発熱・全身倦怠感」

        Issue #983 variant rotation (JP only): after resolving the raw
        source CC, if it matches the disease canonical CC (i.e. the
        simulator wrote the default), swap in a variant from
        ``chief_complaint_variants.yaml`` picked by a deterministic
        SHA256 sub-seed on (patient_id, encounter_id). Real encounter
        overrides (crush injury body-part strings, ED protocol templates)
        are never touched.
        """
        from clinosim.locale.loader import resolve_localized_display

        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = t("chief_complaint.hpi_fallback", lang)

        # Precompute the disease canonical CC — used to decide whether the
        # raw encounter CC is a disease default (variant-eligible) or a
        # real per-encounter override (leave untouched).
        disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol is not None else None
        canonical_disease_cc = self._disease_canonical_cc(ctx.disease_protocol, lang)
        # Fall-through slot: encounter_protocol carries its own canonical CC
        # + condition_id for ED "minor complaint" flows (chest_pain_noncardiac,
        # viral_uri, etc.) — the majority of ED CC frequency in the p=2000
        # audit lives here, not in a disease_protocol. When both slots have
        # variants the disease slot wins.
        encounter_condition_id = (
            _o(ctx.encounter_protocol, "condition_id", None) if ctx.encounter_protocol is not None else None
        )
        canonical_encounter_cc = self._disease_canonical_cc(ctx.encounter_protocol, lang)

        # 1. Encounter's own chief_complaint is the primary source of truth.
        enc = ctx.encounter
        if enc is not None:
            preferred_key = f"chief_complaint_{lang}"
            for key in (preferred_key, "chief_complaint"):
                raw = _o(enc, key, None)
                if raw:
                    raw_str = str(raw)
                    # Issue #983 — swap disease-default CCs for a variant.
                    swapped, swap_fact = self._maybe_swap_cc_variant(
                        raw_str,
                        disease_id,
                        canonical_disease_cc,
                        is_ja,
                        ctx,
                        encounter_condition_id=encounter_condition_id,
                        canonical_encounter_cc=canonical_encounter_cc,
                    )
                    facts.append(f"ctx.encounter.{key}")
                    if swap_fact:
                        facts.append(swap_fact)
                    return swapped, facts

        # 2. ED_NOTE: encounter_protocol.narrative.ed_note_template
        if ctx.document_type == DocumentType.ED_NOTE:
            ed_tmpl = self._get_ed_note_template(ctx)
            if ed_tmpl is not None:
                text = _pick_localized(ed_tmpl, "chief_complaint", lang, ctx)
                if text:
                    facts.append(f"encounter_protocol.narrative.ed_note_template.chief_complaint_{lang}")
                    return text, facts
            return fallback, facts

        # 3. disease_protocol.chief_complaint (per-disease default)
        proto = ctx.disease_protocol
        if proto is None:
            return fallback, facts

        cc = _o(proto, "chief_complaint", None)
        if cc is None:
            return fallback, facts

        if isinstance(cc, dict):
            text = resolve_localized_display(cc, lang, fallback=fallback)
            facts_key = f"disease_protocol.chief_complaint.{lang}"
            if text == fallback:
                facts_key += ":fallback"
            facts.append(facts_key)
        else:
            # Plain string (pre-Task-4 format)
            text = str(cc)
            facts.append("disease_protocol.chief_complaint:str")

        # Issue #983 — variant swap for the disease-protocol path too.
        swapped, swap_fact = self._maybe_swap_cc_variant(
            text,
            disease_id,
            canonical_disease_cc,
            is_ja,
            ctx,
            encounter_condition_id=encounter_condition_id,
            canonical_encounter_cc=canonical_encounter_cc,
        )
        if swap_fact:
            facts.append(swap_fact)
        return swapped, facts

    @staticmethod
    def _disease_canonical_cc(disease_protocol: Any, lang: str) -> str | None:
        """Return the disease-protocol canonical chief_complaint (single string).

        Used as the "is this a disease default?" comparison target for
        Issue #983 variant swapping.
        """
        from clinosim.locale.loader import resolve_localized_display

        if disease_protocol is None:
            return None
        cc = _o(disease_protocol, "chief_complaint", None)
        if cc is None:
            return None
        if isinstance(cc, dict):
            return resolve_localized_display(cc, lang, fallback="") or None
        return str(cc)

    @staticmethod
    def _maybe_swap_cc_variant(
        text: str,
        disease_id: str | None,
        canonical_cc: str | None,
        is_ja: bool,
        ctx: NarrativeContext,
        *,
        encounter_condition_id: str | None = None,
        canonical_encounter_cc: str | None = None,
    ) -> tuple[str, str | None]:
        """Issue #983 — swap disease-default CCs for a per-encounter variant.

        Returns ``(text, fact_or_none)``. When ``fact_or_none`` is not
        ``None`` the swap happened and callers should append it to
        ``facts``. Preserves real per-encounter overrides (burns "手/腕の
        熱傷", stroke fallback strings authored on Encounter, EN locale
        entirely) by returning the original ``text``.

        Two lookup keys are attempted in order:

          1. ``disease_id`` from ``ctx.disease_protocol`` — matches admissions
             for the 32 seeded diseases.
          2. ``encounter_condition_id`` from ``ctx.encounter_protocol`` —
             matches ED "minor complaint" flows (chest_pain_noncardiac,
             viral_uri, elderly_fall etc.). Most ED encounters take this
             path; a swap here breaks the pre-#983 uniform-per-condition
             concentration.
        """
        if not is_ja or not text:
            return text, None
        try:
            variants = load_chief_complaint_variants()
        except (OSError, ValueError):
            # Loader errors are non-fatal — narrative must never raise.
            return text, None

        # Priority 1 — disease_protocol
        if disease_id and canonical_cc and text == canonical_cc:
            pool = variants.get(disease_id) or []
            if len(pool) > 1:
                idx = TemplateNarrativeGenerator._cc_variant_index(disease_id, ctx, len(pool))
                return pool[idx], f"chief_complaint_variants.{disease_id}[{idx}]"

        # Priority 2 — encounter_protocol
        if encounter_condition_id and canonical_encounter_cc and text == canonical_encounter_cc:
            pool = variants.get(encounter_condition_id) or []
            if len(pool) > 1:
                idx = TemplateNarrativeGenerator._cc_variant_index(encounter_condition_id, ctx, len(pool))
                return (
                    pool[idx],
                    f"chief_complaint_variants.{encounter_condition_id}[{idx}]",
                )

        return text, None

    @staticmethod
    def _cc_variant_index(pool_key: str, ctx: NarrativeContext, pool_size: int) -> int:
        """Deterministic SHA256 sub-seed → variant index.

        Sub-seed on (pool_key, patient_id, encounter_id) — RNG-neutral
        (no ``ctx``-level RNG consumption; matches the pattern documented
        in ``feedback_rng_neutral_additive_field``).
        """
        patient_id = _o(ctx.patient, "patient_id", "") or ""
        encounter_id = _o(ctx.encounter, "encounter_id", "") if ctx.encounter is not None else ""
        seed = f"cc-variant|{pool_key}|{patient_id}|{encounter_id}"
        return int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:4], "big") % pool_size

    def _build_hpi(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build HPI section, then append the neonatal workup one-liner
        for birth admissions (Issue #1432).

        The core HPI builder has multiple return paths (ED_NOTE branch,
        no-narrative fallback, missing-hpi_template fallback, EN locale
        onset synthesis, JA onset_pattern) — wrapping the whole thing so
        every path picks up the newborn workup append without duplicating
        the check at each return.
        """
        text, facts = self._build_hpi_core(ctx)
        return self._maybe_append_newborn_workup(text, facts, ctx)

    def _maybe_append_newborn_workup(self, text: str, facts: list[str], ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Issue #1432: append the newborn workup one-liner to HPI when
        ``ctx.newborn_workup["is_neonate"]`` is true and the rendered
        summary is non-empty. The summary is built by
        ``replacement_strategy._render_newborn_workup_summary`` — the
        same helper the LLM prompt grounding uses, so template body and
        LLM narrative anchor on identical CIF-derived facts.
        """
        workup = getattr(ctx, "newborn_workup", None) or {}
        if not workup.get("is_neonate"):
            return text, facts
        from clinosim.modules.document.narrative.replacement_strategy import (
            _render_newborn_workup_summary,
        )

        summary = _render_newborn_workup_summary(workup, lang=ctx.target_lang)
        if not summary:
            return text, facts
        # Terminate the appended fragment with the locale-appropriate
        # sentence punctuation so the section reads as one paragraph.
        terminator = "。" if ctx.target_lang == "ja" else "."
        appended = f"{summary}{terminator}"
        if text:
            joined = f"{text} {appended}"
        else:
            joined = appended
        facts.append("ctx.newborn_workup")
        return joined, facts

    def _build_hpi_core(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """HPI content, pre-neonatal-append. See :meth:`_build_hpi`."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        # JA: localize severity token (mild/moderate/... → 軽度/中等度/...)
        # so the LLM doesn't inherit the EN token into its output — same
        # rule as `_build_admission_hp_condition` line ~1393. EN branch
        # keeps the raw token because it is already valid English.
        # #1266: guard against empty ctx.severity — for records with no
        # graded severity (e.g. newborn Z38.0 US, 28.5 % of admissions at
        # s=351 p=10k) the raw f-string interpolated `""` producing the
        # doubled-space fingerprint "Patient presented with  symptoms."
        # in the emitted Composition. Both locales use the natural
        # chief-complaint-less form on empty severity.
        sev = str(ctx.severity or "").strip()
        if sev and lang == "ja":
            from clinosim.modules.document.narrative.replacement_strategy import (
                _localize_severity_ja,
            )

            sev = _localize_severity_ja(sev)
        if sev:
            fallback = t("hpi_core.fallback_with_severity", lang, sev=sev)
        else:
            fallback = t("hpi_core.fallback_no_severity", lang)

        # ED_NOTE reads from ed_note_template
        if ctx.document_type == DocumentType.ED_NOTE:
            ed_tmpl = self._get_ed_note_template(ctx)
            if ed_tmpl is not None:
                text = _pick_localized(ed_tmpl, "hpi", lang, ctx)
                if text:
                    facts.append(f"encounter_protocol.narrative.ed_note_template.hpi_{lang}")
                    # Issue #984: append CIF-anchored HPI extras (age/sex,
                    # home meds, chronic list, ROS pertinent-negatives)
                    # to the ED_NOTE onset seed. Before #984 the ED HPI
                    # was a single-clause line (median 23 chars); the
                    # extras extend it to real-EHR admission-note richness.
                    extras = self._compose_hpi_extras_from_state(ctx)
                    if extras:
                        facts.extend(
                            [
                                "ctx.patient.demographics",
                                "ctx.patient.chronic_conditions",
                                "ctx.patient.current_medications",
                            ]
                        )
                        return f"{text} {extras}".strip(), facts
                    return text, facts
            return fallback, facts

        proto = ctx.disease_protocol
        narrative = _o(proto, "narrative", None) if proto is not None else None
        if narrative is None:
            # v9 (2026-08-17) density: still append CIF-derived context
            # so HPI carries real patient data even for chronic-follow-up
            # encounters whose disease YAML has no narrative section.
            extras = self._compose_hpi_extras_from_state(ctx)
            if extras:
                facts.extend(
                    ["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"]
                )
                return f"{fallback} {extras}".strip(), facts
            return fallback, facts

        hpi_tmpl = _o(narrative, "hpi_template", None)
        if hpi_tmpl is None:
            extras = self._compose_hpi_extras_from_state(ctx)
            if extras:
                facts.extend(
                    ["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"]
                )
                return f"{fallback} {extras}".strip(), facts
            return fallback, facts

        # US-locale leak fix. `hpi_template.onset_pattern` and
        # `trigger_options` in disease YAMLs are JP-only strings. The EN
        # locale previously emitted the JP text (tagged
        # `:ja_only_fallback`), which surfaced as CJK in US Composition
        # `.section[].text.div`. The EN locale now synthesizes a
        # locale-neutral English phrase per severity and skips
        # `trigger_options` entirely (per-disease English wording is
        # deferred to the LLM narrative pass — a functional fallback beats
        # a locale leak).
        if not is_ja:
            onset_text_en = _HPI_ONSET_EN.get(ctx.severity) or _HPI_ONSET_EN["moderate"]
            facts.append(f"generic:hpi_onset_en.{ctx.severity}")
            return onset_text_en, facts

        onset_pattern = _o(hpi_tmpl, "onset_pattern", {})
        if isinstance(onset_pattern, dict):
            onset_text = onset_pattern.get(ctx.severity) or onset_pattern.get("moderate") or ""
        else:
            onset_text = ""

        trigger_options = _o(hpi_tmpl, "trigger_options", []) or []
        trigger = trigger_options[0] if trigger_options else ""

        if onset_text:
            base = f"{onset_text} {trigger}".strip() if trigger else onset_text
            facts.append(f"disease_protocol.narrative.hpi_template.onset_pattern.{ctx.severity}")
            if trigger:
                facts.append("disease_protocol.narrative.hpi_template.trigger_options[0]")
        else:
            base = fallback

        # v9 (2026-08-17) density fix: append CIF-derived context
        # (demographics + chief_complaint + chronic overview) so HPI
        # carries per-patient specificity even when the disease YAML
        # onset_pattern is a short generic line.
        extras = self._compose_hpi_extras_from_state(ctx)
        text = f"{base} {extras}".strip() if extras else base
        if extras:
            facts.extend(
                ["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"]
            )

        return text, facts

    def _compose_hpi_extras_from_state(self, ctx: NarrativeContext) -> str:
        """Append CIF-anchored HPI enrichment (Issue #984).

        Extends the disease-YAML onset_pattern seed with:
          - demographics: age + sex
          - chief_complaint from ``ctx.encounter``
          - chronic short list (top 3)
          - home meds reconciliation (up to top 3 current_medications)
          - prior-care attempt sentinel (derived from chronic + med presence,
            never fabricated as a specific institution or datetime)
          - ROS pertinent negatives from per-disease yaml pool

        Previously (v9) emitted only demographics + CC + chronic and hit a
        median 23 chars. #984 lifts median to ~100-150 chars while staying
        template-only (no LLM dependency) and CIF-anchored (no fabrication)."""
        if ctx.target_lang != "ja":
            return ""
        patient = ctx.patient
        enc = ctx.encounter
        parts: list[str] = []
        age = _age_at(ctx) if patient else None
        sex = _o(patient, "sex", None) if patient else ""
        sex_ja = {"M": "男性", "F": "女性"}.get(str(sex).upper(), "")
        if age and sex_ja:
            parts.append(f"{age}歳{sex_ja}患者。")
        elif age:
            parts.append(f"{age}歳患者。")
        # chief_complaint from encounter (真の CIF、v9 bug fix)
        cc = ""
        if enc is not None:
            cc = _o(enc, "chief_complaint_ja", None) or _o(enc, "chief_complaint", None) or ""
        if cc:
            parts.append(f"主訴: {cc}。")
        # Chronic short list — Issue #1333: route CIF base code through
        # map_diagnosis_code so display matches the FHIR emit-target.
        from clinosim.codes import lookup as _code_lookup
        from clinosim.modules.output.fhir_r4.lib.common import (
            map_diagnosis_code as _map_diagnosis_code,
        )

        country = "JP" if ctx.locale.lower() == "jp" else "US"
        conds = _o(patient, "chronic_conditions", []) or []
        chronic_labels: list[str] = []
        for c in conds[:3]:
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            emit_code = _map_diagnosis_code(code, country) or code
            key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
            disp = _code_lookup(key, emit_code, ctx.target_lang) or emit_code
            chronic_labels.append(disp)
        if chronic_labels:
            parts.append(f"既往: {'、'.join(chronic_labels)}。")

        # Issue #984: home meds reconciliation (top 3 to keep HPI compact).
        # CIF-anchored — omitted when current_medications is empty; never
        # fabricated. Reuses _render_home_med_name so JA katakana localization
        # matches the medications_at_home section.
        meds = _o(patient, "current_medications", []) or []
        if meds:
            med_labels: list[str] = []
            for m in meds[:3]:
                name = _render_home_med_name(m, lang="ja")
                if name:
                    med_labels.append(name)
            if med_labels:
                more = f"他 {len(meds) - len(med_labels)} 剤" if len(meds) > len(med_labels) else ""
                joined = "、".join(med_labels) + (f"、{more}" if more else "")
                parts.append(f"常用薬: {joined}。")

        # Issue #984: prior-care sentinel (derived — never claim a specific
        # institution or datetime not in CIF). Two branches:
        #   (a) patient has chronic conditions + current_medications → "かかりつけ医
        #       で処方継続中" (evidence: patient is under ongoing care)
        #   (b) neither → omit (silent no-op)
        if conds and meds:
            parts.append("かかりつけ医で内服治療継続中。")
        elif meds:
            parts.append("外来にて内服処方継続中。")

        # Issue #984: ROS pertinent negatives from per-disease yaml pool.
        # Reads the FIRST-listed 2 negatives to keep HPI length realistic.
        # Fallback (no disease_id / not in yaml) → omit rather than fabricate.
        disease_id = ""
        if ctx.disease_protocol is not None:
            disease_id = str(_o(ctx.disease_protocol, "disease_id", "") or "")
        if disease_id:
            neg_pool = load_hpi_pertinent_negatives().get(disease_id) or []
            if neg_pool:
                # Use up to 2 to keep HPI compact.
                selected = neg_pool[:2]
                parts.append(f"ROS: {'、'.join(selected)}。")

        return "".join(parts)

    def _build_past_medical_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build past medical history from ctx.patient.chronic_conditions."""
        facts: list[str] = []
        lang = ctx.target_lang
        none_text = t("section_none.past_medical_history", lang)

        patient = ctx.patient
        if patient is None:
            return none_text, facts

        conditions = _o(patient, "chronic_conditions", []) or []
        if not conditions:
            return none_text, facts

        facts.append("ctx.patient.chronic_conditions")
        # Session-88j v3-review fix: resolve ICD code → localised disease
        # display via code_lookup ("icd-10" for JP-native codes / "icd-10-cm"
        # US). Previously the PMH section rendered raw codes ("J45 (Moderate
        # persistent); I10 (Stage 1); …") which read as a coding sheet
        # rather than a clinical PMH. LOOKUP failure falls back to the raw
        # code so the field is never empty.
        #
        # Issue #1333 fix: route the CIF base code through
        # ``map_diagnosis_code`` first so the narrative shows the same
        # billable code (and display) that the FHIR Condition emits. The
        # historical bug was US ``F00`` (dementia base) rendering as
        # "Dementia in Alzheimer disease" (WHO F00 parent-display leaked
        # from icd-10-cm.yaml) while FHIR emitted ``F03.90`` (unspecified
        # dementia) via ``code_mapping_diagnosis/us.yaml`` — narrative
        # ↔ FHIR disagreed on the disease name. Now the narrative looks
        # up the emit-target's display and prints the emit-target code in
        # the trailing ``[code]`` bracket.
        from clinosim.modules.output.fhir_r4.lib.common import map_diagnosis_code

        country = "JP" if ctx.locale.lower() == "jp" else "US"
        icd_system = _label("code_system_icd_display", "primary", lang)
        lines = []
        for cond in conditions:
            code = _o(cond, "code", "")
            stage = _o(cond, "stage", "")
            if not code:
                continue
            # Sex is not always available in ctx.patient shape; pass empty
            # so map_diagnosis_code takes the ``default`` on sex-conditional
            # entries (US C50 defaults to the female leaf per its docstring).
            emit_code = map_diagnosis_code(code, country) or code
            display = code_lookup(icd_system, emit_code, lang) or emit_code
            if display == emit_code:
                # Try 3-char parent (E11.9 → E11) — many mappings live only
                # at the category level.
                base = emit_code.split(".")[0]
                if base != emit_code:
                    display = code_lookup(icd_system, base, lang) or emit_code
            # Phase 1c-6 (2026-09-23): localize the severity /
            # persistence descriptor via ``_localize_stage`` so JA
            # emits 「気管支喘息 (軽度持続) [J45]」 rather than
            # 「気管支喘息 (Mild persistent) [J45]」. Mirrors the LLM
            # prompt Rule 5 A authorised table. ~245 leaks in the JP
            # p=10000 audit (Mild / Moderate / Severe / persistent /
            # intermittent).
            stage_display = _localize_stage(str(stage), lang) if stage else ""
            annotation = f" ({stage_display})" if stage_display else ""
            if display and display != emit_code:
                # Format: "気管支喘息 (軽度持続) [J45]" — code
                # trailing for traceability, humans read the display first.
                lines.append(f"{display}{annotation} [{emit_code}]")
            else:
                lines.append(f"{emit_code}{annotation}")
        if lines:
            return "; ".join(lines), facts
        return none_text, facts

    def _build_medications_at_home(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build home medications from ctx.patient.current_medications."""
        facts: list[str] = []
        lang = ctx.target_lang
        none_text = t("section_none.home_medications", lang)

        patient = ctx.patient
        if patient is None:
            return none_text, facts

        meds = _o(patient, "current_medications", []) or []
        if not meds:
            return none_text, facts

        facts.append("ctx.patient.current_medications")
        # Issue #452 PR 1: `HomeMedication` serializes to dict when the CIF is
        # written to disk and reloaded here in the narrative pass. Extract
        # drug_name explicitly so we don't render a Python dict repr.
        # v9 (2026-08-17): pass lang to enable JA katakana localization.
        return "; ".join(_render_home_med_name(m, lang=lang) for m in meds), facts

    def _build_allergies(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build allergies section from ctx.allergies.

        Resolves display via code_lookup ( — CIF stores allergen_code
        only, not display text; this mirrors _build_discharge_diagnoses'
        code_lookup pattern in this same file).
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang

        allergies = ctx.allergies or []
        if not allergies:
            return t("fallback.nkda", lang), facts

        # Issue #942: a cohort of exactly one NKA (No Known Allergies)
        # positive-assertion record is narratively equivalent to "no known
        # allergies" — collapse to the NKDA phrasing rather than surfacing
        # the SNOMED "no known allergy" label verbatim.
        if len(allergies) == 1 and bool(_o(allergies[0], "is_nka", False)):
            facts.append("ctx.allergies")
            return t("fallback.nkda", lang), facts

        facts.append("ctx.allergies")
        parts = []
        for allergy in allergies:
            # Skip NKA marker records when mixed alongside real allergies
            # (should not happen with the current enricher, but defensive).
            if bool(_o(allergy, "is_nka", False)):
                continue
            allergen_code = _o(allergy, "allergen_code", "") or ""
            display = code_lookup("snomed-ct", allergen_code, lang) if allergen_code else ""
            criticality = _o(allergy, "criticality", "") or ""
            if display:
                if criticality:
                    crit_str = t("allergy.criticality_suffix", lang, criticality=criticality)
                    parts.append(f"{display}{crit_str}")
                else:
                    parts.append(display)
        return "; ".join(parts) if parts else (t("fallback.nkda", lang)), facts

    def _build_social_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build social history from patient smoking_status, alcohol_use, occupation."""
        facts: list[str] = []
        lang = ctx.target_lang

        patient = ctx.patient
        if patient is None:
            return t("fallback.generic_fallback", lang), facts

        smoking_status = _o(patient, "smoking_status", "unknown") or "unknown"
        alcohol_use = _o(patient, "alcohol_use", "unknown") or "unknown"
        occupation = _o(patient, "occupation", "") or ""

        smoke_text = _label("smoking", smoking_status, lang, fallback=_label("smoking", "unknown", lang, fallback=""))
        alcohol_text = _label("alcohol", alcohol_use, lang, fallback=_label("alcohol", "unknown", lang, fallback=""))

        parts = []
        if smoke_text:
            key = t("section_label.smoking", lang)
            parts.append(f"{key}: {smoke_text}")
        if alcohol_text:
            key = t("section_label.alcohol", lang)
            parts.append(f"{key}: {alcohol_text}")
        if occupation:
            key = t("section_label.occupation", lang)
            # v6 (2026-08-16): localize occupation token; fall back to
            # raw when unmapped so a novel population value still renders
            # (rather than being dropped silently).
            occ_text = _label("occupation", occupation, lang, fallback=occupation)
            parts.append(f"{key}: {occ_text}")

        facts.append("ctx.patient.smoking_status")
        facts.append("ctx.patient.alcohol_use")
        facts.append("ctx.patient.occupation")

        fallback = t("fallback.generic_fallback", lang)
        return "; ".join(parts) if parts else fallback, facts

    def _build_family_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build family_history section from ``ctx.family_history`` (Issue #982).

        Pre-#982 this returned a hardcoded "特記家族歴なし" placeholder for
        every document, even when the CIF carried real
        FamilyMemberHistoryRecord entries (17,889 FHIR resources in the
        p=2000 audit — narrative rate was 1 distinct string across 171 docs).

        Walks ``ctx.family_history`` (list of ``FamilyMemberHistoryRecord``
        dicts or dataclasses), groups by relationship, translates each
        ``condition_code`` to a display via ``clinosim.codes.get_display``
        (JP → ICD-10-MHLW display; US → ICD-10-CM), and renders a
        relationship-grouped sentence. Falls back to the historical
        "特記家族歴なし" phrase when the CIF has no entries or when every
        relative carries an empty ``condition_codes`` list — the
        placeholder still needs to appear for that legitimate case
        (fam-hx generator emits a relative record even when the sampled
        conditions are empty, so a bare-relative record must not render
        as text-less output).
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.family_history_fallback", lang)

        fams = ctx.family_history or []
        if not fams:
            return fallback, facts

        # Country → code-system key for `get_display` lookup. `system_key_for`
        # is the same helper the FHIR emit-side family_history builder uses,
        # so the narrative and FHIR resource render the same disease label
        # per relative.
        country = "JP" if ctx.locale.lower() == "jp" else "US"
        try:
            icd_system_key = system_key_for("diagnosis", country)
        except KeyError:  # pragma: no cover — kind is hard-coded
            icd_system_key = _label("code_system_icd_lookup", "primary", lang)
        deceased_suffix = t("fallback.family_history_deceased_suffix", lang)
        cond_sep = t("list_sep.serial", lang)
        entry_sep = t("list_sep.space", lang)

        entries: list[str] = []
        for fam in fams:
            rel = str(_o(fam, "relationship", "") or "")
            label = _label("family_relation", rel, lang, fallback=rel or t("common.relative", lang))
            deceased = bool(_o(fam, "deceased", False))
            codes = list(_o(fam, "condition_codes", []) or [])
            displays: list[str] = []
            for code in codes:
                if not code:
                    continue
                # get_display falls back to the code string when the
                # display is missing — that surfaces a code rather than an
                # empty entry, better than dropping the relative silently.
                disp = code_display(icd_system_key, str(code), country=country)
                if disp:
                    displays.append(str(disp))
            if not displays:
                # A relative with no sampled conditions carries no clinical
                # signal. Skip so we don't render "母 – 。" empty entries.
                continue
            suffix = deceased_suffix if deceased else ""
            joined = cond_sep.join(displays)
            entries.append(t("family_history.entry_line", lang, label=label, suffix=suffix, conditions=joined))

        if not entries:
            return fallback, facts

        facts.append("ctx.family_history")
        prefix = t("section_label.family_history_prefix", lang)
        return prefix + entry_sep.join(entries), facts

    def _build_physical_examination(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build physical_examination using multi-step fallback chain.

        Issue #979: prepend a JA vital-signs prose line (BP / HR / T / SpO2
        / RR) sourced from CIF ``ctx.vitals`` for the appropriate day
        (admission notes → day 0, discharge summaries → last day, progress
        notes → ``ctx.day_index``). Silently omit the vitals block when
        ``ctx.vitals`` is empty for this day — no placeholder emitted.

        Issue #980: after formatting the per-body-system prose, rewrite
        「意識清明」 clauses to a plausible JCS/GCS phrase when the CIF
        chief_complaint carries an altered-consciousness keyword, and rewrite
        「呼吸音清明」 clauses when the CC carries a severe-dyspnea keyword.
        Deterministic per-encounter pool pick (SHA256), RNG-neutral.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        # Issue #1156: EN PE previously short-circuited to a bare
        # "No special findings" placeholder. The JP-only per-disease
        # ``physical_exam_findings`` YAML content still cannot be reused
        # (would leak CJK), but the vitals line ``_compose_pe_vitals_line``
        # produces a language-neutral prose string ("BP 130/80 mmHg, HR
        # 88/min, T 37.5°C, SpO2 96% (RA), RR 20/min") that reads
        # cleanly in either locale. EN now prepends the vitals block
        # so admission H&P PE carries at least the encounter's
        # objective vitals instead of being blank.
        if not is_ja:
            vitals_line = self._compose_pe_vitals_line(ctx)
            if vitals_line:
                facts.append(f"ctx.vitals[day_{ctx.day_index}]")
                return f"Vital signs: {vitals_line}. General: no additional exam findings recorded.", facts
            facts.append("generic:physical_exam_en")
            return _GENERIC_FALLBACK_EN, facts

        phys_exam = self._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
        if phys_exam:
            facts.append(f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}")

        text = self._format_physical_exam(phys_exam, ctx.severity, lang)
        if not text:
            text = _GENERIC_FALLBACK_JA

        # #980: rewrite contradicted clauses BEFORE #979 prepend so the
        # rewrite operates on the "labelled clause" shape produced by
        # `_format_physical_exam` (see `_rewrite_pe_clause` docstring).
        text, cc_facts = self._apply_cc_pe_consistency(text, ctx)
        facts.extend(cc_facts)

        # #979: prepend vital-signs prose line for this day.
        vitals_line = self._compose_pe_vitals_line(ctx)
        if vitals_line:
            facts.append(f"ctx.vitals[day_{ctx.day_index}]")
            text = f"バイタルサイン: {vitals_line}。{text}"

        return text, facts

    def _build_assessment_and_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build assessment_and_plan from daily_trajectory day_0 assessment + plan."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        # Issue #1156: EN branch previously short-circuited to the
        # generic "Clinical assessment ongoing. Plan: Continue current
        # management." string for every admission, disconnecting the
        # H&P A&P section from the chief complaint. The EN branch now
        # calls the same CIF-derived composers as JA (which were made
        # language-aware in the same fix), so an asthma-exacerbation
        # admission reads "Admitted for evaluation and management of:
        # Severe wheezing... Initial medications: Prednisone, Albuterol..."
        # instead of the disconnected generic fallback. daily_trajectory
        # YAML content is still JA-only so EN skips that source.
        if not is_ja:
            facts.append("composed:cif_state_en")
            _en_assessment = self._compose_ap_assessment_from_state(ctx) or _GENERIC_ASSESSMENT_EN
            _en_plan = self._compose_ap_plan_from_state(ctx) or _GENERIC_PLAN_EN
            return f"Assessment: {_en_assessment} Plan: {_en_plan}", facts

        traj, traj_src = self._resolve_daily_trajectory_with_source(ctx, ctx.clinical_course_archetype, 0)
        if traj_src:
            facts.append(traj_src)

        _generic_a = _GENERIC_ASSESSMENT_JA
        _generic_p = _GENERIC_PLAN_JA
        # v9 (2026-08-17) density fix — v8 emitted only 19-char
        # "評価: 経過観察中。方針: 治療継続。". Compose an A&P from CIF
        # facts (diagnosis + severity + orders/procedures/meds today +
        # LOS estimate) so the section is clinically informative even
        # when disease YAML has no day_0 trajectory content. The
        # placeholder-aware _prefer helper matches the pattern used in
        # _render_progress_note_text.
        _placeholders = {_generic_a, _generic_p, ""}
        traj_a = traj.get("assessment")
        traj_p = traj.get("plan")
        assessment = (
            traj_a
            if (traj_a and traj_a not in _placeholders)
            else (self._compose_ap_assessment_from_state(ctx) or _generic_a)
        )
        plan = (
            traj_p
            if (traj_p and traj_p not in _placeholders)
            else (self._compose_ap_plan_from_state(ctx) or _generic_p)
        )
        text = f"【評価】{assessment}\n【方針】{plan}"
        return text, facts

    def _compose_ap_assessment_from_state(self, ctx: NarrativeContext) -> str:
        """admission_hp Assessment composed from CIF (v9 density fix).

        Issue #1156: prior to session-103 this composer returned ""
        for non-JA locales, forcing EN admission H&P sections into the
        ``Clinical assessment ongoing`` fallback regardless of the
        actual chief complaint / disease / severity. EN branch now
        parallels the JA structure (same CIF sources, English wording).
        """
        lang = ctx.target_lang
        parts: list[str] = []
        enc = ctx.encounter
        # Primary reason — try the localized ``chief_complaint_<lang>``
        # slot first, then fall back to the language-agnostic base
        # ``chief_complaint`` field. Preserves the pre-Phase-1d-18
        # behaviour: JA reads chief_complaint_ja first, EN reads
        # chief_complaint first (there is no chief_complaint_en slot on
        # PatientProfile) — but the branch is now data-driven.
        if enc is None:
            cc = None
        else:
            cc = _o(enc, f"chief_complaint_{lang}", None) or _o(enc, "chief_complaint", None)
        if cc:
            parts.append(t("ap_assessment.chief_complaint_line", lang, cc=cc))
        # Severity + disease
        # session-88j P1-12/Bug-3: JA output must not leak raw EN severity
        # (mild / moderate / severe / critical) into 「病態: X (Y)」. v14
        # review found 8/1084 admission_hp narratives with EN severity.
        # Localize severity for JA locale via the shared JA severity map.
        if ctx.disease_protocol is not None:
            disease = _o(ctx.disease_protocol, "disease_id", None)
            if disease:
                _sev = str(ctx.severity or "")
                if _sev and lang == "ja":
                    from clinosim.modules.document.narrative.replacement_strategy import (
                        _localize_severity_ja,
                    )

                    _sev = _localize_severity_ja(_sev)
                # Phase 1c-2 (2026-09-22): the raw disease_id snake_case
                # token ("bacterial_pneumonia", "acute_myocardial_infarction")
                # leaked into JA narratives.
                # ``_localize_complication`` covers the disease-id vocabulary
                # too because ``disease_id`` and complication tokens draw
                # from the same disease-YAML namespace.
                disease_label = _localize_complication(str(disease), lang)
                parts.append(t("ap_assessment.disease_severity_line", lang, disease=disease_label, severity=_sev))
        # Chronic backdrop — Issue #1333: route CIF base code through
        # map_diagnosis_code so display matches the FHIR emit-target.
        conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
        if conds:
            from clinosim.codes import lookup as _code_lookup
            from clinosim.modules.output.fhir_r4.lib.common import (
                map_diagnosis_code as _map_diagnosis_code,
            )

            country = "JP" if ctx.locale.lower() == "jp" else "US"
            key = _label("code_system_icd_display", "primary", lang)

            def _resolve_chronic_label(c: object) -> str:
                base = _o(c, "code", "") or ""
                if not base:
                    return ""
                emit = _map_diagnosis_code(base, country) or base
                return _code_lookup(key, emit, lang) or emit

            labels = [_resolve_chronic_label(c) for c in conds[:4]]
            labels = [lbl for lbl in labels if lbl]
            if labels:
                sep = t("list_sep.serial", lang)
                parts.append(t("ap_assessment.comorbidities_line", lang, list=sep.join(labels)))
        if not parts:
            parts.append(t("ap_assessment.acute_fallback", lang))
        return t("list_sep.chunk", lang).join(parts)

    def _compose_ap_plan_from_state(self, ctx: NarrativeContext) -> str:
        """admission_hp Plan composed from CIF (v9 density fix).

        Issue #1156: EN branch added — parallels the JA structure so
        the EN admission H&P plan section carries LOS estimate, day-0
        medication orders, and workup procedures instead of the
        ``Continue current management`` fallback.
        """
        lang = ctx.target_lang
        parts: list[str] = []
        # LOS estimate — Issue #1185 F4: two sections of the same admission_hp
        # document reported different planned LOS numbers (25日 vs 17日)
        # because `_compose_ap_plan_from_state` used `ctx.los_days` (the
        # actual observed LOS) while `_build_acp_estimated_los` used the
        # canonical `_estimated_los_days()` resolver (protocol mean =
        # AT-ADMISSION prediction). Route both through the canonical
        # resolver so the "予定入院期間" and "推定入院期間" slots of the
        # same document quote the same value. The resolver falls back to
        # `ctx.los_days` when disease_protocol is unavailable.
        los, _los_facts = self._estimated_los_days(ctx)
        if los > 0:
            parts.append(t("ap_plan.estimated_los", lang, los=los))
        # Today's meds (day 0 admission-day filter). Same explicit-day-else-
        # timestamp-derived pattern as `_compose_progress_plan_from_state`
        # (Issue #1154) so real CIF MedicationAdministration without a
        # ``day`` field still filters correctly.
        _adm_raw = _o(getattr(ctx, "encounter", None), "admission_datetime", None)
        _adm_dt = _parse_iso_datetime(_adm_raw) if _adm_raw is not None else None
        admins = list(ctx.medications or [])
        med_names: list[str] = []
        seen: set[str] = set()
        for m in admins[:60]:
            d = _o(m, "day", None)
            if d is None and _adm_dt is not None:
                _mts_raw = _o(m, "actual_datetime", None) or _o(m, "scheduled_datetime", None)
                _mts = _parse_iso_datetime(_mts_raw) if _mts_raw is not None else None
                if _mts is not None:
                    # Session-104 Issue #1166: calendar-day bucket
                    # (sibling of _filter_vitals_for_day v7).
                    d = (_mts.date() - _adm_dt.date()).days
            if d is not None and d != 0:  # admission day
                continue
            name = _o(m, "drug_name", None) or _o(m, "medication", None)
            if not name or name in seen:
                continue
            seen.add(name)
            if lang == "ja":
                # Drug-name katakana lookup is a JA-locale-specific data
                # pipeline (not just a display translation), so this
                # branch dispatches on lang. Extending to fr/zh/… would
                # add a matching per-locale drug-name resolver, not
                # extend a YAML phrase catalog.
                from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

                med_names.append(_localize_drug_name(str(name), "JP"))
            else:
                med_names.append(str(name))
            if len(med_names) >= 6:
                break
        if med_names:
            sep = t("list_sep.serial", lang)
            parts.append(t("ap_plan.initial_meds", lang, list=sep.join(med_names)))
        # Ordered procedures (workup)
        procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:4]]
        procs = [p for p in procs if p]
        if procs:
            sep = t("list_sep.serial", lang)
            parts.append(t("ap_plan.workup_procedures", lang, list=sep.join(str(p) for p in procs)))
        if not parts:
            parts.append(t("ap_plan.observation_fallback", lang))
        return t("list_sep.chunk", lang).join(parts)

    def _build_admission_summary(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build admission_summary for DISCHARGE_SUMMARY."""
        facts: list[str] = []
        lang = ctx.target_lang

        cc_text, cc_facts = self._build_chief_complaint(ctx)
        facts.extend(cc_facts)

        text = t("admission_summary.head_line", lang, cc=cc_text, day=ctx.day_index + 1)

        return text, facts

    # ─────────────────────────────────────────────────────────────────
    # P2-13 PR2a: JP-CLINS discharge-summary section builders (JP-only).
    # Consumed when country=JP and doc_type=discharge_summary. The US
    # path returns the original 6-section list via
    # composition_sections_for("US"). Each builder keeps the common
    # signature and branches internally on ctx.target_lang.
    # ─────────────────────────────────────────────────────────────────

    def _build_admission_reason(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """312 入院理由セクション:入院理由の一言記述。

        Resolve primary admission diagnosis display via clinosim.codes.lookup.
        Falls back to chief complaint if code cannot be resolved.
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang
        diagnoses = ctx.diagnoses or []
        primary = diagnoses[0] if diagnoses else None
        code = ""
        system = ""
        if primary is not None:
            code = _o(primary, "admission_diagnosis_code", "") or _o(primary, "discharge_diagnosis_code", "")
            system = (
                _o(primary, "admission_diagnosis_system", "")
                or _o(primary, "discharge_diagnosis_system", "")
                or system_key_for("diagnosis", ctx.locale.upper())
            )
        display = code_lookup(system, code, lang) if code else ""
        if display and display != code:
            facts.append("ctx.diagnoses[0].admission_diagnosis_code")
            subject = display
        else:
            cc_text, cc_facts = self._build_chief_complaint(ctx)
            facts.extend(cc_facts)
            subject = cc_text
        text = t("admission_reason.admitted_for", lang, subject=subject)
        return text, facts

    def _build_admission_details(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """322 入院時詳細セクション:入院日・入院経路(救急経由か)・入棟病棟。

        JA sentence structure joins fragments with 「、」 then closes
        with 「に入院した。」. EN joins with " " then a trailing period.
        Fragment templates live in ``narrative_phrases.yaml::
        admission_details``.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        enc = ctx.encounter
        adm_dt = _o(enc, "admission_datetime", "") if enc is not None else ""
        ward = _o(enc, "ward", "") if enc is not None else ""
        via_ed = bool(_o(enc, "via_emergency", False)) if enc is not None else False
        facts.append("ctx.encounter.admission_datetime")

        # Format admission datetime to YYYY-MM-DD only
        adm_date = ""
        if adm_dt:
            adm_date = str(adm_dt).split("T")[0]
        fragments: list[str] = []
        if adm_date:
            fragments.append(t("admission_details.date_slot", lang, date=adm_date))
        if via_ed:
            fragments.append(t("admission_details.via_ed_slot", lang))
        if ward:
            fragments.append(t("admission_details.ward_slot", lang, ward=ward))
        if not fragments:
            return t("admission_details.fallback", lang), facts
        parts_joined = t("admission_details.fragment_sep", lang).join(fragments)
        return t("admission_details.full_line", lang, parts=parts_joined), facts

    def _build_discharge_details(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """324 退院時詳細セクション:退院日・退院病棟・退院時転帰(JP-only)。

        One of the 5 discharge-side mandatory sections in the eDS spec.
        An earlier state emitted only the slice code, leaving the
        narrative content unset — that violated `text.div SHALL have
        non-whitespace content` (FHIR R4 `txt-2`) on 130+ resources per
        fullset. This template mirrors `_build_admission_details`
        symmetrically to close that gap.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        enc = ctx.encounter
        dis_dt = _o(enc, "discharge_datetime", None) if enc is not None else None
        ward = _o(enc, "ward", "") if enc is not None else ""
        disposition = _o(enc, "discharge_disposition", "") if enc is not None else ""
        facts.append("ctx.encounter.discharge_datetime")
        # Disposition slug → per-locale narrative label lives in
        # ``narrative_labels.yaml::discharge_disposition`` (Phase 1d-32).

        dis_date = ""
        if dis_dt:
            dis_date = str(dis_dt).split("T")[0]

        dispo_default = t("discharge_details.disposition_default", lang)
        dispo_label = _label("discharge_disposition", disposition, lang, fallback=dispo_default)

        if lang == "ja":
            parts: list[str] = []
            if dis_date:
                parts.append(dis_date)
            if ward:
                parts.append(t("discharge_details.ward_slot", lang, ward=ward))
            parts.append(f"{dispo_label}となった。")
            text = "、".join(parts[:-1]) + parts[-1] if len(parts) > 1 else parts[0]
            if not text:
                text = t("discharge_details.fallback_ja_only", lang)
        else:
            fragments: list[str] = []
            if dis_date:
                fragments.append(t("discharge_details.date_slot", lang, date=dis_date))
            if ward:
                fragments.append(t("discharge_details.ward_slot", lang, ward=ward))
            fragments.append(f"({dispo_label})")
            text = " ".join(fragments) + "." if fragments else "Discharge details not recorded."
        return text, facts

    def _build_admission_diagnoses(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """342 入院時診断セクション:入院時診断名の番号付きリスト。

        _build_discharge_diagnoses と同じ code-lookup pattern を再利用するが
        ``admission_diagnosis_code`` を最優先で拾い、無ければ
        ``discharge_diagnosis_code`` に fallback。
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang
        diagnoses = ctx.diagnoses or []
        if not diagnoses:
            return t("section_none.admission_diagnoses", lang), facts

        facts.append("ctx.diagnoses")
        lines: list[str] = []
        for idx, dx in enumerate(diagnoses, start=1):
            code = _o(dx, "admission_diagnosis_code", "") or _o(dx, "discharge_diagnosis_code", "")
            if not code:
                continue
            system = (
                _o(dx, "admission_diagnosis_system", "")
                or _o(dx, "discharge_diagnosis_system", "")
                or system_key_for("diagnosis", ctx.locale.upper())
            )
            display = code_lookup(system, code, ctx.target_lang)
            if display and display != code:
                lines.append(t("list_item.numbered_dx_with_code", lang, idx=idx, display=display, code=code))
            else:
                lines.append(f"{idx}. {code}")
        if not lines:
            return t("section_none.admission_diagnoses", lang), facts
        return "\n".join(lines), facts

    def _build_present_illness(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """360 現病歴セクション:現病歴の短文記述。

        退院時サマリー用は ADMISSION_HP と同じ disease_protocol の HPI
        reuses this template. Tense variation (narrative tone) will be
        LLM 差替時に調整予定。
        """
        hpi_text, facts = self._build_hpi(ctx)
        lang = ctx.target_lang
        # HPI is already structured as a chronological onset narrative, so
        # no structural changes are needed. Text style harmonization will be
        # deferred to the LLM narrative pass when applicable.
        if not hpi_text:
            # #1266 empty-severity guard (see `_build_hpi`). JA severity
            # translation via _localize_severity_ja is JA-locale-specific
            # (JA disease severity ontology mapping); other locales use
            # the raw token via the phrase template.
            sev = str(ctx.severity or "").strip()
            if sev and lang == "ja":
                from clinosim.modules.document.narrative.replacement_strategy import (
                    _localize_severity_ja,
                )

                sev = _localize_severity_ja(sev)
            if sev:
                hpi_text = t("hpi.admission_with_severity", lang, sev=sev)
            else:
                hpi_text = t("hpi.admission_no_severity", lang)
        return hpi_text, facts

    # ─────────────────────────────────────────────────────────────────
    # P2-13 PR2b: JP-CLINS referral (referral letter) section
    # builders. JP-only.
    # ─────────────────────────────────────────────────────────────────

    def _build_referring_institution(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """920 紹介元情報セクション:紹介元(送信元)医療機関の記載。

        clinosim は単一病院を simulate するため、紹介元は常に当院固定。
        Dynamic facility name retrieval from hospital_config is deferred
        to the LLM narrative pass for future enhancement.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        return t("referral.referring_institution_line", lang), facts

    def _build_referral_destination(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """910 紹介先情報セクション:紹介先医療機関の記載。

        clinosim は機関間連携 workflow を simulate しないため、紹介先は
        汎用 "他院" placeholder。将来:受け入れ想定医療機関の小さな pool
        から sample する余地あり。
        """
        facts: list[str] = []
        lang = ctx.target_lang
        return t("referral.referral_destination_line", lang), facts

    # Ordered key tuple for _build_referral_purpose SHA256 index
    # sampling (Phase 1d-28). Key order is load-bearing: it defines
    # which YAML slot maps to which hash-index, so cohort determinism
    # depends on preserving it.
    _REFERRAL_PURPOSE_KEYS: tuple[str, ...] = (
        "option_1",
        "option_2",
        "option_3",
        "option_4",
    )

    def _build_referral_purpose(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """950 紹介目的セクション:標準セットから決定的に一つ選択。

        encounter_id の hash で 4 選択肢から index 決定。cohort 全体で
        分布は stable、encounter 個別ではばらつき保持。
        """
        import hashlib

        facts: list[str] = []
        lang = ctx.target_lang
        enc = ctx.encounter
        enc_id = _o(enc, "encounter_id", "") or "ENC-UNKNOWN"
        digest = hashlib.sha256(enc_id.encode("utf-8")).digest()
        idx = digest[0] % len(self._REFERRAL_PURPOSE_KEYS)
        picked = _label("referral_purpose_options", self._REFERRAL_PURPOSE_KEYS[idx], lang)
        facts.append(f"ctx.encounter.encounter_id[hash-idx={idx}]")
        return t("referral.referral_purpose_line", lang, purpose=picked), facts

    def _build_diagnoses_and_complaint(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """340 傷病名・主訴セクション:傷病名リスト + 主訴の複合セクション。"""
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang

        # Diagnoses
        diagnoses = ctx.diagnoses or []
        dx_lines: list[str] = []
        for idx, dx in enumerate(diagnoses, start=1):
            code = _o(dx, "discharge_diagnosis_code", "") or _o(dx, "admission_diagnosis_code", "")
            if not code:
                continue
            system = (
                _o(dx, "discharge_diagnosis_system", "")
                or _o(dx, "admission_diagnosis_system", "")
                or system_key_for("diagnosis", ctx.locale.upper())
            )
            display = code_lookup(system, code, lang)
            if display and display != code:
                dx_lines.append(t("list_item.numbered_dx_with_code", lang, idx=idx, display=display, code=code))
            else:
                dx_lines.append(f"{idx}. {code}")
        if dx_lines:
            facts.append("ctx.diagnoses")

        # Chief complaint
        cc_text, cc_facts = self._build_chief_complaint(ctx)
        facts.extend(cc_facts)

        dx_body = "\n".join(dx_lines) if dx_lines else t("diagnoses_and_complaint.no_diagnoses", lang)
        text = t("diagnoses_and_complaint.section", lang, dx_lines=dx_body, cc_text=cc_text)
        return text, facts

    def _build_present_illness_ref(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """360 現病歴セクション(診療情報提供書用):HPI builder を再利用。"""
        hpi_text, facts = self._build_hpi(ctx)
        lang = ctx.target_lang
        if not hpi_text:
            # #1266 empty-severity guard (see `_build_hpi`).
            sev = str(ctx.severity or "").strip()
            if sev and lang == "ja":
                from clinosim.modules.document.narrative.replacement_strategy import (
                    _localize_severity_ja,
                )

                sev = _localize_severity_ja(sev)
            if sev:
                hpi_text = t("hpi.ref_with_severity", lang, sev=sev)
            else:
                hpi_text = t("hpi.ref_no_severity", lang)
        return hpi_text, facts

    # ─────────────────────────────────────────────────────────────────
    # P2-13 PR3: JP-eCheckup checkup report (health-checkup report)
    # section builders. JP-only, opt-in. Covers the 2 mandatory sections
    # of the 事業者健診 (statutory occupational-health checkup).
    # ─────────────────────────────────────────────────────────────────

    def _build_checkup_lab_results(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """01031 事業者健診検査結果セクション:法定健診項目の判定文。

        sub-PR-B: ctx.lab_results から健診 5 項目の実測値を拾い、法定健診の
        基準に基づき A/B/C/D 判定を組み立てる。lab_results が空(または一部
        欠損)の場合は該当項目を「未測定」と記す。総合判定は各項目の最悪判定
        を返す。将来:HDL / TC / TG や AST / ALT を追加する sub-PR で拡張
        余地あり。
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        # Extract 5 measured values from lab_results keyed by LOINC code
        results_by_loinc: dict[str, float | None] = {}
        for r in ctx.lab_results or []:
            loinc = _o(r, "lab_name", "")
            val = _o(r, "value", None)
            if loinc in {"39156-5", "8480-6", "8462-4", "4548-4", "18262-6"}:
                results_by_loinc[loinc] = val
                facts.append(f"ctx.lab_results[{loinc}]")

        # Helper returns assessment per item (A=normal, B=borderline,
        # C=guidance needed, D=detailed testing needed)
        def _judge_bmi(v: float | None) -> tuple[str, str]:
            if v is None:
                return ("未測定", "A")
            if v < NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE:
                return (f"{v:.1f}(低体重)", "B")
            if v < NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE:
                return (f"{v:.1f}(標準)", "A")
            if v < NARRATIVE_BMI_OBESITY_MILD_MAX_EXCLUSIVE:
                return (f"{v:.1f}(肥満 1 度)", "B")
            return (f"{v:.1f}(肥満 2 度以上)", "C")

        def _judge_bp(sys_v: float | None, dia_v: float | None) -> tuple[str, str]:
            if sys_v is None or dia_v is None:
                return ("未測定", "A")
            if sys_v >= NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD or dia_v >= NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD:
                return (f"{sys_v:.0f}/{dia_v:.0f} mmHg(高血圧)", "D")
            if sys_v >= NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD or dia_v >= NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD:
                return (f"{sys_v:.0f}/{dia_v:.0f} mmHg(高値注意)", "B")
            return (f"{sys_v:.0f}/{dia_v:.0f} mmHg(基準内)", "A")

        def _judge_hba1c(v: float | None) -> tuple[str, str]:
            if v is None:
                return ("未測定", "A")
            if v >= NARRATIVE_HBA1C_DIABETES_THRESHOLD:
                return (f"{v:.1f}%(糖尿病型)", "D")
            if v >= NARRATIVE_HBA1C_BORDERLINE_THRESHOLD:
                return (f"{v:.1f}%(境界)", "B")
            return (f"{v:.1f}%(基準内)", "A")

        def _judge_ldl(v: float | None) -> tuple[str, str]:
            if v is None:
                return ("未測定", "A")
            if v >= NARRATIVE_LDL_HIGH_THRESHOLD:
                return (f"{v:.0f} mg/dL(高 LDL 血症)", "D")
            if v >= NARRATIVE_LDL_BORDERLINE_THRESHOLD:
                return (f"{v:.0f} mg/dL(境界域)", "C")
            if v >= NARRATIVE_LDL_ELEVATED_THRESHOLD:
                return (f"{v:.0f} mg/dL(高値注意)", "B")
            return (f"{v:.0f} mg/dL(基準内)", "A")

        bmi_desc, bmi_grade = _judge_bmi(results_by_loinc.get("39156-5"))
        bp_desc, bp_grade = _judge_bp(results_by_loinc.get("8480-6"), results_by_loinc.get("8462-4"))
        hba1c_desc, hba1c_grade = _judge_hba1c(results_by_loinc.get("4548-4"))
        ldl_desc, ldl_grade = _judge_ldl(results_by_loinc.get("18262-6"))

        # Overall assessment = worst grade across all items (A<B<C<D)
        grades = [bmi_grade, bp_grade, hba1c_grade, ldl_grade]
        overall = max(grades, key=lambda g: "ABCD".index(g))
        overall_note = {
            "A": "異常なし",
            "B": "軽度異常、生活指導",
            "C": "要指導",
            "D": "要精査・要治療",
        }[overall]

        if is_ja:
            text = (
                f"【身体計測】BMI:{bmi_desc}。\n"
                f"【血圧】{bp_desc}。\n"
                f"【血糖・HbA1c】HbA1c:{hba1c_desc}。\n"
                f"【脂質】LDL:{ldl_desc}。\n"
                f"総合判定:{overall}({overall_note})。"
            )
        else:
            text = (
                f"Body measurements: BMI {bmi_desc}.\n"
                f"Blood pressure: {bp_desc}.\n"
                f"HbA1c: {hba1c_desc}.\n"
                f"LDL: {ldl_desc}.\n"
                f"Overall assessment: {overall} ({overall_note})."
            )
        return text, facts

    def _build_checkup_questionnaire(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """01032 事業者健診問診結果セクション:PatientProfile 依存の個別問診記録。

        sub-PR-B: ctx.patient から以下を反映:
          - 既往歴:chronic_conditions(code → 日本語 display)
          - 服薬:current_medications
          - 生活習慣:smoking_status / alcohol_use
        判定は慢性疾患を持つ患者は「経過観察を要す」、それ以外は「経過
        観察不要」を返す MVP ロジック。将来 sub-PR で身体活動量・食習慣
        などの詳細問診を追加可能。
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang
        patient = ctx.patient

        # Convert past medical history (chronic_conditions) codes to
        # locale-appropriate display text. JP forces the ICD-10 authority
        # (JP-CLINS uses base icd-10, not the US -CM modification);
        # other locales use whatever ``system`` the CIF Condition
        # carries (typically icd-10-cm on US records).
        chronic = _o(patient, "chronic_conditions", []) or []
        history_lines: list[str] = []
        for cond in chronic:
            code = _o(cond, "code", "")
            system = _o(cond, "system", "icd-10-cm") or "icd-10-cm"
            if not code:
                continue
            resolved_system = system_key_for("diagnosis", "JP") if lang == "ja" else system
            display = code_lookup(resolved_system, code, lang)
            if display and display != code:
                history_lines.append(t("list_item.bullet_dx_with_code", lang, display=display, code=code))
            else:
                history_lines.append(t("checkup_questionnaire.history_raw_line", lang, code=code))
        if chronic:
            facts.append("ctx.patient.chronic_conditions")
        history_text = "\n".join(history_lines) if history_lines else t("section_none.history_none_noted", lang)

        # Current medications: list may contain HomeMedication objects or
        # mixed dict/str entries
        current_meds = _o(patient, "current_medications", []) or []
        if current_meds:
            facts.append("ctx.patient.current_medications")
        med_text = (
            t("list_sep.serial", lang).join(_render_home_med_name(m) for m in current_meds)
            if current_meds
            else t("section_none.home_medications_alt", lang)
        )

        # 生活習慣(smoking_status / alcohol_use). Vocabulary moved to
        # ``narrative_labels.yaml::checkup_smoking_status / _alcohol_use``.
        # Unknown values fall back to per-lang formatters (JA marks
        # ``(区分未定義)``, EN emits the raw slug — matches pre-Phase-1d-38
        # behaviour byte-for-byte).
        smoking = _o(patient, "smoking_status", "never") or "never"
        alcohol = _o(patient, "alcohol_use", "none") or "none"
        facts.append("ctx.patient.smoking_status")
        facts.append("ctx.patient.alcohol_use")

        def _checkup_lifestyle_label(section: str, key: str) -> str:
            fallback = f"{key}(区分未定義)" if lang == "ja" else key
            return _label(section, key, lang, fallback=fallback)

        smoking_disp = _checkup_lifestyle_label("checkup_smoking_status", smoking)
        alcohol_disp = _checkup_lifestyle_label("checkup_alcohol_use", alcohol)

        # Assessment: follow-up required when chronic conditions are present
        needs_followup = len(chronic) > 0
        assessment = t(
            "checkup_questionnaire.assessment_followup_needed"
            if needs_followup
            else "checkup_questionnaire.assessment_no_followup",
            lang,
        )
        text = t(
            "checkup_questionnaire.full_line",
            lang,
            history=history_text,
            meds=med_text,
            smoking=smoking_disp,
            alcohol=alcohol_disp,
            assessment=assessment,
        )
        return text, facts

    def _build_hospital_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build hospital_course template seed.

        v6 blocker fix (2026-08-16): v5 returned a single hardcoded
        sentence ("入院 N 日間の治療を経て経過良好。症状は改善し退院となった。"),
        producing 11/11 identical outputs across a p=100 run because
        the LLM had a bland seed AND no factual anchor from context.
        This version enumerates the concrete facts (complications,
        procedures, key med classes) so both the template fallback and
        the LLM prompt see per-patient specificity. The LLM still
        composes the final prose.
        """
        facts: list[str] = []
        lang = ctx.target_lang

        los = ctx.los_days or 1
        parts: list[str] = []

        # Sentence 1: header (LOS + primary reason if present).
        # v7 (2026-08-16 pm): prefer localized fields; skip when JP
        # data only carries the English string ("Dyspnea on exertion,
        # orthopnea, lower extremity edema" leaked into JP discharge
        # summaries in v8). LLM enrichment fills in the reason when
        # the strategy dispatches through it.
        primary_reason = None
        if ctx.encounter is not None:
            # Try the localized ``primary_diagnosis_<lang>`` /
            # ``chief_complaint_<lang>`` slots first; fall back to the
            # base slots. For lang=en both localized slots are typically
            # absent so lookup drops to the base fields on its own.
            primary_reason = _o(ctx.encounter, f"primary_diagnosis_{lang}", None) or _o(
                ctx.encounter, f"chief_complaint_{lang}", None
            )
            if not primary_reason:
                primary_reason = _o(ctx.encounter, "primary_diagnosis", None) or _o(
                    ctx.encounter, "chief_complaint", None
                )
        if primary_reason:
            parts.append(t("hospital_course.los_head_with_reason", lang, los=los, reason=str(primary_reason)[:80]))
        else:
            parts.append(t("hospital_course.los_head", lang, los=los))

        # Sentence 2: complications (blocker 1 — MUST be surfaced)
        # Issue #848: when a working_diagnoses entry carries an
        # onset_day, prefer the "入院第N日発症" / "developed on hospital
        # day N" rendering — the intra-admission timing is the clinical
        # signal that separates a new-disease event (MI on day 30) from a
        # protocol-standard complication of the primary disease (AKI in
        # sepsis). Falls back to the plain "経過中の合併症" phrasing when
        # no onset day is known (legacy complications_occurred entries).
        comps = list(getattr(ctx, "complications_occurred", []) or [])
        wds = list(getattr(ctx, "working_diagnoses", []) or [])
        wd_by_disease = {str(wd.get("disease_id", "")): wd for wd in wds if isinstance(wd, dict)}
        if comps:
            facts.append("ctx.complications_occurred")
            phrases: list[str] = []
            for c in comps[:6]:
                cid = str(c)
                # Phase 1c-2 (2026-09-22): localize the complication token
                # to JA/EN; unmapped values fall back to a humanised
                # ("_"-stripped) form so novel complications still surface.
                label = _localize_complication(cid, lang)
                wd = wd_by_disease.get(cid)
                onset_day = wd.get("onset_day") if wd else None
                if onset_day is not None and int(onset_day) > 0:
                    phrases.append(t("hospital_course.complication_with_onset", lang, day=int(onset_day), label=label))
                else:
                    phrases.append(label)
            if wds:
                facts.append("ctx.working_diagnoses")
            sep = t("list_sep.serial", lang)
            parts.append(t("hospital_course.complications_line", lang, list=sep.join(phrases)))

        # Sentence 3: key procedures performed
        proc_names: list[str] = []
        seen: set[str] = set()
        for pr in ctx.procedures or []:
            nm = _o(pr, "procedure_name", None) or _o(pr, "name", None) or _o(pr, "display_name", None)
            if not nm:
                continue
            if nm in seen:
                continue
            seen.add(nm)
            proc_names.append(str(nm))
            if len(proc_names) >= 6:
                break
        if proc_names:
            facts.append("ctx.procedures")
            sep = t("list_sep.serial", lang)
            parts.append(t("hospital_course.procedures_line", lang, list=sep.join(proc_names)))

        # v7 (2026-08-16 pm): closer removed. v6 emitted
        # "治療経過は臨床経過（アーキタイプ）に沿って推移した。" in
        # every JP discharge_summary because the JP-only
        # llm_enabled_sections_jp bug (see DocumentTypeSpec) dropped
        # hospital_course from LLM replacement — so the template seed
        # became the final output and the internal "アーキタイプ" token
        # leaked to every one of 11 patients. Both the union-semantics
        # fix in DocumentTypeSpec and this closer removal are needed.
        facts.append("ctx.los_days")
        return " ".join(parts), facts

    def _build_discharge_diagnoses(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build discharge_diagnoses from ctx.diagnoses.

        When ``ctx`` is provided ctx.diagnoses is now wired (clinical_diagnosis), so
        this section resolves display text at render time via
        ``clinosim.codes.lookup`` (CIF stores codes only; a bare
        "I63.9" in a JP narrative fails the JP language gate). Format:
        ``<display>（<code>）`` (ja) / ``<display> (<code>)`` (en); when the
        code has no authoritative entry, ``lookup`` returns the code itself
        and the section emits the code alone.
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang

        diagnoses = ctx.diagnoses or []
        if not diagnoses:
            # Fall back to chief complaint
            cc_text, _ = self._build_chief_complaint(ctx)
            return cc_text, []

        facts.append("ctx.diagnoses")
        parts = []
        for dx in diagnoses:
            code = _o(dx, "discharge_diagnosis_code", "") or _o(dx, "admission_diagnosis_code", "")
            if not code:
                continue
            system = (
                _o(dx, "discharge_diagnosis_system", "")
                or _o(dx, "admission_diagnosis_system", "")
                or system_key_for("diagnosis", ctx.locale.upper())
            )
            display = code_lookup(system, code, ctx.target_lang)
            if display and display != code:
                parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=code))
            else:
                parts.append(code)

        if parts:
            return "; ".join(parts), facts

        # No codes — fall back
        cc_text, _ = self._build_chief_complaint(ctx)
        return cc_text, []

    def _build_discharge_medications(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build discharge_medications from ctx.discharge_medications (rx only).

        adv-1 I-1: reads ONLY the normalized discharge_prescription items —
        never ctx.medications (MAR), whose in-hospital entries (ICU drips,
        protocol-prefixed orders) previously leaked into this section.
        Protocol prefixes ("DVT_prophylaxis:", "antipyretic:", ...) are
        stripped via the shared normalization helper (same normalization as the FHIR
        medication builders).
        """
        facts: list[str] = []
        lang = ctx.target_lang
        none_text = t("section_none.discharge_medications", lang)

        meds = getattr(ctx, "discharge_medications", None) or []
        if not meds:
            return none_text, facts

        facts.append("ctx.discharge_medications")
        seen: set[str] = set()
        lines: list[str] = []
        for med in meds:
            drug = _o(med, "drug_name", "") or ""
            drug, _protocol_category = strip_protocol_prefix(drug)
            if not drug:
                continue
            # v7 (2026-08-16 pm): dedup by case-insensitive drug name
            # (kept combo vs mono distinct — "Amoxicillin/Clavulanate"
            # and "Amoxicillin" are pharmacologically different, so
            # collapsing them would be data loss). Fixes only the
            # exact-duplicate variant seen in POP-000075 v8 output
            # ("Amoxicillin" listed twice with identical dose+route+freq).
            norm_key = str(drug).lower().strip()
            if norm_key in seen:
                continue
            seen.add(norm_key)
            # v6 blocker fix (2026-08-16): PrescriptionRecord.items carry
            # dose / route / frequency / days_supply. v5 emitted names
            # only, violating the LLM prompt's REQUIRED specificity spec
            # and leaving discharge_medications indistinguishable across
            # patients. Format: "<drug> <dose> <route> <freq> x<days>d".
            # v9 (2026-08-17 evening): apply JA katakana localization to
            # drug_name. v11 review found 9/11 discharge_summary carried
            # English drug tokens ("Furosemide 20mg PO daily") because
            # this builder never routed through _localize_drug_name.
            display = str(drug)
            # Phase 1c-6 (Category F, 2026-09-23): route dose / route /
            # frequency fields through ``_localize_dosage_terms`` on JA
            # output so 「20mg PO daily」 → 「20mg 経口 1日1回」. Pre-
            # fix, `_localize_drug_name` translated dosage terms only
            # when they appeared inside the drug_name string; the
            # separate ``dose`` / ``route`` / ``frequency`` fields on
            # ``PrescriptionRecord.items`` were concatenated raw, so
            # discharge_medications leaked ``PO`` / ``daily`` / ``TID``
            # / ``q4h`` verbatim into JA output (~545 leaks in the
            # p=10000 audit for `daily` alone).
            if lang == "ja":
                # JA-locale drug-name katakana + dosage-term localization
                # (locale-specific data pipeline).
                from clinosim.modules.output.fhir_r4.lib.localization import (
                    _localize_dosage_terms,
                    _localize_drug_name,
                )

                display = _localize_drug_name(display, "JP")

                # Phase 1d-3 (2026-09-23): pass ctx.target_lang through so
                # this branch stays lang-agnostic when a future locale
                # (fr / zh) adds its own YAML slots to med_terms.yaml.
                _term_lang = lang

                def _ja_term(v: str) -> str:
                    try:
                        return _localize_dosage_terms(v, _term_lang)
                    except Exception:  # noqa: BLE001
                        return v
            else:

                def _ja_term(v: str) -> str:
                    return v

            dose = _o(med, "dose", "") or ""
            route = _o(med, "route", "") or ""
            freq = _o(med, "frequency", "") or ""
            days = _o(med, "days_supply", None)
            bits: list[str] = [display]
            if dose:
                bits.append(_ja_term(str(dose)))
            if route:
                bits.append(_ja_term(str(route)))
            if freq:
                bits.append(_ja_term(str(freq)))
            if days:
                bits.append(t("prescription.days_supply_suffix", lang, days=days))
            lines.append(" ".join(bits))

        if lines:
            return "; ".join(lines), facts
        return none_text, facts

    def _build_discharge_instructions(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build discharge_instructions using disease-specific override + baseline merge."""
        facts: list[str] = []
        lang = ctx.target_lang

        instructions = self._resolve_discharge_instructions(ctx)
        facts.append("discharge_instructions.baseline")

        disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
        if disease_id:
            facts.append(f"discharge_instructions.disease_specific.{disease_id}")

        parts = []
        for key, bi_lang in instructions.items():
            text = bi_lang.get(lang) or bi_lang.get("ja") or bi_lang.get("en") or ""
            if text:
                parts.append(text)

        return " ".join(parts), facts

    def _build_follow_up(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build follow_up section from discharge instructions follow_up entry."""
        lang = ctx.target_lang

        instructions = self._resolve_discharge_instructions(ctx)
        follow_up_entry = instructions.get("follow_up") or {}
        text = follow_up_entry.get(lang) or follow_up_entry.get("ja") or follow_up_entry.get("en") or ""
        if not text:
            text = "外来フォローアップ予定" if lang == "ja" else "Follow up with outpatient provider"
        return text, ["discharge_instructions.follow_up"]

    # ─────────────────────────────────────────────────────────────────
    # Free-text renderers (NURSING_SHIFT_NOTE, ED_TRIAGE_NOTE)
    # ─────────────────────────────────────────────────────────────────

    def _render_nursing_shift_note_text(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build NURSING_SHIFT_NOTE as free text.

        Includes: day/shift info, primary_nurse_id (graceful when absent),
        and a generic per-shift status summary.

        When ``ctx.shift`` carries a neutral shift key
        ("night"/"day"/"evening" from a daily_3shift stub), the localized
        shift label (en: night/day/evening, ja: 深夜/日勤/準夜) is resolved
        here at render time and included in the header, so the 3 per-day
        notes differ at least by the shift label. ``ctx.shift == ""``
        (legacy callers) keeps the previous header unchanged.

        EN locale note: nursing shift data is JP-primary in stage 2. EN locale
        produces an English summary using the same CIF fields.
        """
        facts: list[str] = []
        lang = ctx.target_lang

        day_num = ctx.day_index + 1  # 1-based display
        los = ctx.los_days or 1

        shift_key = ctx.shift or ""
        shift_label = ""
        if shift_key:
            facts.append("ctx.shift")
            # Unknown key → render the neutral key itself (never drop silently).
            shift_label = _label("shift_labels", shift_key, lang, fallback=shift_key)

        nurse_id = _o(ctx.encounter, "primary_nurse_id", "") or ""
        nurse_line = ""
        if nurse_id:
            facts.append("encounter.primary_nurse_id")
            nurse_disp = _resolve_staff_name(nurse_id, ctx.roster_map, lang)
            nurse_line = t("nursing_shift.nurse_line", lang, name=nurse_disp)

        # v9 (2026-08-17) density fix: replace 「バイタルサイン安定 / 特記事項なし」
        # boilerplate with CIF-sourced per-shift narrative (today's vitals,
        # supplemental O2 flag, active meds, ADL trend, risk flags).
        picks = _filter_vitals_for_day(ctx.vitals, ctx.day_index, ctx.encounter)
        v = picks[0] if picks else None

        status_bits: list[str] = []
        if v is not None:
            temp = _o(v, "temperature_celsius", None)
            spo2 = _o(v, "spo2", None)
            sbp = _o(v, "systolic_bp", None)
            dbp = _o(v, "diastolic_bp", None)
            hr = _o(v, "heart_rate", None)
            on_o2 = _o(v, "on_supplemental_oxygen", False)
            device = _o(v, "oxygen_delivery_device", None)
            flow = _o(v, "oxygen_flow_rate_lpm", None)
            vital_line_parts: list[str] = []
            if sbp and dbp:
                vital_line_parts.append(f"BP {int(sbp)}/{int(dbp)}")
            if hr:
                vital_line_parts.append(f"HR {int(hr)}")
            if spo2:
                vital_line_parts.append(f"SpO2 {float(spo2):.0f}%")
            if temp:
                vital_line_parts.append(f"T {float(temp):.1f}°C")
            if vital_line_parts:
                status_bits.append(", ".join(vital_line_parts))
            if on_o2:
                # JA-locale drug/device-name katakana lookup is a
                # locale-specific data pipeline; other languages pass
                # the raw device token through.
                if lang == "ja":
                    from clinosim.modules.document.narrative.replacement_strategy import (
                        _localize_oxygen_device_ja,
                    )

                    device_disp = _localize_oxygen_device_ja(str(device or ""))
                else:
                    device_disp = str(device or "")
                if device and flow is not None:
                    try:
                        flow_str = f"{float(flow):g}"
                        status_bits.append(
                            t("nursing_shift.o2_device_with_flow", lang, device=device_disp, flow=flow_str)
                        )
                    except (TypeError, ValueError):
                        status_bits.append(t("oxygen.device_line", lang, device=device_disp))
                else:
                    status_bits.append(t("nursing.supplemental_o2", lang))
            facts.append("ctx.vitals.today")

        # Today's meds (limit 3 for shift-note brevity)
        med_names: list[str] = []
        seen: set[str] = set()
        for m in (ctx.medications or [])[:12]:
            d = _o(m, "day", None)
            if d is not None and d != ctx.day_index:
                continue
            n = _o(m, "drug_name", None) or _o(m, "medication", None)
            if not n or n in seen:
                continue
            seen.add(n)
            if lang == "ja":
                # JA-locale drug-name katakana lookup (locale-specific
                # data pipeline, same rationale as _compose_ap_plan_from_state).
                from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

                med_names.append(_localize_drug_name(str(n), "JP"))
            else:
                med_names.append(str(n))
            if len(med_names) >= 3:
                break

        # Risk flag today
        risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
        risk_bit = ""
        if risks:
            latest = risks[-1]
            fall = _o(latest, "fall_risk_level", None)
            if fall and str(fall).lower() in ("high", "moderate"):
                # Localize the risk-level enum via the shared morse_band
                # phrase catalog (low/moderate/high → 低リスク/中等度リスク/
                # 高リスク on JA output). Unknown values fall back to the
                # raw token so novel risk levels still surface.
                fall_disp = t(f"morse_band.{str(fall).lower()}", lang)
                if fall_disp == f"morse_band.{str(fall).lower()}":
                    fall_disp = str(fall)
                risk_bit = t("nursing_shift.fall_risk_line", lang, level=fall_disp)
                facts.append("ctx.nursing_risk_assessments[-1]")

        title = (
            t("nursing_shift.title_with_shift", lang, shift=shift_label)
            if shift_label
            else t("nursing_shift.title_no_shift", lang)
        )
        header = t("nursing_shift.header_line", lang, title=title, day=day_num, los=los)
        # status_bits separator differs by locale: JA uses 「、」, EN uses
        # "; " — matched by list_sep.semicolon. Trailing period picked
        # via list_sep.period (「。」 / ".").
        if status_bits:
            status_body = t("list_sep.semicolon", lang).join(status_bits) + t("list_sep.period", lang)
        else:
            status_body = t("nursing_shift.no_vital_record", lang)
        status = t("nursing_shift.patient_status_head", lang) + status_body
        if med_names:
            meds_line = (
                t("nursing_shift.meds_head", lang)
                + t("list_sep.serial", lang).join(med_names)
                + t("list_sep.period", lang)
            )
        else:
            meds_line = ""
        observations = risk_bit or t("nursing_shift.observations_default", lang)

        lines = [header]
        if nurse_line:
            lines.append(nurse_line)
        lines.append(status)
        if meds_line:
            lines.append(meds_line)
            facts.append("ctx.medications.today")
        lines.append(observations)
        raw_text = "\n".join(lines)

        facts.append("ctx.day_index")
        facts.append("ctx.los_days")

        metadata: dict[str, Any] = {
            "generator": "template",
            "lang": lang,
            "day_index": ctx.day_index,
        }
        if shift_key:
            metadata["shift"] = shift_key

        return NarrativeOutput(
            raw_text=raw_text,
            metadata=metadata,
            facts_used=facts,
        )

    def _render_ed_triage_note_text(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build ED_TRIAGE_NOTE as free text from encounter.triage_data.

        Reads TriageData fields (level, level_system, arrival_mode,
        chief_complaint_summary). Gracefully falls back to a generic phrase
        when triage_data is None.

        EN locale note: arrival_mode and chief_complaint_summary from CIF are
        used directly; level_system labels (ESI/JTAS) are system codes (no
        translation needed). EN output uses the same field values but with
        English grammatical framing.
        """
        facts: list[str] = []
        lang = ctx.target_lang

        triage = _o(ctx.encounter, "triage_data", None)

        if triage is None:
            raw_text = t("fallback.triage_fallback", lang)
            return NarrativeOutput(
                raw_text=raw_text,
                metadata={"generator": "template", "lang": lang},
                facts_used=facts,
            )

        facts.append("encounter.triage_data")

        level = _o(triage, "level", "") or ""
        level_system = _o(triage, "level_system", "") or ""
        arrival_mode = _o(triage, "arrival_mode", "") or ""
        cc_summary = _o(triage, "chief_complaint_summary", "") or ""
        arrival_display = _label("arrival_mode", arrival_mode, lang, fallback=arrival_mode)

        level_line = (
            t("triage_note.level_line_with_data", lang, system=level_system, level=level)
            if level_system and level
            else t("triage_note.level_line_none", lang)
        )
        arrival_line = (
            t("triage_note.arrival_line", lang, mode=arrival_display)
            if arrival_display
            else t("triage_note.arrival_line_none", lang)
        )
        cc_line = t("triage_note.cc_line", lang, cc=cc_summary) if cc_summary else t("triage_note.cc_line_none", lang)
        raw_text = "\n".join([level_line, arrival_line, cc_line])

        return NarrativeOutput(
            raw_text=raw_text,
            metadata={"generator": "template", "lang": lang},
            facts_used=facts,
        )

    # ─────────────────────────────────────────────────────────────────
    # ADMISSION_NURSING_ASSESSMENT section builders
    # ─────────────────────────────────────────────────────────────────

    def _build_nursing_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build nursing_history from CIF (primary nurse + admission reason
        + chronic conditions + allergy summary). v9 density fix — v8
        emitted only a nurse id + generic fallback (~30 chars)."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        parts: list[str] = []
        nurse_id = _o(ctx.encounter, "primary_nurse_id", "") or ""
        if nurse_id:
            facts.append("encounter.primary_nurse_id")
            nurse_disp = _resolve_staff_name(nurse_id, ctx.roster_map, lang)
            parts.append(t("admission_status.assigned_nurse", lang, name=nurse_disp))
        cc = ""
        if ctx.encounter is not None:
            cc = _o(ctx.encounter, f"chief_complaint_{lang}", None) or _o(ctx.encounter, "chief_complaint", None) or ""
        if cc:
            parts.append(t("admission_status.admission_reason", lang, cc=cc))
        # Chronic summary — Issue #1333: route CIF base code through
        # map_diagnosis_code so display matches the FHIR emit-target.
        from clinosim.codes import lookup as _code_lookup
        from clinosim.modules.output.fhir_r4.lib.common import (
            map_diagnosis_code as _map_diagnosis_code,
        )

        country = "JP" if ctx.locale.lower() == "jp" else "US"
        conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
        labels: list[str] = []
        for c in conds[:4]:
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            emit_code = _map_diagnosis_code(code, country) or code
            key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
            labels.append(_code_lookup(key, emit_code, ctx.target_lang) or emit_code)
        if labels:
            parts.append(
                t("pmh.header_prefix", lang)
                + ("、".join(labels) if is_ja else ", ".join(labels))
                + t("list_sep.period", lang)
            )
        # Allergy
        allergies = ctx.allergies or []
        if allergies:
            first_allergen = _o(allergies[0], "substance", None) or _o(allergies[0], "name", None) or ""
            if first_allergen:
                parts.append(t("admission_status.allergy_first", lang, allergen=first_allergen))
        if len(parts) <= 1:
            parts.append(t("fallback.nursing_history_fallback", lang))
        facts.extend(["ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"])
        return "".join(parts), facts

    def _build_adl_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build adl_assessment from CIF adl_assessments (Barthel Index).
        v9 density fix — v8 emitted 12-char "ADL：自立（問題なし）"."""
        facts: list[str] = []
        lang = ctx.target_lang
        adls = list(getattr(ctx, "adl_assessments", None) or [])
        if not adls:
            return (t("fallback.adl_fallback", lang)), facts
        latest = adls[-1]
        barthel = _o(latest, "barthel_score", None)
        if barthel is None:
            return (t("fallback.adl_fallback", lang)), facts
        facts.append("ctx.adl_assessments[-1]")
        # Barthel band interpretation (standard)
        if barthel >= 91:
            band = t("barthel_band.independent", lang)
        elif barthel >= 61:
            band = t("barthel_band.minimal_assist", lang)
        elif barthel >= 41:
            band = t("barthel_band.moderate_assist", lang)
        elif barthel >= 21:
            band = t("barthel_band.severe_dependence", lang)
        else:
            band = t("barthel_band.total_care", lang)
        detail_parts: list[str] = []
        for k in ("feeding", "bathing", "mobility", "toilet_use"):
            v = _o(latest, k, None)
            if v is not None:
                label = _label("adl_detail_key", k, lang, fallback=k)
                detail_parts.append(t("adl_detail.item", lang, label=label, score=v))
        detail = t("adl_detail.wrap", lang, items=t("list_sep.serial", lang).join(detail_parts)) if detail_parts else ""
        return f"Barthel Index {barthel}/100 → {band}{detail}", facts

    def _build_risk_assessments(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build risk_assessments from CIF (Braden + Morse). v9 density
        fix — v8 emitted 12-char placeholder."""
        facts: list[str] = []
        lang = ctx.target_lang
        risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
        if not risks:
            return (t("fallback.risk_fallback", lang)), facts
        latest = risks[-1]
        braden = _o(latest, "braden_total", None)
        morse = _o(latest, "morse_total", None)
        fall_lvl = _o(latest, "fall_risk_level", None)
        facts.append("ctx.nursing_risk_assessments[-1]")
        parts: list[str] = []
        if braden is not None:
            # Braden risk bands: >18 low / 15-18 mild / 13-14 moderate / 10-12 high / ≤9 severe
            if braden >= 19:
                bband = t("morse_band.low", lang)
            elif braden >= 15:
                bband = t("morse_band.mild", lang)
            elif braden >= 13:
                bband = t("morse_band.moderate", lang)
            elif braden >= 10:
                bband = t("morse_band.high", lang)
            else:
                bband = t("morse_band.severe", lang)
            parts.append(t("risk.braden_line", lang, braden=braden, band=bband))
        if morse is not None:
            lvl = fall_lvl or ("low" if morse < 25 else "moderate" if morse < 45 else "high")
            # Localize the fall-risk enum via the shared morse_band phrase
            # catalog so JA emits 「低リスク / 中等度リスク / 高リスク」
            # instead of the raw EN token. Unknown values fall back to
            # the raw string.
            lvl_key = str(lvl).lower()
            lvl_disp = t(f"morse_band.{lvl_key}", lang)
            if lvl_disp == f"morse_band.{lvl_key}":
                lvl_disp = str(lvl)
            parts.append(t("fall_risk.morse_score_line", lang, morse=morse, level=lvl_disp))
        if not parts:
            return (t("fallback.risk_fallback", lang)), facts
        return t("list_sep.period", lang).join(parts) + t("list_sep.period", lang), facts

    def _build_nursing_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build nursing_diagnosis from CIF chronic conditions + acute
        admission reason + risk data.

        Session-104 Tier 2: acute-disease axis (from
        ``ctx.disease_protocol.disease_id``) is consulted BEFORE the
        chronic-ICD10 axis via ``_lookup_nursing_content``. Both axes
        are backed by ``nursing_content.yaml`` — the 6 chronic
        prefixes are carried over verbatim, so byte-diff on encounters
        without a pilot acute match is zero.

        Risk-derived NDx (fall / pressure ulcer) are appended after
        the YAML-driven items — same behavior as pre-session-104.
        """
        lang = ctx.target_lang
        dx_labels, facts = _lookup_nursing_content(ctx, "nursing_diagnoses", lang, cap=5)

        # Risk-derived NDx (unchanged from pre-session-104 semantics —
        # appended on top of the YAML-driven items, past the cap).
        risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
        if risks:
            latest = risks[-1]
            fall = _o(latest, "fall_risk_level", None)
            if fall and str(fall).lower() in ("high", "moderate"):
                fr = t("fall_risk.short_label", lang)
                if fr not in dx_labels:
                    dx_labels.append(fr)
                    if "ctx.nursing_risk_assessments" not in facts:
                        facts.append("ctx.nursing_risk_assessments")
            braden = _o(latest, "braden_total", None)
            if braden is not None and braden <= 14:
                pu = t("nursing.pu_risk_label", lang)
                if pu not in dx_labels:
                    dx_labels.append(pu)
                    if "ctx.nursing_risk_assessments" not in facts:
                        facts.append("ctx.nursing_risk_assessments")

        if dx_labels:
            head = t("nursing.diagnoses_head", lang)
            sep = t("list_sep.serial", lang)
            return head + sep.join(dx_labels) + t("list_sep.period", lang), facts
        return (t("fallback.nursing_dx_fallback", lang)), facts

    def _build_care_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build care_plan from CIF-derived nursing diagnoses (mirror of
        _build_nursing_diagnosis interventions).

        Session-104 Tier 2: acute-disease axis (from
        ``ctx.disease_protocol.disease_id``) is consulted BEFORE the
        chronic-ICD10 axis via ``_lookup_nursing_content``. The 6
        chronic prefixes carry over verbatim, so byte-diff on
        non-pilot encounters is zero. Risk-driven actions (fall / PU
        precautions) are appended after the YAML-driven items — same
        as pre-session-104.
        """
        lang = ctx.target_lang
        actions, facts = _lookup_nursing_content(ctx, "care_plan", lang, cap=4)

        # Risk-driven actions. Semantic-prefix dedup (session-104): the
        # acute YAML entry for cerebral_infarction (and future pilots)
        # already emits a "fall precautions" line — appending the
        # risk-derived version would double-cover. Skip whenever ANY
        # existing action already opens with the fall-precaution /
        # PU-prevention prefix (locale-specific).
        risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
        _fall_prefix = t("nursing.fall_precautions", lang)
        _pu_prefix = t("nursing.pu_prevention", lang)
        if risks:
            latest = risks[-1]
            if str(_o(latest, "fall_risk_level", "") or "").lower() in ("high", "moderate"):
                if not any(a.startswith(_fall_prefix) for a in actions):
                    actions.append(t("nursing.fall_precautions_action", lang))
                    if "ctx.nursing_risk_assessments" not in facts:
                        facts.append("ctx.nursing_risk_assessments")
            if (_o(latest, "braden_total", 25) or 25) <= 14:
                if not any(a.startswith(_pu_prefix) for a in actions):
                    actions.append(t("nursing.pu_prevention_action", lang))
                    if "ctx.nursing_risk_assessments" not in facts:
                        facts.append("ctx.nursing_risk_assessments")

        if actions:
            head = t("nursing.care_plan_head", lang)
            sep = t("list_sep.semicolon", lang)
            return head + sep.join(actions) + t("list_sep.period", lang), facts
        return (t("fallback.care_plan_fallback", lang)), facts

    # ─────────────────────────────────────────────────────────────────
    # ADMISSION_CARE_PLAN (Phase 2) section builders (入院診療計画書, LOINC 18776-5)
    #
    # MHLW form 別紙２ (10 core fields, verified 2026-07-03 — design spec §2).
    # JP-only doc type (countries_supported=[jp]); both language branches are
    # implemented for consistency with every other builder in this file, even
    # though only target_lang="ja" is ever reached through the registry gate.
    # ─────────────────────────────────────────────────────────────────

    def _build_acp_ward_and_room(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病棟（病室）— Encounter.ward_id + bed_number."""
        facts: list[str] = []
        lang = ctx.target_lang
        ward = str(_o(ctx.encounter, "ward_id", "") or "")
        bed = str(_o(ctx.encounter, "bed_number", "") or "")
        if not ward and not bed:
            return (t("fallback.acp_ward_room_fallback", lang)), facts
        if ward:
            facts.append("encounter.ward_id")
        if bed:
            facts.append("encounter.bed_number")
        tbd = t("acp.ward_tbd", lang)
        return t("acp.ward_and_room_line", lang, ward=ward or tbd, bed=bed or tbd), facts

    def _build_acp_other_staff(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Healthcare staff names other than attending physician — mapped to
        Encounter.primary_nurse_id (shares field with CareTeam)."""
        facts: list[str] = []
        lang = ctx.target_lang
        nurse_id = str(_o(ctx.encounter, "primary_nurse_id", "") or "")
        if not nurse_id:
            return (t("fallback.acp_other_staff_fallback", lang)), facts
        facts.append("encounter.primary_nurse_id")
        nurse_disp = _resolve_staff_name(nurse_id, ctx.roster_map, lang)
        return t("acp.assigned_nurse_line", lang, name=nurse_disp), facts

    def _build_acp_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病名（他に考え得る病名）— ctx.diagnoses, admission code preferred
        (discharge dx is not yet known when this document is written at
        admission — unlike _build_discharge_diagnoses which prefers discharge)."""
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang
        diagnoses = ctx.diagnoses or []
        if not diagnoses:
            return self._build_chief_complaint(ctx)

        facts.append("ctx.diagnoses")
        parts: list[str] = []
        for dx in diagnoses:
            admission_code = _o(dx, "admission_diagnosis_code", "")
            discharge_code = _o(dx, "discharge_diagnosis_code", "")
            code = str(admission_code or discharge_code or "")
            if not code:
                continue
            system = str(
                _o(dx, "admission_diagnosis_system", "")
                or _o(dx, "discharge_diagnosis_system", "")
                or system_key_for("diagnosis", ctx.locale.upper())
            )
            display = code_lookup(system, code, ctx.target_lang)
            if display and display != code:
                parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=code))
            else:
                parts.append(code)

        if parts:
            return "; ".join(parts), facts
        return self._build_chief_complaint(ctx)

    def _build_acp_symptoms(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """症状 — reuses chief_complaint extraction (presenting symptom)."""
        return self._build_chief_complaint(ctx)

    def _build_acp_treatment_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """治療計画 — reuses assessment_and_plan extraction (admission_hp precedent)."""
        return self._build_assessment_and_plan(ctx)

    def _build_acp_test_schedule(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """検査内容及び日程 — distinct test names from ctx.lab_results.

        ctx has no separate "orders" field (only already-resulted lab_results);
        distinct test names is the best available data-driven proxy within
        NarrativeContext's existing schema (spec §3b decision)."""
        facts: list[str] = []
        lang = ctx.target_lang
        names: set[str] = set()
        for lab in ctx.lab_results or []:
            name = _o(lab, "test_name", None)
            if name:
                names.add(str(name))
        if not names:
            fallback = t("fallback.acp_test_schedule_fallback", lang)
            return fallback, facts
        facts.append("ctx.lab_results")
        joined = t("list_sep.serial", lang).join(sorted(names))
        return t("acp.test_schedule_line", lang, joined=joined), facts

    def _build_acp_surgery_schedule(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """手術内容及び日程 — ctx.procedures filtered to category_code=387713003 (surgical)."""
        facts: list[str] = []
        lang = ctx.target_lang
        surgical = [p for p in (ctx.procedures or []) if str(_o(p, "category_code", "") or "") == "387713003"]
        if not surgical:
            return (t("fallback.acp_surgery_none", lang)), facts
        facts.append("ctx.procedures")
        # Phase 1c-6 (2026-09-23): localize each procedure_type slug via
        # `_localize_proc_type` so JA emits 「手術予定：経皮的冠動脈形成術、
        # ペースメーカー移植術」 rather than 「手術予定：coronary_pci、
        # pacemaker_implant」. ~50 leaks in the JP p=10000 audit.
        types = [
            _localize_proc_type(str(_o(p, "procedure_type", "") or ""), ctx.target_lang)
            for p in surgical
            if _o(p, "procedure_type", "")
        ]
        joined = t("list_sep.serial", lang).join(types)
        return t("acp.surgery_schedule_line", lang, joined=joined), facts

    def _estimated_los_days(self, ctx: NarrativeContext) -> tuple[int, list[str]]:
        """disease_protocol.target_los[country][severity].mean → whole days,
        RNG-free (target_los is a static YAML dict, read with no sampling —
        adv-1 finding on admission_care_plan: ctx.los_days, the already-realized
        LOS, is tautologically 100% accurate and unrealistic for a document
        meant to represent an AT-ADMISSION prediction). Falls back to
        ctx.los_days only when disease_protocol is unavailable.

        Shared by _build_acp_estimated_los and _build_rp_discharge_estimate —
        extracted once rehabilitation_plan became the 2nd consumer
        (implementation-rules.md §4 canonical single-source rule)."""
        facts: list[str] = []
        los: float = 0
        proto = ctx.disease_protocol
        if proto is not None:
            # Issue #550: canonical resolver — same fallback ladder as the
            # inpatient simulator. The narrative path takes the mean rather
            # than sampling (RNG-free per this method's docstring above), and
            # falls back to the observed encounter length when the protocol
            # has no matching (country, severity) slot.
            country = "JP" if ctx.locale == "jp" else "US"
            los_cfg = target_los_config(proto, country, ctx.severity) or {}
            if "mean" in los_cfg:
                los = los_cfg["mean"]
                facts.append("disease_protocol.target_los")
        if not los:
            los = ctx.los_days or 1
            facts.append("ctx.los_days")
        return round(los), facts

    def _build_acp_estimated_los(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """推定される入院期間 — see _estimated_los_days for the shared calculation."""
        lang = ctx.target_lang
        los_days, facts = self._estimated_los_days(ctx)
        return t("acp.estimated_los_line", lang, days=los_days), facts

    def _build_acp_special_nutrition_management(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """特別な栄養管理の必要性 — MVP: always「無」(no NutritionOrder subsystem
        exists yet; TODO.md tracks the future nutrition subsystem chain)."""
        lang = ctx.target_lang
        return (t("fallback.acp_nutrition_no", lang)), []

    def _build_acp_other_plans(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """その他（看護計画・リハビリテーション等の計画）— fixed cross-reference
        phrase. NarrativeContext does not carry other stub types' rendered
        content at this call site (each spec walked independently), so this
        section cannot dynamically pull admission_nursing_assessment content
        without a larger architecture change (out of scope, see plan)."""
        lang = ctx.target_lang
        return (t("fallback.acp_other_plans", lang)), []

    # ─────────────────────────────────────────────────────────────────
    # NUTRITION_CARE_PLAN (Phase 2) section builders (栄養管理計画書, LOINC 80791-7)
    #
    # MHLW form 別紙23 (verified 2026-07-03 — design spec §2). JP-only,
    # LOS>7-gated. Only 3 of 12 sections are data-driven (ward_and_physician /
    # nutrition_risk / nutrition_supply); the rest are MVP fixed fallbacks —
    # no dietitian role or real nutrition-assessment data source exists yet
    # (TODO.md tracks this). Both language branches implemented for
    # consistency with every other builder in this file, though this doc
    # type is JP-only in production.
    # ─────────────────────────────────────────────────────────────────

    def _build_ncp_ward_and_physician(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病棟／担当医師名／入院日 — same Encounter fields as admission_care_plan."""
        facts: list[str] = []
        lang = ctx.target_lang
        ward = str(_o(ctx.encounter, "ward_id", "") or "")
        physician = str(_o(ctx.encounter, "attending_physician_id", "") or "")
        if ward:
            facts.append("encounter.ward_id")
        if physician:
            facts.append("encounter.attending_physician_id")
        ward_disp = ward or t("common.tbd", lang)
        physician_disp = _resolve_staff_name(physician, ctx.roster_map, lang) if physician else t("common.tbd", lang)
        return t("ncp.ward_and_physician_line", lang, ward=ward_disp, physician=physician_disp), facts

    def _build_ncp_dietitian(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """担当管理栄養士名 — MVP: no dietitian staff role exists yet."""
        lang = ctx.target_lang
        return (t("fallback.ncp_dietitian_fallback", lang)), []

    def _build_ncp_nutrition_risk(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """入院時栄養状態に関するリスク — BMI 3-tier threshold (coarse screening
        proxy, not a validated instrument like GLIM/MUST — design spec §4)."""
        facts: list[str] = []
        lang = ctx.target_lang
        bmi = _o(ctx.patient, "bmi", None)
        if bmi is None:
            fallback = t("section_none.nutrition_risk_no_data", lang)
            return fallback, facts
        facts.append("patient.bmi")
        bmi_r = round(float(bmi), 1)
        if bmi_r < NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE:
            return t("nutrition.malnutrition_high_line", lang, bmi=bmi_r), facts
        if bmi_r > NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE:
            return t("nutrition.overnutrition_line", lang, bmi=bmi_r), facts
        return t("ncp.nutrition_low_risk_line", lang, bmi=bmi_r), facts

    def _build_ncp_nutrition_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養状態の評価と課題 — v9 density fix: compose from BMI +
        chronic disease + ADL (Barthel) rather than MVP placeholder."""
        facts: list[str] = []
        lang = ctx.target_lang
        patient = ctx.patient
        if patient is None:
            return (t("fallback.ncp_assessment_fallback", lang)), facts
        parts: list[str] = []
        weight = _o(patient, "weight_kg", None)
        height = _o(patient, "height_cm", None)
        if weight and height:
            try:
                bmi = float(weight) / ((float(height) / 100) ** 2)
                facts.append("patient.weight_kg+height_cm")
                if bmi < 18.5:
                    band = t("bmi_band.underweight", lang)
                elif bmi < 25:
                    band = t("bmi_band.normal", lang)
                elif bmi < 30:
                    band = t("bmi_band.overweight", lang)
                else:
                    band = t("bmi_band.obese", lang)
                parts.append(f"BMI {bmi:.1f} ({band})")
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        # Nutrition-relevant chronic diseases
        conds = _o(patient, "chronic_conditions", []) or []
        codes = {(_o(c, "code", "") or (c if isinstance(c, str) else "")).split(".")[0].upper() for c in conds}
        risk_conds = []
        risk_map = {
            "E11": t("diet_plan.diabetic", lang),
            "N18": t("diet_plan.ckd_protein_restriction", lang),
            "I50": t("diet_plan.hf_fluid_salt_restriction", lang),
            "K70": t("diet_plan.hepatic", lang),
        }
        for k, label in risk_map.items():
            if k in codes:
                risk_conds.append(label)
        if risk_conds:
            facts.append("ctx.patient.chronic_conditions")
            parts.append(t("nutrition_special.prefix", lang) + t("list_sep.serial", lang).join(risk_conds))
        # ADL
        adls = list(getattr(ctx, "adl_assessments", None) or [])
        if adls:
            b = _o(adls[-1], "barthel_score", None)
            if b is not None and b < 60:
                parts.append(t("nutrition.feeding_assist", lang))
                facts.append("ctx.adl_assessments[-1]")
        if not parts:
            return (t("fallback.ncp_assessment_fallback", lang)), facts
        head = t("nutrition.assessment_head", lang)
        return head + t("list_sep.semicolon", lang).join(parts) + t("list_sep.period", lang), facts

    def _build_ncp_nutrition_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養管理計画 目標 — MVP fixed fallback."""
        lang = ctx.target_lang
        return (t("fallback.ncp_goals_fallback", lang)), []

    def _build_ncp_nutrition_supply(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養補給に関する事項 (エネルギー/たんぱく質/補給方法) — standard
        initial-planning estimation formulas from PatientProfile.weight_kg
        (25-30 kcal/kg/day energy midpoint, 1.0-1.2 g/kg/day protein
        midpoint — design spec §3c). Route fixed to 経口 (oral) MVP default."""
        facts: list[str] = []
        lang = ctx.target_lang
        weight = _o(ctx.patient, "weight_kg", None)
        if weight is None:
            fallback = t("section_none.nutrition_supply_no_data", lang)
            return fallback, facts
        facts.append("patient.weight_kg")
        energy = round(float(weight) * NUTRITION_ENERGY_KCAL_PER_KG_MIDPOINT)
        protein = round(float(weight) * NUTRITION_PROTEIN_G_PER_KG_MIDPOINT, 1)
        return t("ncp.nutrition_supply_line", lang, energy=energy, protein=protein), facts

    def _build_ncp_dysphagia_diet(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """嚥下調整食の必要性 — MVP fixed 「なし」."""
        lang = ctx.target_lang
        return (t("fallback.ncp_dysphagia_none", lang)), []

    def _build_ncp_dietary_content(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """食事内容 — MVP fixed fallback."""
        lang = ctx.target_lang
        return (t("fallback.ncp_dietary_content_fallback", lang)), []

    def _build_ncp_nutrition_counseling(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養食事相談に関する事項 — MVP fixed fallback (collapses the 3 MHLW
        sub-items — admission/consult/discharge instruction — into one
        section; no per-item data source exists, design spec §2 row 7)."""
        lang = ctx.target_lang
        return (t("fallback.ncp_counseling_fallback", lang)), []

    def _build_ncp_other_issues(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """その他栄養管理上解決すべき課題 — v9 density fix: derive from
        allergies + high-risk chronic combo. Falls back to placeholder
        when CIF has no relevant markers."""
        facts: list[str] = []
        lang = ctx.target_lang
        parts: list[str] = []
        # Food allergies (subset)
        for a in (ctx.allergies or [])[:3]:
            substance = _o(a, "substance", None) or _o(a, "name", None) or ""
            if substance:
                parts.append(t("allergy.avoidance_line", lang, substance=substance))
        if parts:
            facts.append("ctx.allergies")
        # Combined chronic (DM+CKD) — polyrestrictive diet
        conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
        codes = {(_o(c, "code", "") or (c if isinstance(c, str) else "")).split(".")[0].upper() for c in conds}
        if "E11" in codes and "N18" in codes:
            parts.append(t("nutrition.dm_ckd_combined", lang))
            facts.append("ctx.patient.chronic_conditions")
        if not parts:
            return (t("fallback.ncp_other_issues_fallback", lang)), facts
        return t("nutrition.other_head", lang) + t("list_sep.semicolon", lang).join(parts) + t(
            "list_sep.period", lang
        ), facts

    def _build_ncp_reassessment_timing(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養状態の再評価の時期 — MVP fixed fallback."""
        lang = ctx.target_lang
        return (t("fallback.ncp_reassessment_fallback", lang)), []

    def _build_ncp_discharge_evaluation(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """退院時及び終了時の総合的評価 — genuinely unknowable at plan-creation
        time; this system has no mechanism to revise a Stage-1 stub at a
        later encounter phase for this doc type (design spec §2 row 10)."""
        lang = ctx.target_lang
        return (t("fallback.ncp_discharge_eval_fallback", lang)), []

    # ─────────────────────────────────────────────────────────────────
    # REHABILITATION_PLAN sections (LOINC 34823-5)
    # ─────────────────────────────────────────────────────────────────

    def _build_rp_patient_and_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """患者・原因疾患 — reuses admission_care_plan's diagnosis extraction
        (same ctx.diagnoses source, design spec §3e)."""
        return self._build_acp_diagnosis(ctx)

    def _build_rp_rehab_team(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハ担当医・PT・OT・ST — therapy_type set from ctx.rehab_sessions.
        generate_rehab_sessions (modules/procedure/engine.py) currently only
        produces "PT" — this renders whatever therapy types are actually
        present rather than implying multi-disciplinary coverage that doesn't
        exist (design spec §3e / §4 out-of-scope note)."""
        facts: list[str] = []
        lang = ctx.target_lang
        therapy_types = sorted(
            {str(_o(s, "therapy_type", "") or "") for s in (ctx.rehab_sessions or []) if _o(s, "therapy_type", "")}
        )
        if not therapy_types:
            return (t("fallback.rp_team_fallback", lang)), facts
        facts.append("ctx.rehab_sessions")
        joined = t("list_sep.serial", lang).join(
            _label("rp_therapy_type", tt, lang, fallback=tt) for tt in therapy_types
        )
        therapist_note = t("fallback.rp_therapist_fallback", lang)
        return t("rp_note.rehab_team_line", lang, disciplines=joined, therapist_note=therapist_note), facts

    def _build_rp_functional_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """機能評価 — latest (by session_date) session's functional_progress /
        patient_participation / pain_score."""
        facts: list[str] = []
        lang = ctx.target_lang
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (t("fallback.rp_functional_fallback", lang)), facts
        latest = max(sessions, key=lambda s: _o(s, "session_date", datetime(1970, 1, 1)))
        facts.append("ctx.rehab_sessions")
        progress = str(_o(latest, "functional_progress", "") or "")
        participation = str(_o(latest, "patient_participation", "") or "")
        pain = _o(latest, "pain_score", None)
        progress_label = _label("rp_progress", progress, lang, fallback=progress)
        participation_label = _label("rp_participation", participation, lang, fallback=participation)
        pain_text = f"{pain}/10" if pain is not None else t("section_none.pain_not_assessed", lang)
        return (
            t(
                "rp_note.functional_status_line",
                lang,
                progress=progress_label,
                participation=participation_label,
                pain=pain_text,
            ),
            facts,
        )

    def _build_rp_basic_movement(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """基本動作 — day_post_op から phase (early/mid/late) を再導出。
        generate_rehab_sessions (modules/procedure/engine.py) が内部で使う閾値
        (<=3 early, <=14 mid, else late) と同一 — RehabSession に phase フィールド
        is absent, so recalculation is required. RehabSession.activities raw English
        text is not used (per design spec §4)。"""
        facts: list[str] = []
        lang = ctx.target_lang
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (t("fallback.rp_movement_fallback", lang)), facts
        latest = max(sessions, key=lambda s: _o(s, "session_date", datetime(1970, 1, 1)))
        facts.append("ctx.rehab_sessions")
        day_post_op = _o(latest, "day_post_op", 0) or 0
        if day_post_op <= 3:
            phase = "early"
        elif day_post_op <= 14:
            phase = "mid"
        else:
            phase = "late"
        return _label("rp_phase", phase, lang), facts

    def _build_rp_session_frequency(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """実施回数・期間・1回あたりの時間。"""
        facts: list[str] = []
        lang = ctx.target_lang
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (t("fallback.rp_frequency_fallback", lang)), facts
        facts.append("ctx.rehab_sessions")
        dates = [_o(s, "session_date", datetime(1970, 1, 1)) for s in sessions]
        first_date, last_date = min(dates), max(dates)
        duration = _o(sessions[0], "duration_minutes", 0) or 0
        count = len(sessions)
        return (
            t(
                "rp_note.session_frequency_line",
                lang,
                count=count,
                first=first_date.date().isoformat(),
                last=last_date.date().isoformat(),
                duration=duration,
            ),
            facts,
        )

    def _build_rp_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """本人の希望・家族の希望 — CIF に患者意向を表すフィールドなし
        (design spec §3d)、固定フォールバック。"""
        return t("fallback.rp_goals_fallback", ctx.target_lang), []

    def _build_rp_policy(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハビリテーション治療方針 — 固定フォールバック(design spec §3d)。"""
        return t("fallback.rp_policy_fallback", ctx.target_lang), []

    def _build_rp_discharge_estimate(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハビリテーション終了の目安・時期 — _estimated_los_days を再利用
        (admission_care_plan の estimated_los と同じ target_los データ、
        リハ完了フレーミングの文言のみ異なる)。"""
        lang = ctx.target_lang
        los_days, facts = self._estimated_los_days(ctx)
        return t("rp_note.discharge_estimate_line", lang, days=los_days), facts

    def _build_rp_explanation_consent(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """本人・家族への説明(署名欄) — 固定フォールバック
        (admission_care_plan/nutrition_care_plan と同じ signature-block pattern)。"""
        lang = ctx.target_lang
        return (t("fallback.rp_explanation_fallback", lang)), []

    # ─────────────────────────────────────────────────────────────────
    # NURSING_DISCHARGE_SUMMARY section builders
    # ─────────────────────────────────────────────────────────────────

    def _build_nursing_admission_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build admission_status for NURSING_DISCHARGE_SUMMARY. v9 density fix:
        include admission reason + complications summary."""
        facts: list[str] = []
        lang = ctx.target_lang
        los = ctx.los_days or 1
        facts.append("ctx.los_days")
        cc = ""
        if ctx.encounter is not None:
            cc = _o(ctx.encounter, f"chief_complaint_{lang}", None) or _o(ctx.encounter, "chief_complaint", None) or ""
        comps = list(getattr(ctx, "complications_occurred", []) or [])
        # Phase 1c-2 (2026-09-22): localize complication tokens (31 leaks
        # in JP p=500 admission_status audit — "経過中の合併症: urosepsis"
        # → "経過中の合併症: 尿路性敗血症").
        comp_labels = [_localize_complication(str(c), lang) for c in comps[:3]]
        parts: list[str] = [t("nursing_admission_status.stay_head", lang, los=los)]
        if cc:
            parts.append(t("nursing_admission_status.admission_reason_line", lang, cc=cc))
        if comp_labels:
            sep = t("list_sep.serial", lang)
            parts.append(t("nursing_admission_status.complications_line", lang, list=sep.join(comp_labels)))
            facts.append("ctx.complications_occurred")
        parts.append(t("nursing_admission_status.discharge_met_line", lang))
        return "".join(parts), facts

    def _build_nursing_interventions_provided(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build nursing_interventions_provided from CIF procedures / MAR /
        intake-output totals. v9 density fix — v8 emitted 15-char placeholder."""
        facts: list[str] = []
        lang = ctx.target_lang
        parts: list[str] = []
        procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:5]]
        procs = [p for p in procs if p]
        if procs:
            facts.append("ctx.procedures")
            parts.append(
                t("discharge_readiness.procedures_head", lang) + t("list_sep.serial", lang).join(str(p) for p in procs)
            )
        # Intake/output totals
        io = list(getattr(ctx, "intake_output_records", None) or [])
        if io:
            total_in = sum(
                _o(r, "intake_iv_ml", 0) + _o(r, "intake_oral_ml", 0) + _o(r, "intake_other_ml", 0) for r in io
            )
            total_out = sum(
                _o(r, "output_urine_ml", 0) + _o(r, "output_drain_ml", 0) + _o(r, "output_other_ml", 0) for r in io
            )
            facts.append("ctx.intake_output_records")
            parts.append(
                t("nursing_interventions.io_line", lang, in_ml=total_in, out_ml=total_out, net=total_in - total_out)
            )
        if parts:
            return t("list_sep.semicolon", lang).join(parts) + t("list_sep.period", lang), facts
        return (t("fallback.interventions_fallback", lang)), facts

    def _build_patient_education(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build patient_education from chronic conditions + acute
        admission reason.

        Session-104 Tier 2: acute-disease axis (from
        ``ctx.disease_protocol.disease_id``) is consulted BEFORE the
        chronic-ICD10 axis via ``_lookup_nursing_content``. The 6
        chronic prefixes carry over verbatim from the pre-session-104
        hardcoded map, so byte-diff on non-pilot encounters is zero.
        No risk-derived rows here (unlike nursing_diagnosis /
        care_plan) — patient education is disease-driven only.
        """
        lang = ctx.target_lang
        topics, facts = _lookup_nursing_content(ctx, "patient_education", lang, cap=4)
        if not topics:
            return (t("fallback.patient_education_fallback", lang)), facts
        head = t("patient_education.head", lang)
        sep = t("list_sep.semicolon", lang)
        return head + sep.join(topics) + t("list_sep.period", lang), facts

    def _build_discharge_readiness(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build discharge_readiness from latest ADL + risk. v9 density fix."""
        facts: list[str] = []
        lang = ctx.target_lang
        adls = list(getattr(ctx, "adl_assessments", None) or [])
        risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
        parts: list[str] = []
        if adls:
            latest = adls[-1]
            barthel = _o(latest, "barthel_score", None)
            if barthel is not None:
                facts.append("ctx.adl_assessments[-1]")
                parts.append(t("rehab.discharge_barthel_line", lang, score=barthel))
        if risks:
            latest = risks[-1]
            fall = _o(latest, "fall_risk_level", None)
            braden = _o(latest, "braden_total", None)
            if fall or braden is not None:
                facts.append("ctx.nursing_risk_assessments[-1]")
                bits = []
                if fall:
                    # Localize fall_risk_level via the shared morse_band
                    # catalog (JA emits 「低リスク / 中等度リスク / 高リスク」
                    # rather than the raw EN token). Unknown values fall
                    # back to the raw string.
                    fall_key = str(fall).lower()
                    fall_disp = t(f"morse_band.{fall_key}", lang)
                    if fall_disp == f"morse_band.{fall_key}":
                        fall_disp = str(fall)
                    bits.append(t("rehab.fall_suffix", lang, label=fall_disp))
                if braden is not None:
                    bits.append(f"Braden {braden}")
                parts.append(t("list_sep.serial", lang).join(bits))
        if parts:
            head = t("discharge_readiness.head", lang)
            return head + (t("list_sep.semicolon", lang).join(parts)) + t("list_sep.period", lang), facts
        return (t("fallback.discharge_readiness_fallback", lang)), facts

    # ─────────────────────────────────────────────────────────────────
    # OUTPATIENT_SOAP section builders
    # Reads from encounter_protocol.narrative.outpatient_soap_template via
    # _pick_localized(soap, "<field>", ctx.target_lang) (AD-65 Bug A fix).
    # A missing "<field>_en" (currently the case for all encounter YAMLs —
    # data-authoring gap, not a code bug) yields a generic English fallback
    # phrase with a warn log, instead of silently emitting Japanese text.
    # ─────────────────────────────────────────────────────────────────

    def _get_soap_template(self, ctx: NarrativeContext) -> Any | None:
        """Extract outpatient_soap_template.

        v9 (2026-08-17): resolution chain
          1. encounter_protocol.narrative.outpatient_soap_template
             (encounter-specific — screening / vaccination / referral etc.)
          2. disease_protocol.narrative.outpatient_soap_template
             (acute disease follow-up — v9 new layer)
          3. chronic_soap_templates.yaml lookup by primary chronic ICD
             (v9 new layer — closes the "chronic follow-up" gap for
             hypertension / DM / CKD / etc. which have no per-disease YAML)
          4. None → caller falls through to patient-state engine
        """
        ep = ctx.encounter_protocol
        if ep is not None:
            narrative = _o(ep, "narrative", None)
            if narrative is not None:
                tmpl = _o(narrative, "outpatient_soap_template", None)
                if tmpl is not None:
                    return tmpl
        # L2: disease-side (acute follow-up)
        dp = ctx.disease_protocol
        if dp is not None:
            narrative = _o(dp, "narrative", None)
            if narrative is not None:
                tmpl = _o(narrative, "outpatient_soap_template", None)
                if tmpl is not None:
                    return tmpl
        # L3: chronic-condition registry (v9 new)
        #
        # Session-98 log-noise fix: the registry (`chronic_soap_templates.yaml`)
        # only carries `_ja` fields today. On EN runs `_pick_localized` would
        # emit "template locale field subjective_en missing" and fall through
        # to the CIF-composed EN path anyway — 91,640 warnings on the p=10000
        # US sim, all no-op. Skip the registry entirely for EN so the
        # warning fires only when a genuinely bilingual template drops a
        # locale (the guardrail's original intent).
        if ctx.target_lang == "ja":
            from clinosim.modules.document.narrative._chronic_soap import resolve_chronic_soap

            patient = ctx.patient
            if patient is not None:
                conds = _o(patient, "chronic_conditions", []) or []
                chronic_tmpl = resolve_chronic_soap(conds)
                if chronic_tmpl is not None:
                    return chronic_tmpl
        return None

    def _build_outpatient_subjective(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP subjective from outpatient_soap_template.subjective_<lang>.

        v9 (2026-08-17): dropped the single-line "特記事項なし" fallback in
        favour of a CIF-composed subjective line so Template-only output
        carries usable density. Resolution chain:
          1. encounter_protocol.narrative.outpatient_soap_template.subjective_<lang>
             (explicit encounter-YAML author intent — highest fidelity)
          2. compose from CIF: age/sex + encounter.chief_complaint +
             chronic-condition follow-up context
          3. generic "特記事項なし" only when CIF truly empty (patient=None)
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.generic_fallback", lang)

        # v9 (2026-08-17 evening) FIX: v11 review found 28 encounters had
        # identical stereotype subjective because the chronic SOAP
        # registry supplied a fixed template and the CIF-composed
        # per-patient content was skipped. Now: always append the
        # per-patient composition (age / sex / CC / chronic) even when
        # a template exists, so the reader sees encounter-specific
        # variation on top of the disease-class seed.
        composed = self._compose_outpatient_subjective_from_state(ctx)
        soap = self._get_soap_template(ctx)
        template_prose = ""
        if soap is not None:
            template_prose = _pick_localized(soap, "subjective", lang, ctx)
            if template_prose == fallback:
                template_prose = ""
        if composed and template_prose:
            facts.extend(
                [
                    f"outpatient_soap_template.subjective_{lang}",
                    "ctx.patient.demographics",
                    "ctx.encounter.chief_complaint",
                    "ctx.patient.chronic_conditions",
                ]
            )
            return f"{composed} {template_prose.strip()}", facts
        if composed:
            facts.extend(
                ["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"]
            )
            return composed, facts
        if template_prose:
            facts.append(f"outpatient_soap_template.subjective_{lang}")
            return template_prose.strip(), facts

        return fallback, facts

    def _compose_outpatient_subjective_from_state(self, ctx: NarrativeContext) -> str:
        """Compose a CIF-only SOAP subjective for outpatient visits.

        v9 (2026-08-17) density fix — Template-only output was
        "特記事項なし" for 100 % of outpatient encounters lacking an
        encounter-YAML template. This builds a clinically-readable
        subjective from age + sex + chief_complaint + chronic-context.
        All fields are CIF-CONFIRMED (patient profile + encounter
        record); no scenario data is asserted here.
        """
        patient = ctx.patient
        enc = ctx.encounter
        if patient is None:
            return ""
        lang = ctx.target_lang
        age = _age_at(ctx)
        sex_raw = _o(patient, "sex", None) or ""
        # Sex vocabulary moved to narrative_labels.yaml::sex_label
        # (Phase 1d-16). Case-insensitive lookup via _label's built-in
        # fallback path.
        sex_label = _label("sex_label", str(sex_raw).lower(), lang, fallback="")
        # chief_complaint — encounter first (v9 chief_complaint bug fix),
        # skip English-in-JA leak.
        cc = ""
        if enc is not None:
            cc = _o(enc, f"chief_complaint_{lang}", None) or _o(enc, "chief_complaint", None) or ""
        cc = str(cc)
        # Chronic condition follow-up context (short list, code-lookup localized).
        # Issue #1333: route CIF base code through map_diagnosis_code so the
        # narrative display matches the FHIR emit-target (US F00 → F03.90
        # renders as "Unspecified dementia", not the WHO parent-code
        # "Dementia in Alzheimer disease").
        from clinosim.codes import lookup as _code_lookup
        from clinosim.modules.output.fhir_r4.lib.common import (
            map_diagnosis_code as _map_diagnosis_code,
        )

        country = "JP" if ctx.locale.lower() == "jp" else "US"
        conditions = _o(patient, "chronic_conditions", []) or []
        chronic_labels: list[str] = []
        for c in conditions[:3]:
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            emit_code = _map_diagnosis_code(code, country) or code
            key = _label("code_system_icd_display", "primary", lang)
            disp = _code_lookup(key, emit_code, lang) or emit_code
            chronic_labels.append(disp)
        # Compose
        parts: list[str] = []
        if age and sex_label:
            parts.append(t("outpatient.subject_with_sex", lang, age=age, sex=sex_label))
        elif age:
            parts.append(t("outpatient.subject_no_sex", lang, age=age))
        if cc:
            parts.append(t("outpatient.visit_reason_with_cc", lang, cc=cc))
        else:
            parts.append(t("outpatient.visit_reason_no_cc", lang))
        if chronic_labels:
            sep = t("list_sep.serial", lang)
            parts.append(t("outpatient.chronic_followup", lang, list=sep.join(chronic_labels)))
        text = "".join(parts).strip()
        return text

    def _build_outpatient_objective(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP objective — CIF vitals ALWAYS appear; template is a seed.

        v9 (2026-08-17 evening) FIX: v11 review found 82% of outpatient
        objective sections were "特記事項なし" because the chronic SOAP
        registry supplied templates with `{vital_line}` placeholders that
        _pick_localized couldn't resolve, and the whole section fell back
        to the generic phrase. The registry has been simplified (no
        placeholders) and this builder now:
          1. Composes the CIF vitals line (BP/HR/RR/SpO2/T) as the primary content
          2. Appends the encounter/disease/chronic-registry template text
             as clinical context prose when available
          3. Falls back to vitals-only when no template exists
          4. Only returns the generic 「特記事項なし」 when BOTH template
             text AND vitals are absent (rare — every outpatient encounter
             records at least BP+HR)
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.generic_fallback", lang)

        vital_line = self._compose_vital_signs_line(ctx)
        template_prose = ""
        soap = self._get_soap_template(ctx)
        if soap is not None:
            template_prose = _pick_localized(soap, "objective", lang, ctx)
            if template_prose == fallback:
                # _fill_template_placeholders returned the fallback marker
                # (unresolvable placeholder); treat as empty so vitals alone
                # supply the section.
                template_prose = ""

        if vital_line and template_prose:
            facts.extend(["ctx.vitals", "outpatient_soap_template.objective"])
            return f"{vital_line}。{template_prose.strip()}", facts
        if vital_line:
            facts.append("ctx.vitals")
            return vital_line, facts
        if template_prose:
            facts.append("outpatient_soap_template.objective")
            return template_prose.strip(), facts
        return fallback, facts

    def _compose_progress_subjective_from_state(self, ctx: NarrativeContext) -> str:
        """Inpatient progress_note Subjective composed from CIF facts.

        v9 (2026-08-17) density fix — v8 defaulted to "特記事項なし" for
        every day whose disease_YAML lacked a daily_trajectory entry.
        This composes a minimum-viable subjective from stay_progress +
        today's abnormal vitals (fever / hypoxia flag), backed only by
        confirmed CIF signals.

        Issue #1155 (session-103): EN branch added — parallels the JA
        structure so US inpatient progress notes carry per-day
        subjective ("Hospital day N. Persistent fever 38.5°C. Continued
        SpO2 89 % desaturation.") instead of the flat "No special
        findings" fallback.

        Issue #1327 (session-111): variance fix — when today's vitals
        carry no abnormal marker, the fallback used to emit the same
        "自覚症状に著変なし。" / "No new subjective complaints." on
        every hospital day, producing a flat 15-day CHF stay all
        reading identically. The Issue exemplar pt-25a61e67a2e2 (JP,
        99yo F, 15-day I50.9 admission) shows 15 identical daily notes
        despite Cr 4.26 → 0.84 recovery / dyspnea improvement.

        Fix: (a) compare today's abnormal signal to yesterday's
        (fever_resolved / spo2_recovering / fever_worsening) so the
        rhythm reflects trend, not just snapshot; (b) when the fallback
        fires (no abnormal signal), pick a phase-aware phrase from a
        small pool keyed on stay-phase (early / mid / late / discharge-
        eve) with deterministic day-index rotation so consecutive days
        differ. Every phrase remains CIF-anchored — the pool is
        neutral-observation vocabulary radiologists / nurses use for a
        day with no acute change, not a fabricated symptom claim.
        """
        lang = ctx.target_lang
        picks = _filter_vitals_for_day(ctx.vitals, ctx.day_index, ctx.encounter)
        prev = _filter_vitals_for_day(ctx.vitals, ctx.day_index - 1, ctx.encounter) if ctx.day_index > 0 else []
        parts: list[str] = []
        los = ctx.los_days or 0
        day_1indexed = ctx.day_index + 1
        if los > 0:
            parts.append(t("progress.hospital_day", lang, day=day_1indexed))

        abnormal_added = False
        if picks:
            v = picks[0]
            temp = _o(v, "temperature_celsius", None)
            spo2 = _o(v, "spo2", None)
            temp_f = float(temp) if temp is not None else None
            spo2_f = float(spo2) if spo2 is not None else None

            # Yesterday snapshot for trend detection (#1327).
            prev_temp = float(_o(prev[0], "temperature_celsius", None) or 0.0) if prev else 0.0
            prev_spo2 = float(_o(prev[0], "spo2", None) or 0.0) if prev else 0.0

            if temp_f is not None and temp_f >= 38.0:
                # Escalating vs persistent — differentiate for rhythm.
                if prev_temp and prev_temp < 38.0:
                    parts.append(t("progress.fever_new_onset", lang, t=temp_f))
                elif prev_temp and temp_f > prev_temp + 0.3:
                    parts.append(t("progress.fever_worsening", lang, t=temp_f))
                else:
                    parts.append(t("progress.fever_persistent", lang, t=temp_f))
                abnormal_added = True
            elif temp_f is not None and temp_f < 36.0:
                parts.append(t("progress.hypothermia", lang, t=temp_f))
                abnormal_added = True
            elif prev_temp >= 38.0 and temp_f is not None and temp_f < 37.5:
                # Fever resolved — rhythm-worthy positive change.
                parts.append(t("progress.fever_resolving", lang, pt=prev_temp, t=temp_f))
                abnormal_added = True

            if spo2_f is not None and spo2_f < 92:
                if prev_spo2 and spo2_f < prev_spo2 - 2:
                    parts.append(t("progress.spo2_worsening", lang, s=spo2_f))
                else:
                    parts.append(t("progress.spo2_desaturating", lang, s=spo2_f))
                abnormal_added = True
            elif prev_spo2 and prev_spo2 < 92 and spo2_f is not None and spo2_f >= 94:
                parts.append(t("progress.spo2_recovering", lang, ps=prev_spo2, s=spo2_f))
                abnormal_added = True

        if not abnormal_added:
            # No abnormal signal — pick a phase-aware, day-rotating phrase
            # so a multi-day stay does not read as identical boilerplate
            # (Issue #1327). Phrases stay CIF-anchored: they describe the
            # day's clinical hold, not fabricated symptoms.
            phrase = self._pick_stable_progress_phrase(ctx, lang=lang)
            parts.append(phrase)
        return t("list_sep.chunk", lang).join(parts)

    def _pick_stable_progress_phrase(self, ctx: NarrativeContext, *, lang: str) -> str:
        """Return a neutral-observation subjective phrase for a stable day.

        Issue #1327: rotates through a small pool keyed on stay-phase so
        consecutive hospital days differ even when today's vitals show
        no abnormal marker. Deterministic — the rotation index derives
        from ``day_index`` alone, so seed-reproducibility is preserved
        (no RNG consumption).

        Phase 1d-17: pool moved to
        ``clinosim/locale/shared/inpatient_subjective_pool.yaml``. The
        list index is shared across languages so the same day_index
        picks the same slot in each locale.

        Phase heuristics (approximate; LOS-relative):
          - early:  day 1-2 of the stay
          - mid:    days 3..(los-2)
          - late:   penultimate day
          - eve:    last inpatient day (near discharge)
        """
        from clinosim.locale.loader import load_inpatient_subjective_pool, resolve_localized_display

        los = ctx.los_days or 0
        day = (ctx.day_index or 0) + 1
        if los <= 0:
            phase = "mid"
        elif day <= 2:
            phase = "early"
        elif day >= los:
            phase = "eve"
        elif day == los - 1:
            phase = "late"
        else:
            phase = "mid"

        pool_data = load_inpatient_subjective_pool()
        pool = pool_data.get(phase) or pool_data.get("mid") or []
        if not pool:
            return ""
        idx = (ctx.day_index or 0) % len(pool)
        return resolve_localized_display(pool[idx], lang, fallback="")

    def _compose_progress_assessment_from_state(self, ctx: NarrativeContext) -> str:
        """Inpatient progress_note Assessment from CIF facts.

        v9 (2026-08-17) density fix — pulls today's abnormal labs (H/L
        flagged) + complications flag into a 1-2 line assessment.

        Issue #1074 B9 (session-99 2026-09-04): EN branch added. Prior to
        this fix the EN inpatient progress_note assessment collapsed to
        the ``Clinical assessment ongoing`` fallback for every day of
        every encounter (measured on US p=2000 seed=500: 19.4 % of
        1,409 progress notes shipped identically). The EN branch mirrors
        the JA structure — complications listed, today's abnormal-flag
        labs cited by name+value+flag — so each per-day EN note carries
        patient-specific reasoning.
        """
        lang = ctx.target_lang
        parts: list[str] = []
        # Complications (from record via NarrativeContext v6 field).
        # Phase 1c-2 (2026-09-22): the raw snake_case complication tokens
        # ("delirium" / "acute_kidney_injury" / "postoperative_delirium"
        # …) leaked into JA narratives — 610 occurrences in the JP p=500
        # audit. Route each token through ``_localize_complication`` so JA
        # output reads 「合併症 せん妄、急性腎障害 を認識」 rather than
        # 「合併症 delirium、acute_kidney_injury を認識」.
        comps = list(getattr(ctx, "complications_occurred", []) or [])
        if comps:
            localised = [_localize_complication(str(c), ctx.target_lang) for c in comps[:3]]
            sep = t("list_sep.serial", lang)
            parts.append(t("progress.complications_noted", ctx.target_lang, list=sep.join(localised)))
        # Abnormal labs today — Issue #1154 fix.
        #
        # Prior behaviour: the code read a ``lab.day`` field that real
        # CIF ``lab_results`` never carry (per ``lab_timeseries.py``'s
        # design contract: "adding a `day` field at the CIF layer is
        # therefore unnecessary — result_datetime is the time source").
        # ``d = _o(lab, "day", None)`` was always None, so
        # ``if d is not None and d != ctx.day_index: continue`` never
        # fired and every progress-note day showed the SAME first-6
        # abnormal labs across an 8-day stay.
        #
        # Fix: two-path day resolution, mirroring ``_filter_vitals_for_day``:
        #   1. Explicit ``lab.day`` (legacy test fixtures + any CIF that
        #      may carry it) → filter by that.
        #   2. Fall back to ``result_datetime`` vs
        #      ``ctx.encounter.admission_datetime`` (real CIF).
        _lab_enc = getattr(ctx, "encounter", None)
        _lab_adm_raw = _o(_lab_enc, "admission_datetime", None) if _lab_enc is not None else None
        _lab_adm_dt = _parse_iso_datetime(_lab_adm_raw) if _lab_adm_raw is not None else None
        labs = list(ctx.lab_results or [])
        abn: list[str] = []
        for lab in labs:
            flag = _o(lab, "flag", None)
            if not flag:
                continue
            d = _o(lab, "day", None)
            if d is None and _lab_adm_dt is not None:
                _rdt = _parse_iso_datetime(_o(lab, "result_datetime", None))
                if _rdt is not None:
                    # Session-104 Issue #1166: calendar-day bucket
                    # (sibling of _filter_vitals_for_day v7).
                    d = (_rdt.date() - _lab_adm_dt.date()).days
            if d is not None and d != ctx.day_index:
                continue
            name = _o(lab, "lab_name", None)
            val = _o(lab, "value", None)
            unit = _o(lab, "unit", "") or ""
            if name and val is not None:
                # Phase 1c-5 (2026-09-23): route lab_name through
                # ``_localize_lab_name`` and abnormal-flag through
                # ``_localize_lab_flag`` so JA output emits 「クレアチニン
                # 3.2 mg/dL [重篤]」 rather than 「Creatinine 3.2 mg/dL
                # [critical]」. Pre-fix the JP p=10000 audit surfaced
                # ~22,000 raw-English lab-name leaks + ~600 raw
                # ``[critical]`` markers in ``本日の検査所見:`` lists.
                disp_name = _localize_lab_name(name, ctx.target_lang)
                disp_flag = _localize_lab_flag(flag, ctx.target_lang)
                abn.append(f"{disp_name} {val} {unit} [{disp_flag}]")
            if len(abn) >= 6:
                break
        if abn:
            sep = t("list_sep.serial", lang)
            parts.append(t("progress.notable_labs", ctx.target_lang, list=sep.join(abn[:4])))
        if not parts:
            parts.append(t("progress.stable_course_assessment", ctx.target_lang))
        return t("list_sep.chunk", lang).join(parts)

    def _compose_progress_plan_from_state(self, ctx: NarrativeContext) -> str:
        """Inpatient progress_note Plan from CIF facts.

        v9 (2026-08-17) density fix — lists today's active medications
        (JA localized) and today's procedures / orders.

        Issue #1074 B9 (session-99 2026-09-04): EN branch added — parallels
        the JA structure so the EN plan section carries per-day med and
        procedure lists instead of the generic ``Continue current
        management`` fallback (measured on US p=2000 seed=500: 7.8 % of
        1,409 progress notes shipped the fallback).
        """
        lang = ctx.target_lang
        parts: list[str] = []
        # Today's meds (MAR) — Issue #1154 fix: MedicationAdministration
        # records store ``scheduled_datetime`` / ``actual_datetime`` but
        # no ``day`` field, so the naive ``m.day`` filter previously
        # accepted every med from every day of the stay. Derive day from
        # timestamp vs admission_datetime, mirroring the pattern in
        # ``_filter_vitals_for_day``.
        admins = list(ctx.medications or [])
        _p_enc = getattr(ctx, "encounter", None)
        _adm_raw = _o(_p_enc, "admission_datetime", None) if _p_enc is not None else None
        _adm_dt = _parse_iso_datetime(_adm_raw) if _adm_raw is not None else None
        med_names: list[str] = []
        seen: set[str] = set()
        for m in admins:
            d = _o(m, "day", None)
            if d is None and _adm_dt is not None:
                # Derive day from the med's own timestamp field. Session-104
                # Issue #1166: calendar-day bucket (sibling of
                # _filter_vitals_for_day v7).
                _m_ts_raw = _o(m, "actual_datetime", None) or _o(m, "scheduled_datetime", None)
                _m_ts = _parse_iso_datetime(_m_ts_raw) if _m_ts_raw is not None else None
                if _m_ts is not None:
                    d = (_m_ts.date() - _adm_dt.date()).days
            if d is not None and d != ctx.day_index:
                continue
            name = _o(m, "drug_name", None) or _o(m, "medication", None) or _o(m, "name", None)
            if not name or name in seen:
                continue
            seen.add(name)
            if lang == "ja":
                # JA-locale drug-name katakana lookup (locale-specific
                # data pipeline, not a display translation — same
                # rationale as _compose_ap_plan_from_state in Phase 1d-18).
                from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

                med_names.append(_localize_drug_name(str(name), "JP"))
            else:
                med_names.append(str(name))
            if len(med_names) >= 6:
                break
        if med_names:
            sep = t("list_sep.serial", lang)
            parts.append(t("progress.meds_continue", lang, list=sep.join(med_names)))
        # Today's procedures
        procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:4]]
        procs = [p for p in procs if p]
        if procs:
            sep = t("list_sep.serial", lang)
            parts.append(t("progress.procs_today", lang, list=sep.join(str(p) for p in procs)))
        if not parts:
            parts.append(t("progress.observation_fallback", lang))
        return t("list_sep.chunk", lang).join(parts)

    def _compose_today_vitals_line(self, ctx: NarrativeContext) -> str:
        """Compose today's numeric vital-signs summary for inpatient
        progress_note objective. Filters ``ctx.vitals`` by day, using the
        explicit ``day`` field when present and falling back to a
        timestamp-derived day offset against ``ctx.encounter.admission_datetime``
        when the field is None (which it always is in current CIF fullsets
        — 346-record admissions store only ISO ``timestamp``, no day tag,
        so the original day-field filter yielded EVERY vital on every
        day and the LLM saw the same T=38.1°C repeated for 15
        consecutive progress notes).

        Fallback chain: day-field match → timestamp-derived day →
        first record (initial admission vitals).
        """
        picks = _filter_vitals_for_day(ctx.vitals, ctx.day_index, ctx.encounter)
        if not picks:
            return ""
        v = picks[0]
        parts: list[str] = []
        _sbp = _o(v, "systolic_bp", None)
        _dbp = _o(v, "diastolic_bp", None)
        if _sbp and _dbp:
            parts.append(f"BP {int(_sbp)}/{int(_dbp)} mmHg")
        _hr = _o(v, "heart_rate", None)
        if _hr:
            parts.append(f"HR {int(_hr)} 回/分" if ctx.target_lang == "ja" else f"HR {int(_hr)} bpm")
        _rr = _o(v, "respiratory_rate", None)
        if _rr:
            parts.append(f"RR {int(_rr)} 回/分" if ctx.target_lang == "ja" else f"RR {int(_rr)} /min")
        _spo2 = _o(v, "spo2", None)
        if _spo2:
            parts.append(f"SpO2 {_spo2:.0f}%")
        _temp = _o(v, "temperature_celsius", None)
        if _temp:
            parts.append(f"T {_temp:.1f}°C")
        return ", ".join(parts) if parts else ""

    def _compose_pe_vitals_line(self, ctx: NarrativeContext) -> str:
        """Compose a JA vital-signs prose line for the physical_examination
        section (Issue #979).

        Picks the day using ``ctx.day_index`` (set per-stub by
        ``passes.NarrativePass._stub_day_index``, so admission_hp → day 0,
        discharge_summary → LOS-1, progress_note → per-day) and resolves
        vitals via ``_filter_vitals_for_day`` (which handles the CIF
        ``timestamp`` vs ``day`` divergence — see helper docstring).

        If the target day has no vitals, falls back to the encounter's
        earliest vitals record (day 0) so admission_hp / ED_NOTE / progress
        notes still emit a vitals block whenever the CIF has any vitals at
        all. Returns "" only when ``ctx.vitals`` is entirely empty.

        Format matches real JP acute-care admission notes:
            "BP 130/80 mmHg, HR 88/min, T 37.5°C, SpO2 96% (RA), RR 20/min"
        """
        vitals = list(ctx.vitals or [])
        if not vitals:
            return ""
        picks = _filter_vitals_for_day(vitals, ctx.day_index, ctx.encounter)
        if not picks:
            # Day-specific vitals absent — use the earliest record so the PE
            # section still gets a vitals block. Prefer this to emitting
            # nothing (which was the pre-#979 default and caused 57.7% of PE
            # sections to lack any numeric vitals).
            picks = [vitals[0]]
        v = picks[0]

        parts: list[str] = []
        _sbp = _o(v, "systolic_bp", None)
        _dbp = _o(v, "diastolic_bp", None)
        if _sbp and _dbp:
            parts.append(f"BP {int(_sbp)}/{int(_dbp)} mmHg")
        _hr = _o(v, "heart_rate", None)
        if _hr:
            parts.append(f"HR {int(_hr)}/min")
        _temp = _o(v, "temperature_celsius", None)
        if _temp:
            parts.append(f"T {_temp:.1f}°C")
        _spo2 = _o(v, "spo2", None)
        if _spo2:
            # Room-air unless a supplemental-oxygen flag is set on the vitals
            # record (session-88i pattern — see feedback_session_derived_procedure_period).
            on_o2 = bool(_o(v, "on_supplemental_oxygen", False))
            suffix = "" if on_o2 else " (RA)"
            parts.append(f"SpO2 {_spo2:.0f}%{suffix}")
        _rr = _o(v, "respiratory_rate", None)
        if _rr:
            parts.append(f"RR {int(_rr)}/min")

        return ", ".join(parts)

    def _apply_cc_pe_consistency(self, text: str, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Rewrite PE clauses contradicted by the chief_complaint (Issue #980).

        Reads the JA chief_complaint from CIF (encounter.chief_complaint_ja /
        encounter.chief_complaint), detects two contradiction classes, and
        replaces the contradicted PE clause with a deterministic phrase
        drawn from a small pool by SHA256(encounter_id + salt).

        Contradiction classes handled:
          * CC ∋ 意識障害 / 意識消失 / 昏睡 / 意識レベル低下 / 意識もうろう
            (not negated by なし/否定/認めず/etc.) → replace 「意識清明」 clause
          * CC ∋ 呼吸困難 / 息苦しさ / 喘鳴 (not negated) → replace
            「呼吸音清明」 clause

        Returns ``(rewritten_text, facts)``. ``facts`` names the rewrite
        rule(s) applied so downstream provenance tools can see it. If no
        rewrite fires, ``text`` is returned unchanged.
        """
        facts: list[str] = []
        if not text or ctx.target_lang != "ja":
            return text, facts

        enc = ctx.encounter
        if enc is None:
            return text, facts
        cc = _o(enc, "chief_complaint_ja", None) or _o(enc, "chief_complaint", None) or ""
        cc = str(cc)
        if not cc:
            return text, facts

        enc_id = _o(enc, "encounter_id", "") or ""

        if _cc_keyword_positively_present(cc, _CC_ALTERED_CONSCIOUSNESS_KEYWORDS):
            replacement = _pick_from_pool_by_encounter(_PE_ALTERED_CONSCIOUSNESS_POOL_JA, enc_id, "pe_consciousness")
            new_text = _rewrite_pe_clause(text, ("意識清明",), replacement)
            if new_text != text:
                facts.append("cc_pe_consistency:consciousness")
                text = new_text

        if _cc_keyword_positively_present(cc, _CC_SEVERE_DYSPNEA_KEYWORDS):
            replacement = _pick_from_pool_by_encounter(_PE_SEVERE_DYSPNEA_POOL_JA, enc_id, "pe_respiratory")
            new_text = _rewrite_pe_clause(text, ("呼吸音清明",), replacement)
            if new_text != text:
                facts.append("cc_pe_consistency:respiratory")
                text = new_text

        return text, facts

    def _compose_vital_signs_line(self, ctx: NarrativeContext) -> str:
        """Compose a single-line JA/EN vital-signs summary from ctx.vitals[0]
        (encounter has 1 outpatient vitals record per visit — see outpatient.py
        line 162+). Returns "" when no vitals are recorded.
        """
        vitals = list(ctx.vitals or [])
        if not vitals:
            return ""
        v = vitals[0]
        parts: list[str] = []
        _sbp = _o(v, "systolic_bp", None)
        _dbp = _o(v, "diastolic_bp", None)
        if _sbp and _dbp:
            parts.append(f"BP {int(_sbp)}/{int(_dbp)} mmHg")
        _hr = _o(v, "heart_rate", None)
        if _hr:
            unit_ja = "回/分"
            unit_en = "bpm"
            parts.append(f"HR {int(_hr)} {unit_ja if ctx.target_lang == 'ja' else unit_en}")
        _rr = _o(v, "respiratory_rate", None)
        if _rr:
            unit_ja = "回/分"
            unit_en = "/min"
            parts.append(f"RR {int(_rr)} {unit_ja if ctx.target_lang == 'ja' else unit_en}")
        _spo2 = _o(v, "spo2", None)
        if _spo2:
            parts.append(f"SpO2 {_spo2:.0f}%")
        _temp = _o(v, "temperature_celsius", None)
        if _temp:
            parts.append(f"T {_temp:.1f}°C")
        if not parts:
            return ""
        return ", ".join(parts)

    def _build_outpatient_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP assessment from outpatient_soap_template.assessment_<lang>.

        Also handles ED_NOTE context (falls back to CIF-composed assessment).

        Issue #780: when no template is available, list active chronic conditions
        so the A section reflects the patient's real problem list.

        Issue #1074 B9 (session-99 2026-09-04): ED_NOTE and outpatient-with-no-
        chronic-conditions paths now compose from CIF facts (primary dx +
        working diagnoses / chief complaint) instead of the generic
        ``Clinical assessment ongoing`` fallback.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.generic_assessment", lang)

        # ED_NOTE: previously returned generic. Now composes from CIF —
        # primary dx code + working diagnoses give a per-patient A line.
        if ctx.document_type == DocumentType.ED_NOTE:
            composed = self._compose_ed_assessment_from_state(ctx)
            if composed:
                facts.append("ctx.ed_assessment.state_composed")
                return composed, facts
            return fallback, facts

        # Issue #985: ALWAYS compute the integrated per-chronic-condition
        # value block first, so an encounter YAML template ("HbA1c 目標
        # 7.0% 未満を基準に評価") gets an appended CIF-anchored value line
        # ("1. 2型糖尿病: HbA1c 6.8% — 目標 7.0% 未満 — 目標達成中"),
        # rather than emitting identically for 100+ diabetic patients.
        integrated = self._compose_chronic_assessment_integrated(ctx)

        soap = self._get_soap_template(ctx)
        if soap is not None:
            text = _pick_localized(soap, "assessment", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.outpatient_soap_template.assessment_{lang}")
                if integrated:
                    facts.extend(["ctx.patient.chronic_conditions", "ctx.vitals.today", "ctx.lab_results.today"])
                    return f"{text}\n{integrated}", facts
                return text, facts

        # v9 (2026-08-17) density fix: build a per-chronic-condition
        # assessment line that integrates today's vitals + abnormal labs,
        # not just a raw code list. Falls back to the flat chronic list
        # when no interpretation is available.
        if integrated:
            facts.extend(["ctx.patient.chronic_conditions", "ctx.vitals.today", "ctx.lab_results.today"])
            return integrated, facts

        # Original #780 fallback (chronic list only)
        chronic_line = self._compose_chronic_condition_line(ctx)
        if chronic_line:
            facts.append("ctx.patient.chronic_conditions")
            return chronic_line, facts

        # Issue #1074 B9: patients with NO chronic conditions previously fell
        # through to the generic "Clinical assessment ongoing" — 11.6 % of
        # 1,409 progress notes in the US p=2000 seed=500 baseline. When no
        # template + no chronic list is available, compose from the primary
        # encounter reason (chief_complaint + primary_dx_display) so the
        # assessment reflects the actual visit.
        cc_line = self._compose_encounter_reason_line(ctx)
        if cc_line:
            facts.append("ctx.encounter.chief_complaint")
            return cc_line, facts

        return fallback, facts

    def _compose_ed_assessment_from_state(self, ctx: NarrativeContext) -> str:
        """ED_NOTE assessment composed from CIF facts (Issue #1074 B9).

        Combines admission dx + working diagnoses + primary complications
        into a short JA/EN line so ED encounters carry per-patient A text.
        Empty string when no facts available (caller falls back to generic).
        """
        lang = ctx.target_lang
        from clinosim.codes import lookup as _code_lookup

        # Use working_diagnoses from ctx if available
        wds = list(getattr(ctx, "working_diagnoses", []) or [])
        primary_dx_codes: list[str] = []
        for wd in wds[:3]:
            if isinstance(wd, dict):
                code = wd.get("disease_id") or wd.get("code") or wd.get("icd_code")
                if code:
                    primary_dx_codes.append(str(code))
            else:
                code = _o(wd, "disease_id", None) or _o(wd, "code", None)
                if code:
                    primary_dx_codes.append(str(code))

        # If no working dx, fall back to encounter chief complaint anchor
        parts: list[str] = []
        if primary_dx_codes:
            disp_key = _label("code_system_icd_display", "primary", lang)
            labels = []
            for code in primary_dx_codes:
                # Strip pediatric/other prefixes — try registry lookup first
                disp = _code_lookup(disp_key, code, lang) or code
                labels.append(disp)
            sep = t("list_sep.serial", lang)
            parts.append(t("ed_assessment.working_dx_line", lang, list=sep.join(labels)))
        else:
            # Fall through to chief_complaint if no dx
            cc = self._compose_encounter_reason_line(ctx)
            if cc:
                return cc

        # Complications if any.
        # Phase 1c-2 (2026-09-22): localize complication tokens (6 leaks
        # in JP p=500 ed assessment audit — "合併症: acute_kidney_injury"
        # → "合併症: 急性腎障害").
        comps = list(getattr(ctx, "complications_occurred", []) or [])
        if comps:
            comp_labels = [_localize_complication(str(c), lang) for c in comps[:3]]
            sep = t("list_sep.serial", lang)
            parts.append(t("ed_assessment.complications_line", lang, list=sep.join(comp_labels)))

        sep = t("list_sep.period_space", lang)
        return sep.join(parts) + (t("list_sep.period", lang) if parts else "")

    def _compose_encounter_reason_line(self, ctx: NarrativeContext) -> str:
        """Short JA/EN line describing the visit's primary reason (Issue #1074 B9).

        Reads ``encounter.chief_complaint`` first; falls back to
        ``primary_diagnosis`` when the CC is empty or looks like a template
        stub. Empty string when neither is available.
        """
        enc = getattr(ctx, "encounter", None)
        if enc is None:
            return ""
        lang = ctx.target_lang
        # Phase 1c-6 (2026-09-23): prefer the locale-specific
        # ``chief_complaint_{ja,en}`` over the raw ``chief_complaint``
        # so JA output emits 「来院理由: 予防接種」 rather than the
        # underlying-EN 「来院理由: Vaccination visit」 for encounters
        # (immunization / vaccination visits, ED follow-ups) whose
        # emitters populate both language slots. Mirrors the pattern in
        # `_render_outpatient_chronic_soap` (line 5258).
        cc = _o(enc, f"chief_complaint_{lang}", None) or _o(enc, "chief_complaint", "") or ""
        cc = str(cc).strip()
        primary_dx = _o(enc, "primary_diagnosis", "") or _o(enc, "primary_dx", "") or ""
        primary_dx = str(primary_dx).strip()

        # Prefer a non-empty, non-stub chief_complaint. Phase 1d-4
        # (2026-09-23): binary ``if is_ja: X else Y`` inline templates
        # replaced with the language-agnostic ``t(key, lang, **params)``
        # phrase-catalog lookup (see ``clinosim/locale/i18n.py`` and
        # ``narrative_phrases.yaml``). Adding fr / zh / … requires only
        # a YAML edit; no code change here.

        if cc and cc.lower() not in ("none", "n/a", "--"):
            return t("chief_complaint.encounter_reason", ctx.target_lang, cc=cc)
        if primary_dx:
            return t("chief_complaint.primary_problem", ctx.target_lang, dx=primary_dx)
        return ""

    def _compose_chronic_condition_line(self, ctx: NarrativeContext) -> str:
        """List the patient's active chronic conditions in a short JA/EN line
        for the SOAP Assessment section (Issue #780 fallback)."""
        patient = ctx.patient
        conditions = _o(patient, "chronic_conditions", []) or []
        if not conditions:
            return ""
        # Resolve each condition to a language-appropriate label. `code` is
        # ICD-10 (JP) or ICD-10-CM (US) — use the shared codes registry to
        # pick a JA display when available; fall back to the code itself.
        from clinosim.codes import lookup as _code_lookup

        lang = ctx.target_lang
        labels: list[str] = []
        for c in conditions:
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            disp_key = _label("code_system_icd_display", "primary", lang)
            disp = _code_lookup(disp_key, code, lang) or code
            labels.append(disp)
        if not labels:
            return ""
        sep = t("list_sep.serial", lang)
        return t("chronic.followup_head", lang, list=sep.join(labels))

    def _compose_chronic_assessment_integrated(self, ctx: NarrativeContext) -> str:
        """SOAP Assessment enriched with today's vitals + labs + target
        comparison prose (Issue #985 personalization).

        v9 emitted a chronic-condition list; v9-density integrated abnormal
        labs but only fired on ``flag`` presence and lacked target-reference
        prose. #985 lifts:

          - Cites the patient's actual value regardless of flag (a
            controlled HbA1c 6.8% is still worth citing against target
            7.0% — that's the point of the follow-up assessment).
          - Adds explicit target reference (JDS DM HbA1c < 7.0%, JAS
            LDL < 120 mg/dL primary prevention, JSH BP < 140/90 mmHg,
            KDIGO CKD stage classification).
          - Adds CKD staging from eGFR when present.
          - Adds pertinent negatives (尿アルブミン when measured) so the
            assessment reads as "actively assessed and negative" rather
            than silent.
          - Adds continuation-med tail for the primary chronic drug when
            present in ``current_medications``.

        All values are CIF-CONFIRMED (measured today or carried from
        ``current_medications``). Never fabricates a "前回" prior value —
        outpatient chronic-care follow-ups have single-visit lab scope in
        this simulator; a prior-visit comparison would need cross-encounter
        history that ctx does not currently carry. The generic follow-up
        stub falls through when no measurement is available.
        """
        patient = ctx.patient
        if patient is None:
            return ""
        conditions = _o(patient, "chronic_conditions", []) or []
        # Issue #1183: the empty-conditions early return silently dropped
        # abnormal-vital lines for patients with no chronic conditions.
        # Continue into the loop with an empty condition list; the
        # vital-abnormal pass at the end still fires.
        vitals = list(ctx.vitals or [])
        labs = list(ctx.lab_results or [])
        v0 = vitals[0] if vitals else None
        sbp = _o(v0, "systolic_bp", None) if v0 else None
        dbp = _o(v0, "diastolic_bp", None) if v0 else None
        # Issue #1181: cast remaining vitals to floats up-front so the
        # observation-aware fallback below can quote them without a
        # try/except per branch (also consumed by the #1183 vital-abnormal
        # handler after the condition-dispatch loop).
        _hr_raw = _o(v0, "heart_rate", None) if v0 else None
        _t_raw = _o(v0, "temperature_celsius", None) if v0 else None
        _spo2_raw = _o(v0, "spo2", None) if v0 else None
        try:
            hr_f = float(_hr_raw) if _hr_raw is not None else None
        except (TypeError, ValueError):
            hr_f = None
        try:
            temp_f = float(_t_raw) if _t_raw is not None else None
        except (TypeError, ValueError):
            temp_f = None
        try:
            spo2_f = float(_spo2_raw) if _spo2_raw is not None else None
        except (TypeError, ValueError):
            spo2_f = None

        # Issue #985: cite value regardless of flag — a target-comparison
        # assessment needs the actual number even when in-range.
        lab_by_name: dict[str, tuple[Any, str | None]] = {}
        for lab in labs:
            name = str(_o(lab, "lab_name", "") or "").lower()
            val = _o(lab, "value", None)
            if not name or val is None:
                continue
            lab_by_name[name] = (val, _o(lab, "unit", None))

        from clinosim.codes import lookup as _code_lookup

        lang = ctx.target_lang
        is_ja = lang == "ja"
        disp_key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"

        # Pre-resolve current-medications for continuation-tail. Issue #1033:
        # rendering always as ``lang="ja"`` leaks katakana drug names into US
        # assessment prose (`Metformin continue` → `メトホルミン continue`).
        # Render in the target locale and match hints in the target locale so
        # a US assessment cites the English drug name and a JP assessment
        # cites the katakana name.
        cur_meds = _o(patient, "current_medications", []) or []
        med_names_display = [_render_home_med_name(m, lang=ctx.target_lang) for m in cur_meds]
        med_names_display = [n for n in med_names_display if n]

        def _pick_med_containing(en_hints: tuple[str, ...], ja_hints: tuple[str, ...]) -> str | None:
            """Return the first current-med whose (locale-rendered) name
            contains any hint. Hints must be provided for both locales — the
            match set is chosen by ``ctx.target_lang`` so a US assessment
            searches on English tokens and a JP assessment on katakana.
            """
            hints = ja_hints if is_ja else en_hints
            for n in med_names_display:
                for h in hints:
                    if h in n:
                        return n
            return None

        lines: list[str] = []
        for i, c in enumerate(conditions, 1):
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            label = _code_lookup(disp_key, code, ctx.target_lang) or code
            code_prefix = code.split(".")[0].upper()
            interp = ""

            # ── I10: Essential hypertension ────────────────────────────
            if code_prefix.startswith("I10") and sbp and dbp:
                if sbp >= NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD or dbp >= NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD:
                    ctrl = t("control_status.poorly_controlled", lang)
                elif sbp >= NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD or dbp >= NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD:
                    ctrl = t("control_status.high_normal", lang)
                else:
                    ctrl = t("control_status.at_goal", lang)
                target = (
                    (
                        f"目標 {NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD}/"
                        f"{NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD} mmHg 未満"
                    )
                    if is_ja
                    else (
                        f"target < {NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD}/"
                        f"{NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD} mmHg"
                    )
                )
                med = _pick_med_containing(
                    en_hints=("Amlodipine", "Enalapril", "Losartan", "Telmisartan"),
                    ja_hints=("アムロジピン", "エナラプリル", "ロサルタン", "テルミサルタン"),
                )
                med_tail = f"、{med} 継続" if med and is_ja else (f"; {med} continue" if med else "")
                interp = f"BP {int(sbp)}/{int(dbp)} mmHg — {target} — {ctrl}{med_tail}" + t("list_sep.period", lang)

            # ── E11 / E10: Diabetes mellitus ───────────────────────────
            elif code_prefix.startswith(("E10", "E11")):
                parts_dm: list[str] = []
                hba1c = lab_by_name.get("hba1c")
                if hba1c:
                    v, u = hba1c
                    try:
                        vf = float(v)
                        if vf >= NARRATIVE_HBA1C_DIABETES_THRESHOLD + 0.5:  # ≥ 7.0
                            ctrl = t("control_status.poorly_controlled", lang)
                        elif vf >= NARRATIVE_HBA1C_DIABETES_THRESHOLD:  # 6.5-7.0
                            ctrl = t("control_status.near_target", lang)
                        else:
                            ctrl = t("control_status.at_goal_active", lang)
                    except (TypeError, ValueError):
                        ctrl = ""
                    target = t("control_status.hba1c_target_below_7", lang)
                    parts_dm.append(
                        f"HbA1c {v}{u or '%'} — {target} — {ctrl}" if ctrl else f"HbA1c {v}{u or '%'} — {target}"
                    )
                # 尿アルブミン (pertinent info when measured)
                ualb = lab_by_name.get("urine_albumin") or lab_by_name.get("albuminuria")
                if ualb:
                    v, u = ualb
                    parts_dm.append(t("chronic_labs.urine_albumin", lang, value=v, unit=u or "mg/gCr"))
                # 空腹時血糖 — Issue #1188 F4: Nathan formula consistency
                # gate. `eAG (mg/dL) ≈ 28.7 × HbA1c − 46.7`. When HbA1c is
                # elevated (≥8) but the glucose is normoglycemic (<160),
                # the paired citation is clinically implausible (a random
                # glucose of 120-135 mg/dL is not compatible with HbA1c 9%
                # unless the sample is a rare tight-fasting draw). Rather
                # than paper over the underlying CIF sampling mismatch,
                # skip the glucose citation when the pair is Nathan-
                # inconsistent — HbA1c is the more meaningful long-term
                # marker anyway, and the Assessment line stays clean.
                fbg = lab_by_name.get("glucose")
                if fbg:
                    v_g, u_g = fbg
                    _emit_glucose = True
                    if hba1c:
                        try:
                            _hba1c_val = float(hba1c[0])
                            _glucose_val = float(v_g)
                            _expected_eag = 28.7 * _hba1c_val - 46.7
                            # Skip when reported glucose is >60 mg/dL below
                            # the Nathan-expected eAG (i.e., the pair
                            # implausibly asserts good acute control on a
                            # patient with poor long-term control).
                            if _hba1c_val >= 8.0 and _glucose_val + 60 < _expected_eag:
                                _emit_glucose = False
                        except (TypeError, ValueError):
                            pass
                    if _emit_glucose:
                        parts_dm.append(t("chronic_labs.glucose_line", lang, value=v_g, unit=u_g or "mg/dL"))
                med = _pick_med_containing(
                    en_hints=("Metformin", "Glimepiride", "Insulin", "Sitagliptin", "DPP"),
                    ja_hints=("メトホルミン", "グリメピリド", "インスリン", "シタグリプチン", "DPP"),
                )
                if med:
                    parts_dm.append(t("prescription.medication_continue", lang, med=med))
                if parts_dm:
                    interp = t("list_sep.serial", lang).join(parts_dm) + t("list_sep.period", lang)

            # ── E78: Dyslipidemia ──────────────────────────────────────
            elif code_prefix.startswith("E78"):
                ldl = lab_by_name.get("ldl")
                if ldl:
                    v, u = ldl
                    try:
                        vf = float(v)
                        if vf >= NARRATIVE_LDL_HIGH_THRESHOLD:
                            ctrl = t("control_status.high_ldl_statin_underresponse", lang)
                        elif vf >= NARRATIVE_LDL_BORDERLINE_THRESHOLD:
                            ctrl = t("control_status.borderline_intensification", lang)
                        elif vf >= NARRATIVE_LDL_ELEVATED_THRESHOLD:
                            ctrl = t("control_status.elevated", lang)
                        else:
                            ctrl = t("control_status.at_goal", lang)
                    except (TypeError, ValueError):
                        ctrl = ""
                    target = (
                        f"目標 {NARRATIVE_LDL_ELEVATED_THRESHOLD} mg/dL 未満 (一次予防)"
                        if is_ja
                        else f"target < {NARRATIVE_LDL_ELEVATED_THRESHOLD} mg/dL (primary prevention)"
                    )
                    med = _pick_med_containing(
                        en_hints=("statin", "Rosuvastatin", "Atorvastatin", "Ezetimibe"),
                        ja_hints=("スタチン", "ロスバスタチン", "アトルバスタチン", "エゼチミブ"),
                    )
                    med_tail = f"、{med} 継続" if med and is_ja else (f"; {med} continue" if med else "")
                    interp = f"LDL {v} {u or 'mg/dL'} — {target} — {ctrl}{med_tail}" + t("list_sep.period", lang)

            # ── N18: Chronic kidney disease ────────────────────────────
            elif code_prefix.startswith("N18"):
                parts_ckd: list[str] = []
                cr = lab_by_name.get("cr") or lab_by_name.get("creatinine")
                egfr = lab_by_name.get("egfr")
                if egfr:
                    v, u = egfr
                    try:
                        vf = float(v)
                        if vf >= 90:
                            stage = "G1"
                        elif vf >= 60:
                            stage = "G2"
                        elif vf >= 45:
                            stage = "G3a"
                        elif vf >= 30:
                            stage = "G3b"
                        elif vf >= 15:
                            stage = "G4"
                        else:
                            stage = "G5"
                    except (TypeError, ValueError):
                        stage = ""
                    stage_ja = t("chronic_labs.ckd_stage", lang, stage=stage)
                    # UCUM eGFR unit "mL/min/{1.73_m2}" carries a `{}`
                    # annotation that reads as a placeholder in narrative.
                    # Prefer the plain human display for prose emit.
                    display_u = "mL/min/1.73m²" if u and "1.73" in str(u) else (u or "mL/min/1.73m²")
                    parts_ckd.append(f"eGFR {v} {display_u} ({stage_ja})")
                if cr and not egfr:
                    v, u = cr
                    parts_ckd.append(f"Cr {v} {u or 'mg/dL'}")
                if parts_ckd:
                    interp = t("list_sep.serial", lang).join(parts_ckd) + (t("chronic_monitoring.renal_function", lang))

            # ── J44: COPD (stable) ─────────────────────────────────────
            elif code_prefix.startswith("J44"):
                spo2 = _o(v0, "spo2", None) if v0 else None
                bits: list[str] = []
                if spo2:
                    bits.append(f"SpO2 {float(spo2):.0f}%")
                med = _pick_med_containing(
                    en_hints=("LABA", "LAMA", "Tiotropium", "Salmeterol"),
                    ja_hints=("LABA", "LAMA", "チオトロピウム", "サルメテロール"),
                )
                if med:
                    bits.append(t("prescription.medication_inhalation_continue", lang, med=med))
                if bits:
                    interp = t("list_sep.serial", lang).join(bits) + (t("chronic_monitoring.cat_mmrc_review", lang))

            # ── J45: Asthma ────────────────────────────────────────────
            elif code_prefix.startswith("J45"):
                spo2 = _o(v0, "spo2", None) if v0 else None
                bits2: list[str] = []
                if spo2:
                    bits2.append(f"SpO2 {float(spo2):.0f}%")
                med = _pick_med_containing(
                    en_hints=("ICS", "Salmeterol", "Montelukast"),
                    ja_hints=("ICS", "サルメテロール", "モンテルカスト"),
                )
                if med:
                    bits2.append(t("prescription.medication_continue", lang, med=med))
                if bits2:
                    interp = t("list_sep.serial", lang).join(bits2) + (t("chronic_monitoring.act_control_review", lang))

            if interp:
                lines.append(f"{i}. {label}: {interp}")
            else:
                # Issue #1181 (87.7% of SOAP notes contradicted by their
                # own encounter's Observations): before falling back to
                # "本日測定なし", check whether *any* vitals or labs were
                # actually captured on this encounter. If so, cite the
                # top three general observations rather than assert
                # "not measured" — the same encounter carries the
                # measurements verbatim.
                obs_bits: list[str] = []
                if sbp is not None and dbp is not None:
                    obs_bits.append(f"BP {int(sbp)}/{int(dbp)} mmHg")
                if hr_f is not None:
                    obs_bits.append(t("chronic_labs.hr_per_min", lang, value=int(round(hr_f))))
                if temp_f is not None:
                    obs_bits.append(f"T {temp_f:.1f}°C")
                if spo2_f is not None:
                    obs_bits.append(f"SpO2 {spo2_f:.0f}%")
                # Fold in the first two lab_by_name entries not already
                # cited by the condition dispatch (kept generic — the
                # condition-specific labs would have fired `interp`).
                # Issue #1188 F4 verify 2nd pass: apply the same Nathan
                # gate here so a stray `glucose N mg/dL` that would
                # contradict the paired HbA1c (poorly-controlled patient
                # with normoglycemic reading) is not surfaced under an
                # unrelated condition's fallback line either.
                _hba1c_val_gate: float | None = None
                if lab_by_name:
                    _hba1c_pair = lab_by_name.get("hba1c")
                    if _hba1c_pair is not None:
                        try:
                            _hba1c_val_gate = float(_hba1c_pair[0])
                        except (TypeError, ValueError):
                            _hba1c_val_gate = None
                if lab_by_name:
                    for name in list(lab_by_name.keys())[:2]:
                        v, u = lab_by_name[name]
                        # Nathan gate for glucose in the generic fallback.
                        if name.lower() == "glucose" and _hba1c_val_gate is not None and _hba1c_val_gate >= 8.0:
                            try:
                                _g = float(v)
                                _expected_eag = 28.7 * _hba1c_val_gate - 46.7
                                if _g + 60 < _expected_eag:
                                    continue  # skip Nathan-inconsistent glucose
                            except (TypeError, ValueError):
                                pass
                        # Phase 1c-2 (2026-09-22): the JP p=500 audit
                        # surfaced 863 lowercase lab-name slugs
                        # ("creatinine 0.69 mg/dL、k 4.9 mmol/L") in
                        # outpatient assessment fallback lines. Localise
                        # each name via ``_localize_lab_name`` so JA output
                        # reads 「クレアチニン 0.69 mg/dL、K 4.9 mmol/L」
                        # and EN output canonicalises abbreviation casing.
                        obs_bits.append(f"{_localize_lab_name(name, ctx.target_lang)} {v}{f' {u}' if u else ''}")
                if obs_bits:
                    joined = t("list_sep.serial", lang).join(obs_bits[:4])
                    if is_ja:
                        follow = (
                            f"本日測定 ({joined}) は病態特異的モニタリング項目に該当せず、"
                            f"次回受診時に {label} 特化評価を追加検討。"
                        )
                    else:
                        follow = (
                            f"today's measurements ({joined}) not condition-specific; "
                            f"defer {label} focused review to next visit."
                        )
                    lines.append(f"{i}. {label}: {follow}")
                else:
                    stub = t("control_status.no_measurement_reassess", lang)
                    lines.append(f"{i}. {label}: {stub}")

        # Issue #1183: Assessment previously ignored abnormal vitals that
        # were not paired with a matching chronic condition. Tachycardia
        # was acknowledged in 2.5% of notes (20/790), hypoxemia in 0%
        # (0/1,890), and fever in only 6.7% (2/30). Add a per-vital pass
        # after the condition-dispatch loop so a HR ≥100 / SpO2 <95 /
        # T ≥38 always surfaces in the Assessment prose regardless of
        # the chronic-condition list. hr_f / temp_f / spo2_f are already
        # parsed once at the top of this method (shared with PR B3's
        # observation-aware fallback).
        vital_lines: list[str] = []
        if hr_f is not None and hr_f >= 100:
            if is_ja:
                vital_lines.append(f"頻脈: HR {int(round(hr_f))} 回/分、動悸・脱水評価要。")
            else:
                vital_lines.append(f"Tachycardia: HR {int(round(hr_f))} /min, assess volume + arrhythmia.")
        if spo2_f is not None and spo2_f < 95:
            severity_ja = "重度低酸素症" if spo2_f < 90 else "低酸素症"
            severity_en = "severe hypoxemia" if spo2_f < 90 else "hypoxemia"
            if is_ja:
                vital_lines.append(f"{severity_ja}: SpO2 {spo2_f:.0f}%、酸素化評価要。")
            else:
                vital_lines.append(f"{severity_en.capitalize()}: SpO2 {spo2_f:.0f}%, oxygenation review needed.")
        if temp_f is not None and temp_f >= 38.0:
            if is_ja:
                vital_lines.append(f"発熱: T {temp_f:.1f}°C、感染源精査要。")
            else:
                vital_lines.append(f"Fever: T {temp_f:.1f}°C, evaluate for infection source.")
        # Append with continued numbering so the Assessment reads as one list.
        start = len(lines) + 1
        for j, extra in enumerate(vital_lines):
            lines.append(f"{start + j}. {extra}")

        if not lines:
            return ""
        return "\n".join(lines)

    def _build_outpatient_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP plan from outpatient_soap_template.plan_<lang>.

        v9 (2026-08-17) density fix — v8 emitted only continuation-med list
        (英字 + "他 N 剤"). This version composes a multi-line plan
        including continuation Rx (JA localized), today's discharge_prescription
        (if any), procedures ordered today, and a follow-up sentinel.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.generic_plan", lang)

        soap = self._get_soap_template(ctx)
        if soap is not None:
            text = _pick_localized(soap, "plan", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.outpatient_soap_template.plan_{lang}")
                # Issue #1180: the YAML `plan_<lang>` is a per-condition
                # constant, which made the Plan section byte-identical
                # across every visit in 92.1% of patients. Append a
                # per-encounter varying follow-up line so consecutive
                # visits show different cadence (band chosen per chronic
                # condition, index rotated deterministically off
                # (patient_id, encounter_id)). Preserves the YAML content
                # as the baseline; only adds a new tail line.
                tail = self._compose_follow_up_line(ctx)
                if tail:
                    facts.append("encounter_protocol.next_visit_interval")
                    return f"{text}\n{tail}", facts
                return text, facts

        # v9 multi-line composition (density fix)
        lines: list[str] = []
        continuation = self._compose_current_medications_line(ctx)
        if continuation:
            lines.append(continuation)
            facts.append("ctx.patient.current_medications")

        today_rx = self._compose_today_prescription_line(ctx)
        if today_rx:
            lines.append(today_rx)
            facts.append("ctx.discharge_medications")

        today_procs = self._compose_today_procedures_line(ctx)
        if today_procs:
            lines.append(today_procs)
            facts.append("ctx.procedures.today")

        follow_up = self._compose_follow_up_line(ctx)
        if follow_up:
            lines.append(follow_up)
            facts.append("encounter_protocol.next_visit_interval")

        # Issue #1066: append drug_safety avoidance/substitution reasoning
        # so outpatient chronic follow-up notes carry the same visibility
        # as inpatient progress notes.
        skips_addendum = _render_safety_skips_line(getattr(ctx, "safety_skips", None) or [], lang)
        if skips_addendum:
            lines.append(skips_addendum)
            facts.append("ctx.safety_skips")

        if lines:
            return "\n".join(lines), facts

        return fallback, facts

    def _compose_today_prescription_line(self, ctx: NarrativeContext) -> str:
        """Today's outpatient Rx (from ctx.discharge_medications when the
        outpatient visit closes with a fresh prescription). v9 density fix."""
        rx = list(getattr(ctx, "discharge_medications", None) or [])
        if not rx:
            return ""
        lang = ctx.target_lang
        parts: list[str] = []
        for m in rx[:8]:
            drug = _o(m, "drug_name", "") or ""
            if not drug:
                continue
            drug, _cat = strip_protocol_prefix(drug)
            if lang == "ja":
                # JA-locale drug-name katakana lookup (locale-specific
                # data pipeline, same rationale as _compose_ap_plan_from_state).
                from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

                drug = _localize_drug_name(drug, "JP")
            dose = _o(m, "dose", "") or ""
            route = _o(m, "route", "") or ""
            freq = _o(m, "frequency", "") or ""
            days = _o(m, "days_supply", None)
            bits: list[str] = [str(drug)]
            if dose:
                bits.append(str(dose))
            if route:
                bits.append(str(route))
            if freq:
                bits.append(str(freq))
            if days:
                bits.append(t("prescription.days_supply_suffix", lang, days=days))
            parts.append(" ".join(bits))
        if not parts:
            return ""
        head = t("outpatient.today_prescription_head", lang) + (t("list_sep.semicolon", lang).join(parts))
        return head

    def _compose_today_procedures_line(self, ctx: NarrativeContext) -> str:
        """Procedures / labs ordered today for the outpatient visit.
        v9 density fix — v8 P section ignored today's activity entirely."""
        procs = list(ctx.procedures or [])
        if not procs:
            return ""
        lang = ctx.target_lang
        names: list[str] = []
        seen: set[str] = set()
        for pr in procs[:6]:
            nm = _o(pr, "procedure_name", None) or _o(pr, "name", None) or _o(pr, "display_name", None)
            if not nm or nm in seen:
                continue
            seen.add(nm)
            names.append(str(nm))
        if not names:
            return ""
        head = t("outpatient.today_workup_head", lang) + t("list_sep.semicolon", lang).join(names)
        return head

    def _compose_follow_up_line(self, ctx: NarrativeContext) -> str:
        """Follow-up guidance from encounter_protocol (未確定 — treat as
        planning, not fact). v9 density fix.

        Issue #1180: in 92.1% of patients the Plan section was byte-identical
        across every outpatient visit because the sentinel `1 か月後` and
        the per-condition YAML `plan_ja` never varied by visit. Add a
        per-encounter deterministic rotation over a small band of
        clinically-plausible intervals so consecutive visits show
        different follow-up cadence.
        """
        ep = ctx.encounter_protocol
        interval = _o(ep, "next_visit_interval_days", None) if ep is not None else None
        lang = ctx.target_lang
        if interval:
            try:
                d = int(interval)
                return t("prescription.next_visit", lang, days=d)
            except (TypeError, ValueError):
                pass
        # #1180: per-condition follow-up interval bands (in days). Reflects
        # AHA / JDS / JSH / KDIGO / GOLD guideline windows for stable chronic
        # follow-up. Bands are intentionally short (3-5 options) so a
        # patient's own sequence of visits reads with clinical variation
        # rather than as identical template text.
        _follow_up_bands_days: dict[str, tuple[int, ...]] = {
            "I10": (30, 60, 90),  # HTN stable — 1-3 mo
            "E10": (60, 90),  # T1DM — 2-3 mo
            "E11": (60, 90),  # T2DM — 2-3 mo
            "E78": (90, 120, 180),  # dyslipidemia — 3-6 mo
            "N18": (30, 60, 90),  # CKD — 1-3 mo
            "J44": (60, 90, 120),  # COPD stable — 2-4 mo
            "J45": (60, 90, 120),  # Asthma stable — 2-4 mo
        }
        # Pick the primary chronic's ICD prefix for the band lookup.
        primary_prefix = ""
        patient = getattr(ctx, "patient", None)
        conditions = _o(patient, "chronic_conditions", []) if patient else []
        for cond in conditions or []:
            code = _o(cond, "code", "") or (cond if isinstance(cond, str) else "")
            if code:
                primary_prefix = code.split(".")[0].upper()
                break
        band = _follow_up_bands_days.get(primary_prefix, (28, 60, 90))
        # Deterministic per-encounter rotation — same encounter always emits
        # the same interval, but consecutive encounters of the same patient
        # cycle through the band.
        enc = getattr(ctx, "encounter", None)
        enc_id = _o(enc, "encounter_id", "") or ""
        pat_id = getattr(patient, "patient_id", "") if patient else ""
        key = f"{pat_id}|{enc_id}|follow_up_interval".encode()
        idx = int.from_bytes(hashlib.sha256(key).digest()[:4], "big") % len(band)
        d = band[idx]
        return t("prescription.next_visit", lang, days=d)

    def _compose_current_medications_line(self, ctx: NarrativeContext) -> str:
        """List the patient's current medications for the Plan section.

        Reads from `ctx.patient.current_medications` (chronic Rx list, populated
        by the population enricher). Returns "" when the list is empty.

        v9 (2026-08-17): drug names JA localization enabled + truncate
        widened to 10 (v8 = 5, which frequently produced "他 N 剤"
        information loss for polypharmacy patients).
        """
        patient = ctx.patient
        meds = _o(patient, "current_medications", []) or []
        if not meds:
            return ""
        lang = ctx.target_lang
        names: list[str] = []
        for m in meds:
            n = _render_home_med_name(m, lang=lang) if not isinstance(m, str) else m
            if isinstance(m, str) and lang == "ja":
                # JA-locale drug-name katakana lookup for str-only entries
                # (dict entries already routed through _render_home_med_name).
                from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

                n = _localize_drug_name(m, "JP")
            if n:
                names.append(str(n))
        if not names:
            return ""
        # v9: widen truncate 5 → 10 to reduce "他 N 剤" information loss.
        # Polypharmacy patients (5+ chronic Rx) are the norm in geriatric
        # outpatient encounters — 10 covers the 90%ile.
        limit = 10
        shown = names[:limit]
        joiner = t("list_sep.serial", lang)
        head = joiner.join(shown)
        if len(names) > limit:
            head += t("current_medications.truncate_suffix", lang, n=len(names) - limit)
        return t("current_medications.line", lang, list=head)

    # ─────────────────────────────────────────────────────────────────
    # α-min-2: ED_NOTE section builders
    # chief_complaint + hpi are shared with ADMISSION_HP (existing builders).
    # triage_details, physical_exam, ed_workup, disposition are new.
    # ─────────────────────────────────────────────────────────────────

    def _get_ed_note_template(self, ctx: NarrativeContext) -> Any | None:
        """Extract ed_note_template from encounter_protocol (or None)."""
        ep = ctx.encounter_protocol
        if ep is None:
            return None
        narrative = _o(ep, "narrative", None)
        if narrative is None:
            return None
        return _o(narrative, "ed_note_template", None)

    def _build_triage_details(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build triage_details from encounter.triage_data."""
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.triage_fallback", lang)

        triage = _o(ctx.encounter, "triage_data", None)
        if triage is None:
            return fallback, facts

        facts.append("encounter.triage_data")
        level = _o(triage, "level", "") or ""
        level_system = _o(triage, "level_system", "") or ""
        arrival_mode = _o(triage, "arrival_mode", "") or ""
        arrival_display = _label("arrival_mode", arrival_mode, lang, fallback=arrival_mode)

        if level_system and level:
            level_text = f"{level_system} Level {level}"
        else:
            level_text = t("control_status.not_assessed", lang)

        mode_display = arrival_display or t("triage_details.arrival_unknown", lang)
        return t("triage_details.line", lang, level=level_text, mode=mode_display), facts

    def _build_ed_physical_exam(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build physical_exam for ED_NOTE from ed_note_template.physical_exam_<lang>.

        v9 (2026-08-17) density fix — when encounter_protocol has no
        ed_note_template.physical_exam, fall back to arrival vitals +
        chief_complaint context rather than emitting a bare
        "特記事項なし".
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.generic_fallback", lang)

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is None:
            # v9 density: assemble from arrival vitals + severity
            vital_line = self._compose_vital_signs_line(ctx)
            if vital_line:
                facts.append("ctx.vitals[0]")
                return t("ed.on_arrival_no_findings", lang, vitals=vital_line), facts
            return fallback, facts

        # physical_exam_<lang> is a structured per-body-system object, not a plain
        # string, so it is resolved inline rather than via _pick_localized (which
        # coerces its result to str). Same locale-routing semantics: warn + fall
        # back on a missing lang-suffixed field instead of silently reading _ja.
        field = f"physical_exam_{lang}"
        pe = _o(ed_tmpl, field, None)
        if pe is None:
            logger.warning("template locale field %s missing on %s", field, type(ed_tmpl).__name__)
            return fallback, facts

        # Collect non-empty body system findings (placeholder-substituted —
        # encounter YAML physical_exam_<lang> strings carry {severity_desc_*}
        # etc.; β-JP-1 chain 1a, same policy as _pick_localized). adv-1 I-2:
        # a part whose unknown placeholders collapsed it to the generic phrase
        # carries no information and would repeat per body system — drop it;
        # if every part collapses, the section-level fallback below fires once.
        systems = ("general", "cardiovascular", "respiratory", "abdominal", "neurological")
        parts = []
        for sys_key in systems:
            val = _o(pe, sys_key, "") or ""
            if val:
                filled = _fill_template_placeholders(str(val), ctx, lang)
                if filled and filled != fallback:
                    parts.append(filled)

        if parts:
            facts.append(f"encounter_protocol.narrative.ed_note_template.{field}")
            sep = t("list_sep.period_space", lang)
            text = sep.join(parts)
            # JA-locale narrative enhancements (Issues #980 + #979). Both
            # are JA-specific by design: the rewrite pools + trigger
            # keywords in _apply_cc_pe_consistency are JP terminology,
            # and the vitals-line prepend is an inpatient-JA convention
            # not yet mirrored elsewhere. Adding a new locale (fr / zh)
            # would need its own contradiction-rewrite pool and
            # vitals-line style — this is a locale-specific data pipeline
            # gate, not a display translation.
            if lang == "ja":
                text, cc_facts = self._apply_cc_pe_consistency(text, ctx)
                facts.extend(cc_facts)
                vitals_line = self._compose_pe_vitals_line(ctx)
                if vitals_line:
                    facts.append(f"ctx.vitals[day_{ctx.day_index}]")
                    text = t("ed_physical_exam.vitals_prepend", lang, vitals=vitals_line, text=text)
            return text, facts

        return fallback, facts

    def _build_ed_workup(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build ed_workup from ed_note_template.ed_workup_summary_<lang>.

        v9 (2026-08-17) density fix — assemble labs + procedures actually
        performed in ED when the encounter YAML has no ed_workup_summary
        template.

        Issue #981 density fix — before falling back to the abnormal-labs
        + procedures-only enumeration (which produced 71% "特記事項なし"
        placeholders in the p=2000 audit because ED encounters rarely
        have flagged lab_results at narrative time), enumerate the orders
        placed during the ED visit: lab test panel names + imaging
        modalities. Orders are the correct source for "what workup was
        run" — lab_results only surface `flag`-annotated abnormals,
        procedures only surface bedside interventions.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.ed_workup_fallback", lang)

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is not None:
            text = _pick_localized(ed_tmpl, "ed_workup_summary", lang, ctx)
            # Issue #981: the ed_note_template values typically contain
            # unresolved substitution placeholders (`{lab_summary_ja}` etc.
            # from the minor-condition ED protocol templates). _pick_localized
            # returns the generic "特記事項なし" phrase in that case, which
            # short-circuited the fall-through to the CIF-driven enumeration
            # below. Treat the generic phrase (and the ED-specific fallback
            # phrase) as "no real template text" and fall through so the
            # orders / procedures / labs section can render instead.
            if text and text not in {_GENERIC_FALLBACK_JA, _GENERIC_FALLBACK_EN, fallback}:
                facts.append(f"encounter_protocol.narrative.ed_note_template.ed_workup_summary_{lang}")
                return text, facts

        # Issue #981 preferred fallback: lift the ED orders (labs / imaging
        # / medications / procedures) placed during this encounter into
        # the narrative. Orders are the accurate answer to "what did we
        # do in the ED"; the pre-#981 abnormal-labs-only path missed the
        # most common cases (blood draw ordered, results normal → labs
        # list empty; laceration repaired with procedure-only orders and
        # no lab_results at all).
        lab_names: list[str] = []
        imaging_names: list[str] = []
        med_names: list[str] = []
        proc_order_names: list[str] = []
        enc_id = _o(ctx.encounter, "encounter_id", "") if ctx.encounter is not None else ""
        seen_labs: set[str] = set()  # panel-key or display-name dedup
        seen_imaging: set[str] = set()
        seen_meds: set[str] = set()
        seen_proc_orders: set[str] = set()
        for order in ctx.orders or []:
            # Scope to the ED encounter only — record.orders can include a
            # follow-up outpatient order carried on the same patient file
            # in richer CIF layouts.
            if enc_id:
                oe = _o(order, "encounter_id", "") or ""
                if oe and oe != enc_id:
                    continue
            otype = _o(order, "order_type", "") or ""
            otype_str = str(otype.value if hasattr(otype, "value") else otype).lower()
            display_raw = _o(order, "display_name", "") or _o(order, "order_code", "")
            if otype_str == "lab":
                key = _o(order, "panel_key", "") or display_raw
                display = _o(order, "panel_key", "") or display_raw
                if key and str(key) not in seen_labs:
                    seen_labs.add(str(key))
                    lab_names.append(str(display))
            elif otype_str == "imaging":
                modality = str(_o(order, "imaging_modality", "") or "").upper()
                display = display_raw or modality
                key = f"{modality}|{display}"
                if display and key not in seen_imaging:
                    seen_imaging.add(key)
                    imaging_names.append(str(display))
            elif otype_str == "medication":
                if display_raw and str(display_raw) not in seen_meds:
                    seen_meds.add(str(display_raw))
                    med_names.append(str(display_raw))
            elif otype_str == "procedure":
                if display_raw and str(display_raw) not in seen_proc_orders:
                    seen_proc_orders.add(str(display_raw))
                    proc_order_names.append(str(display_raw))
        parts: list[str] = []
        if lab_names:
            # Phase 1c-4 (2026-09-23): localise lab / panel tokens
            # ("Creatinine" / "CBC" / "Urinalysis" / "Total_bilirubin"
            # etc.) via ``_localize_lab_name``. Pre-fix, the JA emission
            # embedded English tokens verbatim under 「検査:」.
            lab_display = [_localize_lab_name(n, ctx.target_lang) for n in lab_names[:8]]
            parts.append(t("ed_workup.labs_head", lang) + t("list_sep.serial", lang).join(lab_display))
        if imaging_names:
            # Phase 1c-4 (2026-09-23): localise imaging codes
            # ("Chest_Xray_PA_Lateral" / "CT_Head" / etc.) via
            # ``_localize_imaging``. Handles both underscore-slug and
            # spaced-name variants (semantic dedup).
            imaging_display = [_localize_imaging(n, ctx.target_lang) for n in imaging_names[:6]]
            parts.append(t("ed_workup.imaging_head", lang) + t("list_sep.serial", lang).join(imaging_display))
        if med_names:
            # Phase 1c-3 (2026-09-22): localize med display names to
            # katakana JA via the shared ``drug_names_ja`` table used by
            # the FHIR emit path. Pre-fix 183 JP ed_workup lines carried
            # 「投薬: Ibuprofen 400mg、Acetaminophen 500mg」 verbatim.
            med_display = med_names[:6]
            if lang == "ja":
                # JA-locale drug-name katakana lookup (locale-specific
                # data pipeline, same rationale as _compose_ap_plan_from_state).
                try:
                    from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

                    med_display = [_localize_drug_name(m, "JP") or m for m in med_display]
                except Exception:  # noqa: BLE001 — never fail narrative on i18n
                    pass
            parts.append(t("ed_workup.medications_head", lang) + t("list_sep.serial", lang).join(med_display))
        if proc_order_names:
            # Phase 1c-6 (Category L, 2026-09-23): route each procedure
            # order display name through ``_localize_drug_name`` (which
            # also invokes ``_localize_dosage_terms`` internally) on JA
            # output so composite English phrases like
            # 「bronchodilator: Salbutamol 2.5mg nebulizer q4h」 →
            # 「気管支拡張薬: サルブタモール 2.5mg ネブライザー 4時間毎」.
            # Pre-fix ~1,700 leaks in the JP p=10000 audit across
            # bronchodilator / nebulizer / cannula / irrigation /
            # bandage / saline / Salbutamol / Ipratropium / etc. Lazy
            # import + broad except mirrors the med_display handler.
            proc_display = proc_order_names[:6]
            if lang == "ja":
                # JA-locale drug-name katakana lookup (locale-specific
                # data pipeline; same rationale as med_display above).
                try:
                    from clinosim.modules.output.fhir_r4.lib.localization import (
                        _localize_drug_name,
                    )

                    proc_display = [_localize_drug_name(p, "JP") or p for p in proc_display]
                except Exception:  # noqa: BLE001
                    pass
            parts.append(t("ed_workup.procedures_ordered_head", lang) + t("list_sep.serial", lang).join(proc_display))

        # Enrich with any flagged abnormals (kept from the v9 path — an
        # abnormal Cr / K reading is high-signal even when the panel it
        # came from is already listed above).
        #
        # Phase 1c-5 (2026-09-23): sibling of the progress_note
        # ``本日の検査所見:`` fix — route lab_name through
        # ``_localize_lab_name`` and flag through ``_localize_lab_flag``
        # so JA emits 「クレアチニン 5.19 mg/dL [H]、BUN 143.8 mg/dL [H]」
        # rather than 「Creatinine 5.19 mg/dL [H]、BUN 143.8 mg/dL [H]」.
        # Pre-fix the JP p=10000 audit surfaced ~2,000 raw-English lab
        # names in ed_workup ``異常値:`` lines (Creatinine / Albumin /
        # Glucose / Lactate / Troponin_I / …).
        abn_labs = []
        for lab in (ctx.lab_results or [])[:8]:
            flag = _o(lab, "flag", None)
            if not flag:
                continue
            name = _o(lab, "lab_name", "") or ""
            val = _o(lab, "value", None)
            unit = _o(lab, "unit", "") or ""
            if name and val is not None:
                disp_name = _localize_lab_name(name, ctx.target_lang)
                disp_flag = _localize_lab_flag(flag, ctx.target_lang)
                abn_labs.append(f"{disp_name} {val} {unit} [{disp_flag}]")
        if abn_labs:
            parts.append(t("ed_workup.abnormal_head", lang) + t("list_sep.serial", lang).join(abn_labs[:4]))

        # Bedside procedures / imaging descriptions.
        procs = []
        for pr in (ctx.procedures or [])[:4]:
            nm = _o(pr, "procedure_name", None) or _o(pr, "name", None)
            if nm:
                procs.append(str(nm))
        if procs:
            parts.append(t("ed_workup.procedures_head", lang) + t("list_sep.serial", lang).join(procs))
        if parts:
            fact_sources = []
            if lab_names or imaging_names or med_names or proc_order_names:
                fact_sources.append("ctx.orders.ed")
            if abn_labs:
                fact_sources.append("ctx.lab_results.abnormal")
            if procs:
                fact_sources.append("ctx.procedures.ed")
            facts.extend(fact_sources)
            return t("list_sep.period_space", lang).join(parts), facts

        return fallback, facts

    def _build_ed_disposition(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build disposition from ed_note_template.disposition_<lang>.

        v9 (2026-08-17) density fix — infer disposition from encounter
        outcome (discharge_disposition / admission linkage) when
        ed_note_template is absent, rather than emitting a bare
        "帰宅または入院加療".

        Issue #981 density fix — attach a reasoning phrase drawn from
        the admit-diagnosis / disease_protocol / acuity so every
        disposition sentence reads as "自宅退院（JTAS レベル 4、症状軽度）"
        instead of the bare "自宅退院。症状経過に応じて再受診指示。" that
        the pre-#981 code produced (68% of ED docs).
        """
        facts: list[str] = []
        lang = ctx.target_lang
        fallback = t("fallback.disposition_fallback", lang)

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is not None:
            text = _pick_localized(ed_tmpl, "disposition", lang, ctx)
            # Issue #981: same guard as ed_workup — unresolved
            # `{disposition_display_ja}` placeholder in the ED protocol
            # template returns the generic phrase, which short-circuited
            # the encounter-field fallback. Treat it as "no real template
            # text" and fall through.
            if text and text not in {_GENERIC_FALLBACK_JA, _GENERIC_FALLBACK_EN, fallback}:
                facts.append(f"encounter_protocol.narrative.ed_note_template.disposition_{lang}")
                return text, facts

        # v9 density fallback: infer from encounter fields
        enc = ctx.encounter
        if enc is not None:
            dispo = str(_o(enc, "discharge_disposition", None) or _o(enc, "outcome", None) or "").lower()
            adm = _o(enc, "admit_to_ward", None) or bool(_o(enc, "admitted", False))
            facts.append("ctx.encounter.disposition")
            reason = self._ed_disposition_reason(ctx, lang)
            jtas_level = self._ed_triage_level(ctx)

            if adm or dispo == "hosp":
                # Deprecated `admit_to_ward` (used by legacy fixtures) is
                # normalized to the same "admitted" path as an inbound
                # transfer disposition.
                tmpl = t("fallback.ed_disposition_admission", lang)
                return tmpl.format(reason=reason), facts
            if dispo == "exp":
                return (t("fallback.ed_disposition_expired", lang)), facts
            if dispo in ("other-hcf", "snf"):
                tmpl = t("fallback.ed_disposition_transfer", lang)
                return tmpl.format(reason=reason), facts
            if dispo == "home":
                tmpl = t("fallback.ed_disposition_home", lang)
                return tmpl.format(level=jtas_level, reason=reason), facts

        return fallback, facts

    @staticmethod
    def _ed_triage_level(ctx: NarrativeContext) -> str:
        """Extract the JTAS triage level (1-5) from the encounter, or "N/A".

        Encounters that skipped triage_enricher (test fixtures, non-JP
        cohorts pre-#941) leave ``triage_data`` unset; falls back to a
        severity → JTAS mapping so the disposition line still carries an
        integer rather than blank.
        """
        enc = ctx.encounter
        if enc is None:
            return "-"
        triage = _o(enc, "triage_data", None)
        if triage is not None:
            level = _o(triage, "level", "") or ""
            if level:
                return str(level)
        severity = str(_o(enc, "severity", "") or ctx.severity or "").lower()
        # Rough clinical mapping: severe→2, moderate→3, mild→4. Matches
        # JTAS's own severity buckets closely enough for a fallback
        # sentence.
        return {"severe": "2", "moderate": "3", "mild": "4"}.get(severity, "-")

    @staticmethod
    def _ed_disposition_reason(ctx: NarrativeContext, lang: str) -> str:
        """Return a short reasoning phrase (admit dx / CC / acuity) for #981.

        Never returns empty — an empty reason would collapse the
        parenthetical to "（）" and read worse than the pre-fix bare
        disposition. Fall-through priority:

          1. ``encounter.chief_complaint_<lang>`` / ``chief_complaint`` –
             the specific complaint the ED chart already knows about.
          2. ``disease_protocol.chief_complaint`` – matches when the
             encounter did not override.
          3. ``encounter.severity`` / ``ctx.severity`` acuity keyword.
          4. Locale-appropriate generic ("症状に応じて対応" / "clinical
             judgment").
        """
        from clinosim.locale.loader import resolve_localized_display

        enc = ctx.encounter
        if enc is not None:
            # Preferred slot ``chief_complaint_<lang>``; base
            # ``chief_complaint`` is the language-agnostic fallback.
            preferred_key = f"chief_complaint_{lang}"
            cc = _o(enc, preferred_key, "") or _o(enc, "chief_complaint", "")
            if cc:
                return str(cc)
        if ctx.disease_protocol is not None:
            proto_cc = _o(ctx.disease_protocol, "chief_complaint", None)
            if isinstance(proto_cc, dict):
                val = resolve_localized_display(proto_cc, lang, fallback="")
                if val:
                    return str(val)
            elif proto_cc:
                return str(proto_cc)
        severity = str(_o(enc, "severity", "") or ctx.severity or "").lower() if enc is not None else ""
        acuity_label = _label("ed_acuity_reason", severity, lang, fallback="")
        if acuity_label:
            return acuity_label
        return t("control_status.clinical_judgment", lang)

    # ─────────────────────────────────────────────────────────────────
    # Fallback helpers
    # ─────────────────────────────────────────────────────────────────

    def _resolve_physical_exam(self, ctx: NarrativeContext, archetype: str, day_index: int) -> dict[str, Any]:
        """Multi-step fallback chain for per-day physical exam findings.

        Fallback priority:
          1. disease_protocol.narrative.physical_exam_findings[archetype][day_N] (Pydantic)
          2. reference_data.findings[disease_id][archetype][day_N]
          3. Steps 1-2 at prior days (N-1 ... 0)
          4. baseline.reference_data[archetype][day_N] with same fallback
          5. Returns {} (caller uses generic phrase)
        """
        # Try days from current down to 0
        candidate_days = list(range(day_index, -1, -1))

        # Source 1+2: disease protocol narrative + reference_data.findings
        disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
        narrative = _o(ctx.disease_protocol, "narrative", None) if ctx.disease_protocol else None
        pex_data = load_physical_exam_findings()

        for day in candidate_days:
            day_key = f"day_{day}"

            # Source 1: disease_protocol.narrative.physical_exam_findings[archetype][day_N]
            if narrative is not None:
                proto_pex = _o(narrative, "physical_exam_findings", {})
                if isinstance(proto_pex, dict):
                    arch_day = proto_pex.get(archetype, {})
                    if isinstance(arch_day, dict):
                        day_findings = arch_day.get(day_key)
                        if day_findings is not None:
                            return self._pydantic_day_findings_to_dict(day_findings)

            # Source 2: reference_data.findings[disease_id][archetype][day_N]
            if disease_id:
                ref_findings = pex_data.get("findings", {})
                disease_findings = ref_findings.get(disease_id, {})
                arch_findings = disease_findings.get(archetype, {})
                day_entry = arch_findings.get(day_key)
                if day_entry is not None:
                    return day_entry if isinstance(day_entry, dict) else {}

        # Source 3+4: baseline reference data
        baseline = pex_data.get("baseline", {})

        # Try archetype directly
        arch_baseline = baseline.get(archetype, {})
        for day in candidate_days:
            day_key = f"day_{day}"
            day_entry = arch_baseline.get(day_key)
            if day_entry is not None:
                return day_entry if isinstance(day_entry, dict) else {}

        # Try similar archetypes (graceful fallback across archetype names)
        for alt_arch, alt_data in baseline.items():
            if not isinstance(alt_data, dict):
                continue
            for day in candidate_days:
                day_key = f"day_{day}"
                day_entry = alt_data.get(day_key)
                if day_entry is not None:
                    return day_entry if isinstance(day_entry, dict) else {}

        return {}

    def _resolve_daily_trajectory(self, ctx: NarrativeContext, archetype: str, day_index: int) -> dict[str, str]:
        """Fallback chain for SOAP-structured daily trajectory.

        Fallback priority:
          1. disease_protocol.course_archetypes[archetype].daily_trajectory[day_N]
          2. Same at prior days (N-1 ... 0)
          3. Generic SOAP entry (always succeeds)
        """
        traj, _ = self._resolve_daily_trajectory_with_source(ctx, archetype, day_index)
        return traj

    def _resolve_daily_trajectory_with_source(
        self, ctx: NarrativeContext, archetype: str, day_index: int
    ) -> tuple[dict[str, str], str]:
        """Like _resolve_daily_trajectory but also returns source path for facts_used.

        Returns (trajectory_dict, source_path) where source_path is an empty string
        when the generic fallback is used (not from disease YAML).
        """
        proto = ctx.disease_protocol
        if proto is None:
            return self._generic_trajectory(ctx), ""

        course_archetypes = _o(proto, "course_archetypes", {}) or {}
        archetype_data = course_archetypes.get(archetype) or {}

        daily_trajectory: dict[str, Any] = {}
        if isinstance(archetype_data, dict):
            daily_trajectory = archetype_data.get("daily_trajectory") or {}
        else:
            # Pydantic model — try attribute
            daily_trajectory = _o(archetype_data, "daily_trajectory", {}) or {}

        candidate_days = list(range(day_index, -1, -1))
        for day in candidate_days:
            day_key = f"day_{day}"
            entry = daily_trajectory.get(day_key)
            if entry is not None:
                source = f"disease_protocol.course_archetypes.{archetype}.daily_trajectory.{day_key}"
                if isinstance(entry, dict):
                    return entry, source
                # Pydantic DailyTrajectoryEntry
                return {
                    "subjective": _o(entry, "subjective", ""),
                    "objective": _o(entry, "objective", ""),
                    "assessment": _o(entry, "assessment", ""),
                    "plan": _o(entry, "plan", ""),
                }, source

        # No trajectory entry found — return generic with no source
        return self._generic_trajectory(ctx), ""

    def _generic_trajectory(self, ctx: NarrativeContext) -> dict[str, str]:
        """Return generic SOAP entry for when no trajectory data is available."""
        lang = ctx.target_lang
        return {
            "subjective": t("fallback.generic_fallback", lang),
            "objective": t("fallback.generic_fallback", lang),
            "assessment": t("fallback.generic_assessment", lang),
            "plan": t("fallback.generic_plan", lang),
        }

    def _resolve_discharge_instructions(self, ctx: NarrativeContext) -> dict[str, dict[str, str]]:
        """Merge baseline + disease_specific discharge instructions.

        disease_specific entries take precedence over baseline for shared keys.
        Returns a flat dict {key: {en: "...", ja: "..."}}.
        """
        di_data = load_discharge_instructions()
        baseline: dict[str, Any] = di_data.get("baseline") or {}
        disease_specific: dict[str, Any] = di_data.get("disease_specific") or {}

        # Start with baseline
        merged: dict[str, dict[str, str]] = {}
        for key, entry in baseline.items():
            if isinstance(entry, dict):
                merged[key] = dict(entry)

        # Override / supplement with disease_specific
        disease_id = _o(ctx.disease_protocol, "disease_id", None) if ctx.disease_protocol else None
        if disease_id and disease_id in disease_specific:
            overrides = disease_specific[disease_id] or {}
            for key, entry in overrides.items():
                if isinstance(entry, dict):
                    merged[key] = dict(entry)

        # Also check disease YAML's own discharge_instructions (highest priority)
        narrative = _o(ctx.disease_protocol, "narrative", None) if ctx.disease_protocol else None
        if narrative is not None:
            proto_di = _o(narrative, "discharge_instructions", None)
            if proto_di is not None:
                _di_sections = ("follow_up", "activity", "medications", "emergency", "diet_lifestyle")
                for section in _di_sections:
                    sec_data = _o(proto_di, section, {})
                    if isinstance(sec_data, dict) and (sec_data.get("en") or sec_data.get("ja")):
                        merged[section] = dict(sec_data)

        return merged

    # ─────────────────────────────────────────────────────────────────
    # DEATH_CERTIFICATE sections (LOINC 64297-5) — Issue #961
    # ─────────────────────────────────────────────────────────────────
    # 医師法第 20 条 legally-defined fields on the 死亡診断書 form; each
    # section renders template-only text (stage2_strategy=template_only)
    # because these fields are structured facts (ICD code, boolean flags,
    # controlled-vocabulary values) rather than free-form narrative.

    def _dc_resolve_primary_cause(self, ctx: NarrativeContext) -> tuple[str, str, list[str]]:
        """Resolve (icd_code, localized_display, facts_used) for the primary
        cause of death.

        Priority chain:
          1. clinical_diagnosis.discharge_diagnosis_code (the final ICD-10
             recorded at the terminating encounter — what the physician
             would enter as 直接死因 on the 死亡診断書).
          2. clinical_diagnosis.admission_diagnosis_code (fallback for
             encounters where the discharge dx was never recoded because
             death happened early in the admission).

        Returns ("", "", []) when neither code is available — the caller
        renders a never-fabricate fallback phrase.
        """
        facts: list[str] = []
        diagnoses = ctx.diagnoses or []
        primary = diagnoses[0] if diagnoses else None
        if primary is None:
            return "", "", facts
        code = _o(primary, "discharge_diagnosis_code", "") or _o(primary, "admission_diagnosis_code", "") or ""
        if not code:
            return "", "", facts
        system = (
            _o(primary, "discharge_diagnosis_system", "")
            or _o(primary, "admission_diagnosis_system", "")
            or system_key_for("diagnosis", ctx.locale.upper())
        )
        display = code_lookup(system, code, ctx.target_lang) if code else ""
        facts.append("ctx.diagnoses[0].discharge_diagnosis_code")
        return code, (display or code), facts

    def _build_dc_immediate_cause(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """直接死因 / Immediate cause of death.

        Sourced from the encounter's final ICD-10 diagnosis. When missing
        (no clinical_diagnosis on record), emits a never-fabricate marker.
        """
        lang = ctx.target_lang
        code, display, facts = self._dc_resolve_primary_cause(ctx)
        if not code:
            return t("death_cert.immediate_cause_not_documented", lang), facts
        return t("death_cert_line.immediate_cause", lang, display=display, code=code), facts

    def _build_dc_duration_of_immediate_cause(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """直接死因までの期間 / Time from onset of the immediate cause to death.

        Real 死亡診断書 forms carry a short prose phrase whose granularity
        varies with disease trajectory — acute events on the day of
        admission are documented in hours, subacute pneumonias in days,
        chronic decompensations in weeks. Template renders one of five
        duration buckets keyed on encounter LOS + disease pattern
        (acute / chronic / unknown, from the terminal ICD chapter),
        giving the LLM refinement pass a clinically-defensible seed to
        polish.

        Never fabricates a pre-admission onset date — clinosim CIF does
        not carry a first-onset date for acute events, so the template
        anchors on the observed admission-to-death interval and states
        so explicitly.
        """
        lang = ctx.target_lang
        facts: list[str] = ["ctx.los_days"]
        los = ctx.los_days or 0
        code, display, _ = self._dc_resolve_primary_cause(ctx)
        pattern = self._dc_disease_pattern(code)
        if code:
            facts.append("ctx.diagnoses[0].discharge_diagnosis_code")

        if los <= 0:
            hours = self._dc_admission_to_discharge_hours(ctx)
            if hours is not None and 0 < hours < 24:
                bucket = "hours"
                bucket_hours = max(1, int(round(hours)))
            else:
                bucket = "same_day"
                bucket_hours = 0
        elif los <= 7:
            bucket = "days"
            bucket_hours = 0
        elif los <= 28:
            bucket = "weeks"
            bucket_hours = 0
        else:
            bucket = "long"
            bucket_hours = 0

        return self._dc_duration_phrase(bucket, los, bucket_hours, pattern, display or "", lang), facts

    def _dc_disease_pattern(self, icd_code: str) -> str:
        """Return an "acute" / "chronic" / "unknown" pattern from ICD-10.

        Uses ICD-10 chapter conventions used elsewhere in clinosim: I21/
        I26/J18/A41 etc. are acute; I25/E11/N18/J44 chronic. "unknown"
        for anything not in these well-known buckets — the caller emits
        a neutral phrase in that case rather than fabricating a
        trajectory.
        """
        if not icd_code:
            return "unknown"
        stem = icd_code.split(".")[0]
        acute = frozenset(
            {
                "I21",  # 急性心筋梗塞
                "I22",  # 再発急性心筋梗塞
                "I26",  # 肺塞栓症
                "I46",  # 心停止
                "I50",  # 心不全（急性増悪）
                "I63",  # 脳梗塞
                "I61",  # 脳出血
                "J18",  # 肺炎
                "J96",  # 呼吸不全
                "A41",  # 敗血症
                "N17",  # 急性腎障害
                "R57",  # ショック
            }
        )
        chronic = frozenset(
            {
                "I25",  # 慢性虚血性心疾患
                "N18",  # 慢性腎臓病
                "J44",  # COPD
                "E11",  # 2型糖尿病
                "K74",  # 肝硬変
                "C34",  # 肺癌
                "C25",  # 膵癌
                "C22",  # 肝癌
                "C18",  # 大腸癌
            }
        )
        if stem in acute:
            return "acute"
        if stem in chronic:
            return "chronic"
        return "unknown"

    def _dc_admission_to_discharge_hours(self, ctx: NarrativeContext) -> float | None:
        """Return the observed admission-to-discharge duration in hours, or
        ``None`` when either datetime is missing. Enables the duration
        section to pick hour granularity on same-day deaths."""
        adm = _o(ctx.encounter, "admission_datetime", None)
        dis = _o(ctx.encounter, "discharge_datetime", None)
        if not adm or not dis:
            return None
        try:
            a = adm if isinstance(adm, datetime) else datetime.fromisoformat(str(adm))
            d = dis if isinstance(dis, datetime) else datetime.fromisoformat(str(dis))
            secs = (d - a).total_seconds()
            return max(0.0, secs / 3600.0)
        except Exception:
            return None

    def _dc_duration_phrase(
        self,
        bucket: str,
        los: int,
        hours: int,
        pattern: str,
        disease_label: str,
        lang: str,
    ) -> str:
        """Compose the JP-CLINS 直接死因までの期間 phrase from bucket +
        pattern + disease-label. Phase 1d-36: unified the previously
        per-lang _dc_duration_phrase_ja / _en pair via the shared
        ``dc_duration`` phrase catalog. Fluency reads like a JP
        physician's short-form note on the 死亡診断書 form; EN
        translations mirror the semantics.
        """
        prefix = t("dc_duration.prefix", lang)
        chronic_lead = t("dc_duration.chronic_lead", lang) if pattern == "chronic" else ""
        suffix = t("dc_duration.disease_suffix", lang, disease=disease_label) if disease_label else ""
        if bucket == "hours":
            body = t("dc_duration.body_hours", lang, hours=hours, suffix=suffix)
        elif bucket == "same_day":
            body = t("dc_duration.body_same_day", lang, suffix=suffix)
        elif bucket == "days":
            body = t("dc_duration.body_days", lang, los=los, suffix=suffix)
        elif bucket == "weeks":
            weeks = max(1, round(los / 7))
            body = t("dc_duration.body_weeks", lang, weeks=weeks, los=los, suffix=suffix)
        else:  # "long"
            weeks = max(4, round(los / 7))
            body = t("dc_duration.body_long", lang, weeks=weeks, suffix=suffix)
        tail = t("dc_duration.tail", lang)
        return f"{prefix}{chronic_lead}{body}{tail}"

    def _build_dc_underlying_cause(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """原死因 / Underlying cause of death.

        Same code as the immediate cause when the encounter has only a
        single diagnosis (mirrors how a simple death certificate lists the
        same ICD-10 on both lines). Uses the ICD-10 chapter root (letter +
        first two digits) as the underlying-cause bucket when the discharge
        dx has a decimal specifier.
        """
        lang = ctx.target_lang
        code, display, facts = self._dc_resolve_primary_cause(ctx)
        if not code:
            return t("death_cert.underlying_cause_not_documented", lang), facts
        chapter = code.split(".")[0] if "." in code else code
        return t("death_cert_line.underlying_cause", lang, display=display, chapter=chapter), facts

    def _build_dc_contributing_conditions(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """影響を及ぼした傷病名 / Contributing conditions.

        Real 死亡診断書 physicians write this field as a short prose
        paragraph explaining WHICH chronic comorbidities plausibly
        contributed to the terminal event — a bare list is undersells
        the clinical linkage. Template enriches with:
          - Lead-in phrase naming the count (単発の / 複数の)
          - The comorbidity list (up to 5) with codes
          - A neutral causal-context sentence tying them to the terminal
            event (using the disease pattern from the primary cause)
          - Optionally, any in-hospital complications observed
            (from ctx.complications_occurred / working_diagnoses) that
            documented a concrete secondary event.

        Never fabricates a comorbidity: "該当なし / none documented" when
        the patient has no chronic history and no in-hospital
        complication was recorded.
        """
        lang = ctx.target_lang
        facts: list[str] = []
        conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
        parts: list[str] = []
        for c in list(conds)[:5]:
            code_val = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code_val:
                continue
            system = _o(c, "system", "") or system_key_for("diagnosis", ctx.locale.upper())
            display = code_lookup(system, code_val, lang) or code_val
            parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=code_val))
        if parts:
            facts.append("ctx.patient.chronic_conditions")

        # In-hospital complications add concrete detail beyond baseline
        # comorbidities (the daily loop records these on the record).
        comp_tokens = list(getattr(ctx, "complications_occurred", []) or [])[:3]
        if comp_tokens:
            facts.append("ctx.complications_occurred")

        primary_code, _display, _ = self._dc_resolve_primary_cause(ctx)
        pattern = self._dc_disease_pattern(primary_code)

        if not parts and not comp_tokens:
            return t("death_cert.contributing_none", lang), facts

        prefix = t("dc_contributing.prefix", lang)
        # JA joins the code-labelled parts with 「、」, EN with "; ".
        # ``list_sep.semicolon`` matches both.
        list_part = t("list_sep.semicolon", lang).join(parts) if parts else ""
        connector = ""
        if list_part:
            connector = t(
                "dc_contributing.connector_chronic" if pattern == "chronic" else "dc_contributing.connector_comorbid",
                lang,
            )
        comp_part = ""
        if comp_tokens:
            comp_sep = t("list_sep.serial", lang)
            comp_labels = comp_sep.join(str(tok).replace("_", " ") for tok in comp_tokens)
            comp_part = t("dc_contributing.comp_part", lang, comp_labels=comp_labels)
        if list_part:
            tail = t("dc_contributing.tail_with_list", lang)
            return t(
                "dc_contributing.compound_line",
                lang,
                prefix=prefix,
                list_part=list_part,
                connector=connector,
                comp_part=comp_part,
                tail=tail,
            ), facts
        # No list_part → prefix + comp_part only. EN strips leading whitespace.
        return f"{prefix}{comp_part.strip() if lang != 'ja' else comp_part}", facts

    def _build_dc_manner_of_death(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """死因の種類 / Manner of death.

        MHLW 死亡診断書 offers three top-level buckets: 病死及び自然死
        (natural/disease), 外因死 (external), and 不詳の死 (unknown).
        clinosim currently models only disease-driven inpatient mortality
        (no trauma/accident/suicide life events wired in), so the default
        is 病死及び自然死. Future external_cause markers would extend this
        builder.
        """
        lang = ctx.target_lang
        facts: list[str] = []
        return t("death_cert_line.manner_natural", lang), facts

    def _build_dc_autopsy_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """解剖の有無 / Autopsy status.

        Real JP acute-care hospitals perform autopsy on ~5-10% of
        deaths (JMA / MHLW annual statistics). clinosim samples per
        encounter with SHA256 (encounter_id + patient_id + "autopsy")
        so the value is RNG-neutral (does not consume the master RNG)
        and deterministic across regens — same encounter always gets
        the same autopsy status. Cutoff p=0.07 gives ~7% autopsy rate,
        matching the low end of the real-world range.

        The paired DDS section ``autopsy_status_and_findings`` uses the
        same SHA256 helper so the two documents agree per encounter
        (feedback_dr_conclusion_code_single_walk — one source for a
        cross-document invariant).
        """
        lang = ctx.target_lang
        facts: list[str] = ["encounter.id::autopsy_sample"]
        performed = _autopsy_performed_sha256(ctx)
        if performed:
            return t("autopsy.status_yes", lang), facts
        return t("autopsy.status_no", lang), facts

    # ─────────────────────────────────────────────────────────────────
    # DEATH_DISCHARGE_SUMMARY sections (LOINC 18842-5 / title 死亡退院
    # サマリー) — Issue #961 extension
    # ─────────────────────────────────────────────────────────────────
    # Real JP hospital deceased-inpatient discharges use a specialized
    # 死亡退院サマリー template with eight sections. Every builder here
    # produces a clinically-defensible narrative from CIF (admission /
    # discharge datetimes, LOS, primary + working diagnoses, complications,
    # SHA256-sampled autopsy). Templates are the authoritative base
    # layer per the coordinator's design principle (2026-08-30): a run
    # without any LLM configured emits a defensible narrative; the LLM
    # refinement pass polishes phrasing on top when available (see
    # llm_service/prompts/{ja,en}/death_discharge_summary_*.yaml).

    def _dds_severity(self, severity: str, lang: str) -> str:
        """Return the localized severity label for the DDS narrative.

        Phase 1d-26: was ``_dds_severity_ja`` / ``_dds_severity_en``
        pair. Vocabulary moved to
        ``narrative_labels.yaml::dds_severity``. For a value outside
        the ``mild`` / ``moderate`` / ``severe`` bucket, JA falls back
        to 中等症 (the JA-specific default), other locales use the
        capitalised raw token.
        """
        key = severity or "moderate"
        default = "中等症" if lang == "ja" else key.capitalize()
        return _label("dds_severity", key, lang, fallback=default)

    def _build_dds_admission_state(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """入院時病状 / Clinical state at admission.

        Renders admission datetime + severity + admission diagnosis code
        into a short scene-setting paragraph. Grounds the terminal
        narrative in the observed baseline so the LLM refinement pass
        cannot drift toward fabricated "healthy on admission" framing.
        """
        lang = ctx.target_lang
        facts: list[str] = []
        adm_dt = _o(ctx.encounter, "admission_datetime", None)
        adm_str = str(adm_dt)[:16].replace("T", " ") if adm_dt else ""
        diagnoses = ctx.diagnoses or []
        primary = diagnoses[0] if diagnoses else None
        adm_code = _o(primary, "admission_diagnosis_code", "") if primary else ""
        adm_sys = _o(primary, "admission_diagnosis_system", "") if primary else ""
        adm_disp = ""
        if adm_code:
            adm_disp = (
                code_lookup(adm_sys or system_key_for("diagnosis", ctx.locale.upper()), adm_code, lang) or adm_code
            )
            facts.append("ctx.diagnoses[0].admission_diagnosis_code")
        if adm_dt:
            facts.append("ctx.encounter.admission_datetime")
        severity = ctx.severity or "moderate"
        sev = self._dds_severity(severity, lang)
        when_str = t("dds_admission_state.when_at", lang, when=adm_str) if adm_str else ""
        dx_str = (
            t("dds_admission_state.dx_with_code", lang, disp=adm_disp, code=adm_code)
            if adm_code
            else t("dds_admission_state.dx_no_code", lang)
        )
        body = t(
            "dds_admission_state.full_line",
            lang,
            when=when_str,
            dx=dx_str,
            severity=sev,
            severity_lower=sev.lower(),
        )
        return body, facts

    def _build_dds_treatment_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """治療経過 / Treatment course (multi-day summary).

        Summarizes the LOS, the number of active medications (MAR),
        procedures performed, and any in-hospital working diagnoses
        that arose. Deterministic prose grounded in structural CIF
        counts — the LLM pass can rewrite phrasing but cannot invent
        procedures or diagnoses that the counts do not support.
        """
        lang = ctx.target_lang
        facts: list[str] = ["ctx.los_days"]
        los = ctx.los_days or 0
        med_count = len(ctx.medications or [])
        proc_count = len(ctx.procedures or [])
        working = list(getattr(ctx, "working_diagnoses", []) or [])
        working_count = len(working)
        if med_count:
            facts.append("ctx.medications")
        if proc_count:
            facts.append("ctx.procedures")
        if working_count:
            facts.append("ctx.working_diagnoses")

        los_part = (
            t("dds_treatment_course.los_part_with_days", lang, los=los)
            if los > 0
            else t("dds_treatment_course.los_part_admission", lang)
        )
        med_part = t("dds_treatment_course.med_part", lang, count=med_count) if med_count else ""
        proc_part = t("dds_treatment_course.proc_part", lang, count=proc_count) if proc_count else ""
        wk_part = t("dds_treatment_course.wk_part", lang, count=working_count) if working_count else ""
        tail = t("dds_treatment_course.tail", lang)
        return f"{los_part}{med_part}{proc_part}{wk_part}{tail}", facts

    def _build_dds_terminal_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """終末期経過 / Terminal course (final ~24-72 h).

        Anchors on the discharge (= death) datetime and describes the
        final hours from the primary cause + any complications. When the
        CIF has no dedicated terminal-vitals summary, the template
        renders a defensible "progressive deterioration" phrase keyed
        on disease pattern (chronic decompensation vs acute event)
        rather than fabricating specific vital values.
        """
        lang = ctx.target_lang
        facts: list[str] = []
        dis_dt = _o(ctx.encounter, "discharge_datetime", None)
        dis_str = str(dis_dt)[:16].replace("T", " ") if dis_dt else ""
        if dis_dt:
            facts.append("ctx.encounter.discharge_datetime")
        code, display, _ = self._dc_resolve_primary_cause(ctx)
        pattern = self._dc_disease_pattern(code)
        if code:
            facts.append("ctx.diagnoses[0].discharge_diagnosis_code")

        phrase_key = {
            "acute": "dds_terminal_course.phrase_acute",
            "chronic": "dds_terminal_course.phrase_chronic",
        }.get(pattern, "dds_terminal_course.phrase_unknown")
        phrase = t(phrase_key, lang)
        dx_part = t("dds_terminal_course.dx_part", lang, display=display) if display else ""
        when = (
            t("dds_terminal_course.when_at", lang, ts=dis_str)
            if dis_str
            else t("dds_terminal_course.when_eventually", lang)
        )
        return t("dds_terminal_course.full_line", lang, phrase=phrase, dx_part=dx_part, when=when), facts

    def _build_dds_circumstances_of_death(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """死亡時状況 / Circumstances of death (bedside events).

        Describes the bedside setting at time of death: location (in
        hospital), resuscitation attempts (from CIF Procedure records
        when present), and whether resuscitation was performed.
        Deterministic default is "看取り" (comfort-care death) when no
        CPR/resuscitation procedure is recorded, and "蘇生術施行" when
        the CIF Procedure list contains a resuscitation code.
        """
        lang = ctx.target_lang
        facts: list[str] = []
        procedures = ctx.procedures or []
        resuscitation = False
        for p in procedures:
            code = str(_o(p, "code", "") or "")
            name = str(_o(p, "name", "") or "").lower()
            # ICD-10-PCS / CPT / SNOMED codes for CPR / defibrillation are
            # detected by name substring — the CIF Procedure list is small
            # so this is O(n) with n ≤ tens.
            if any(k in name for k in ("cpr", "cardiopulmonary", "resuscit", "defibrill", "蘇生", "心肺蘇生")):
                resuscitation = True
                break
            if code in {"5A12012", "92950", "99288"}:  # PCS / CPT CPR codes
                resuscitation = True
                break
        if procedures:
            facts.append("ctx.procedures")

        key = "dds_circumstances_of_death.resuscitation" if resuscitation else "dds_circumstances_of_death.natural"
        return t(key, lang), facts

    def _build_dds_cause_of_death(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """死因 / Cause of death (structured mirror of DC immediate cause).

        Uses the same _dc_resolve_primary_cause helper so this DDS
        section and the DC 直接死因 section are guaranteed to agree per
        encounter (single-source-of-truth per
        feedback_dr_conclusion_code_single_walk).
        """
        lang = ctx.target_lang
        code, display, facts = self._dc_resolve_primary_cause(ctx)
        if not code:
            return t("death_cert.cause_of_death_not_documented", lang), facts
        return t("death_cert_line.cause_of_death", lang, display=display, code=code), facts

    def _build_dds_complications_and_comorbidities(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """合併症・併存症 / Complications and comorbidities.

        Enriched sibling of the DC 影響を及ぼした傷病名 section but
        oriented for the DDS narrative: enumerates chronic conditions
        AND in-hospital complications side by side rather than fusing
        them, so consumers can distinguish pre-existing from acquired.
        """
        lang = ctx.target_lang
        facts: list[str] = []
        conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
        cond_labels: list[str] = []
        for c in list(conds)[:5]:
            code_val = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code_val:
                continue
            system = _o(c, "system", "") or system_key_for("diagnosis", ctx.locale.upper())
            disp = code_lookup(system, code_val, lang) or code_val
            cond_labels.append(t("list_item.inline_dx_with_code", lang, display=disp, code=code_val))
        if cond_labels:
            facts.append("ctx.patient.chronic_conditions")

        comp_tokens = list(getattr(ctx, "complications_occurred", []) or [])[:5]
        if comp_tokens:
            facts.append("ctx.complications_occurred")

        if not cond_labels and not comp_tokens:
            return t("death_cert.comorbidities_none", lang), facts

        cond_sep = t("list_sep.serial", lang)
        parts: list[str] = []
        if cond_labels:
            parts.append(t("dds_complications_and_comorbidities.chronic_part", lang, list=cond_sep.join(cond_labels)))
        if comp_tokens:
            comp_labels_str = cond_sep.join(str(tok).replace("_", " ") for tok in comp_tokens)
            parts.append(t("dds_complications_and_comorbidities.in_hospital_part", lang, list=comp_labels_str))
        # JA joins parts with "。" (list_sep.period) + trailing period;
        # EN joins with ". " (list_sep.period_space) + trailing period.
        body = t("list_sep.period_space", lang).join(parts) + t("list_sep.period", lang)
        return t("dds_complications_and_comorbidities.head", lang, body=body), facts

    def _build_dds_family_communication(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """家族への説明経過 / Family communication timeline.

        clinosim's CIF does not currently model family-communication
        events (no dedicated Encounter subtype or Communication resource).
        Real JP hospital DDS narratives commonly carry a boilerplate
        "家族に病状悪化を説明、死亡時立会い" when the electronic record
        is minimal — this is what a physician writes when the paper
        family-communication log lives outside the EHR. The template
        emits that boilerplate anchored on the encounter's LOS bucket
        (short admission = "入院時から重篤性を説明" / long admission =
        "経過に応じて随時説明") so the LLM refinement pass can polish
        without inventing specific meeting dates.
        """
        lang = ctx.target_lang
        facts: list[str] = ["ctx.los_days"]
        los = ctx.los_days or 0

        if los <= 1:
            lead_key = "dds_family_communication.lead_short"
        elif los <= 7:
            lead_key = "dds_family_communication.lead_med"
        else:
            lead_key = "dds_family_communication.lead_long"
        lead = t(lead_key, lang)
        return t("dds_family_communication.head_with_tail", lang, lead=lead), facts

    def _build_dds_autopsy_status_and_findings(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """剖検の有無・所見 / Autopsy status and findings.

        Uses the SAME SHA256 sampling helper as the DC autopsy_status
        section so the two documents always agree (~7% autopsy rate).
        When autopsy=true, appends a defensible "所見は主要臓器の病理
        学的評価にて確認された" boilerplate — clinosim does not model
        pathological findings, so this stays generic rather than
        fabricating specific gross/microscopic descriptions.
        """
        lang = ctx.target_lang
        facts: list[str] = ["encounter.id::autopsy_sample"]
        performed = _autopsy_performed_sha256(ctx)
        if performed:
            return t("autopsy.findings_yes", lang), facts
        return t("autopsy.findings_no", lang), facts

    # ─────────────────────────────────────────────────────────────────
    # OPERATIVE_NOTE section builders (Issue #991)
    # ─────────────────────────────────────────────────────────────────
    #
    # LOINC 11504-8 (Surgical operation note / 手術記録). Every builder
    # scopes to the encounter's primary surgical ProcedureRecord (earliest
    # by start_datetime whose category_code == "387713003"), mirroring the
    # engine's `per_surgical_encounter` dispatch (engine.py). Missing data
    # degrades to a conservative fallback string rather than fabricating
    # (feedback_empty_vs_wrong_assertion).

    # Phase 1d-24 (2026-09-24): ``_OP_ANESTHESIA_JA/EN`` and
    # ``_OP_OUTCOME_JA/EN`` moved to
    # ``clinosim/locale/shared/narrative_labels.yaml`` under
    # ``op_anesthesia_type`` and ``op_outcome_code``. Callers resolve
    # via ``_label`` + ``resolve_localized_display``.
    #
    # _OP_APPROACH / _OP_IMPLANT vocab — moved to
    # ``clinosim/locale/shared/narrative_op_approach.yaml`` and
    # ``narrative_op_implants.yaml`` (Phase 1d-1). Callers resolve via
    # module-level ``_localize_op_approach`` / ``_localize_op_implant``.

    def _primary_surgical_procedure(self, ctx: NarrativeContext) -> Any | None:
        """Return the encounter's earliest surgical ProcedureRecord (or None).

        Mirrors the engine's ``per_surgical_encounter`` selection: filter
        ``ctx.procedures`` to entries whose ``encounter_id`` matches the
        current encounter AND whose SNOMED ``category_code == "387713003"``
        (surgical procedure), then pick the earliest by ``start_datetime``.
        Bedside/diagnostic/therapeutic procedures never satisfy the
        category filter, so this is safe to call on non-surgical encounters
        (returns None). The engine's own choice of primary is deterministic
        and independent, so template + engine agree on which procedure
        the note describes.
        """
        enc_id = _o(ctx.encounter, "encounter_id", "") or ""
        candidates = [
            p
            for p in (ctx.procedures or [])
            if _o(p, "encounter_id", "") == enc_id and str(_o(p, "category_code", "") or "") == "387713003"
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda p: _o(p, "start_datetime", None) or datetime(2000, 1, 1))

    def _resolve_procedure_display(self, proc: Any, lang: str) -> str:
        """Resolve procedure display via code_lookup (k-codes / cpt).

        Mirrors ``clinosim/modules/output/hospital_course_extractor._resolve_procedure_name``
        so the operative note reads the same authoritative code catalog as
        the FHIR emit path — a single edit of the k-codes yaml updates both
        (single-edit-point rule).
        """
        for key in ("procedure_code", "procedure_code_jp", "procedure_code_us"):
            code = _o(proc, key, "") or ""
            if not code:
                continue
            for system_key in ("k-codes", "cpt"):
                disp = code_lookup(system_key, code, lang)
                if disp and disp != code:
                    return disp
        return str(_o(proc, "procedure_type", "") or "")

    def _build_op_procedure_name(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """術式名 — procedure code display + K/CPT code + approach modifier."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.procedure_not_documented", lang), []
        facts = ["ctx.procedures"]
        name = self._resolve_procedure_display(proc, lang)
        code = _o(proc, "procedure_code", "") or _o(proc, "procedure_code_jp", "") or _o(proc, "procedure_code_us", "")
        approach_raw = str(_o(proc, "approach", "") or "").lower()
        approach = _localize_op_approach(approach_raw, lang)
        duration = _o(proc, "duration_minutes", 0) or 0
        head = t("op_note.procedure_head", lang, name=name)
        approach_part = t("op_note.procedure_approach_paren", lang, approach=approach) if approach else ""
        code_part = t("op_note.procedure_code_paren", lang, code=code) if code else ""
        duration_part = t("op_note.procedure_duration_suffix", lang, duration=duration) if duration else ""
        return f"{head}{approach_part}{code_part}{duration_part}", facts

    def _build_op_anesthesia(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """麻酔法 — anesthesia type + ASA class + anesthesiologist."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.anesthesia_not_documented", lang), []
        facts = ["ctx.procedures"]
        atype = str(_o(proc, "anesthesia_type", "") or "").lower()
        # ``_OP_ANESTHESIA_JA/EN`` moved to
        # ``narrative_labels.yaml::op_anesthesia_type`` (Phase 1d-24).
        anes_label = _label("op_anesthesia_type", atype, lang, fallback=atype or t("op_note.anes_no_record", lang))
        asa = _o(proc, "asa_class", 0) or 0
        anes_id = _o(proc, "anesthesiologist_id", "") or ""
        anes_name = _resolve_staff_name(anes_id, ctx.roster_map, lang) if anes_id else ""
        head = t("op_note.anesthesia_head", lang, label=anes_label)
        asa_part = t("op_note.anesthesia_asa_suffix", lang, asa=asa) if asa else ""
        anes_part = t("op_note.anesthesia_anesthesiologist_suffix", lang, name=anes_name) if anes_name else ""
        return f"{head}{asa_part}{anes_part}", facts

    def _build_op_surgeon(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """執刀医・助手 — primary surgeon + assistant list (name-resolved)."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.surgeon_not_documented", lang), []
        facts = ["ctx.procedures"]
        surgeon_id = _o(proc, "primary_surgeon_id", "") or ""
        surgeon_name = _resolve_staff_name(surgeon_id, ctx.roster_map, lang) if surgeon_id else ""
        assistant_ids = list(_o(proc, "assistant_ids", []) or [])
        assistant_names = [_resolve_staff_name(a, ctx.roster_map, lang) for a in assistant_ids if a]
        sep = t("list_sep.serial", lang)
        surgeon_part = (
            t("op_note.surgeon_line", lang, surgeon=surgeon_name) if surgeon_name else t("op_note.surgeon_none", lang)
        )
        assist_part = (
            t("op_note.assistants_suffix", lang, list=sep.join(assistant_names))
            if assistant_names
            else t("op_note.assistants_none_suffix", lang)
        )
        return f"{surgeon_part}{assist_part}", facts

    def _build_op_findings(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """術中所見 — body site + preop/postop diagnosis + intraop complications."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.findings_not_documented", lang), []
        facts = ["ctx.procedures"]
        body_site_code = _o(proc, "body_site_code", "") or ""
        # snomed-ct is the canonical system key (loader.py). Lookup returns
        # the code string itself when unresolved — treat that as "no display"
        # so we never leak raw SNOMED numeric codes into the narrative.
        body_site_disp = code_lookup("snomed-ct", body_site_code, lang) if body_site_code else ""
        body_site = body_site_disp if body_site_disp and body_site_disp != body_site_code else ""
        preop = _o(proc, "preop_diagnosis", "") or ""
        postop = _o(proc, "postop_diagnosis", "") or ""
        intraop = list(_o(proc, "intraop_complications", []) or [])
        # Phase 1c-6 (Category K, 2026-09-23): preop / postop diagnosis
        # are stamped with the disease_id slug (hip_fracture /
        # acute_cholecystitis / …) and intraop_complications are
        # complication slugs — route through ``_localize_complication``
        # so JA reads 「術前診断：大腿骨近位部骨折」 rather than
        # 「術前診断：hip_fracture」.
        preop_disp = _localize_complication(preop, lang) if preop else ""
        postop_disp = _localize_complication(postop, lang) if postop else ""
        intraop_disp = [_localize_complication(str(c), lang) for c in intraop]
        parts = []
        if body_site:
            parts.append(t("op_note.findings_line", lang, body_site=body_site))
        if preop_disp:
            parts.append(t("op_note.findings_preop", lang, dx=preop_disp))
        if postop_disp and postop_disp != preop_disp:
            parts.append(t("op_note.findings_postop", lang, dx=postop_disp))
        if intraop_disp:
            sep = t("list_sep.serial", lang)
            parts.append(t("op_note.findings_intraop", lang, list=sep.join(intraop_disp)))
        else:
            parts.append(t("op_note.findings_intraop_none", lang))
        chunk_sep = t("list_sep.slash", lang)
        return chunk_sep.join(parts) if parts else t("op_note.findings_none_default", lang), facts

    def _build_op_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """手術経過 — approach + duration + outcome + timing narrative."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.course_not_documented", lang), []
        facts = ["ctx.procedures"]
        approach_raw = str(_o(proc, "approach", "") or "").lower()
        approach = _localize_op_approach(approach_raw, lang)
        duration = _o(proc, "duration_minutes", 0) or 0
        outcome_code = str(_o(proc, "outcome_code", "") or "")
        # ``_OP_OUTCOME_JA/EN`` moved to
        # ``narrative_labels.yaml::op_outcome_code`` (Phase 1d-24).
        outcome = _label("op_outcome_code", outcome_code, lang, fallback="") if outcome_code else ""
        start_dt = _o(proc, "start_datetime", None)
        end_dt = _o(proc, "end_datetime", None)
        approach_part = t("op_note.course_approach_part", lang, approach=approach) if approach else ""
        time_part = ""
        if isinstance(start_dt, datetime) and isinstance(end_dt, datetime):
            time_part = t(
                "op_note.course_time_part",
                lang,
                start=start_dt.strftime("%H:%M"),
                end=end_dt.strftime("%H:%M"),
            )
        duration_part = t("op_note.course_duration_part", lang, duration=duration) if duration else ""
        outcome_part = t("op_note.course_outcome_part", lang, outcome=outcome) if outcome else ""
        return (
            t(
                "op_note.course_head",
                lang,
                approach_part=approach_part,
                time_part=time_part,
                duration_part=duration_part,
                outcome_part=outcome_part,
            ),
            facts,
        )

    def _build_op_specimens(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """摘出臓器・組織 — specimens_sent list."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.specimens_not_documented", lang), []
        facts = ["ctx.procedures"]
        specimens = [str(s) for s in (_o(proc, "specimens_sent", []) or []) if s]
        if not specimens:
            return t("op_note.specimens_none", lang), facts
        sep = t("list_sep.serial", lang)
        return t("op_note.specimens_line", lang, list=sep.join(specimens)), facts

    def _build_op_blood_loss(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """出血量・輸血 — estimated_blood_loss_ml + transfusion note."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.blood_loss_not_documented", lang), []
        facts = ["ctx.procedures"]
        ebl = _o(proc, "estimated_blood_loss_ml", 0) or 0
        # Transfusion inference: check ctx.procedures for a blood_transfusion
        # ProcedureRecord in the same encounter (K920 / procedure_type
        # "blood_transfusion" from clinosim.modules.procedure.engine).
        enc_id = _o(ctx.encounter, "encounter_id", "") or ""
        transfused = any(
            (
                _o(p, "encounter_id", "") == enc_id
                and str(_o(p, "procedure_type", "") or "").lower() == "blood_transfusion"
            )
            for p in (ctx.procedures or [])
        )
        transfusion_part = t(
            "op_note.blood_loss_transfusion_yes" if transfused else "op_note.blood_loss_transfusion_no",
            lang,
        )
        return t("op_note.blood_loss_line", lang, ebl=ebl, transfusion_part=transfusion_part), facts

    def _build_op_equipment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """使用機器・材料 — implants_used list."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.equipment_not_documented", lang), []
        facts = ["ctx.procedures"]
        implants = [str(x) for x in (_o(proc, "implants_used", []) or []) if x]
        if not implants:
            return (t("op_note.implants_none", lang)), facts
        # Phase 1c-6 (Category K, 2026-09-23): route each implant name
        # through the ``narrative_op_implants.yaml`` translation table
        # on JA output so 「使用機器・材料：バイポーラ人工骨頭」 rather
        # than 「使用機器・材料：bipolar femoral prosthesis」.
        # Case-insensitive lookup on the full string; unmapped names
        # pass through unchanged. Only JA has a translation table today;
        # other languages fall through unchanged as well.
        if lang == "ja":
            implants = [_localize_op_implant(x, lang) for x in implants]
        sep = t("list_sep.serial", lang)
        return t("op_note.equipment_head", lang, list=sep.join(implants)), facts

    def _build_op_postop_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """術後方針 — recovery destination + monitoring plan (derived)."""
        lang = ctx.target_lang
        proc = self._primary_surgical_procedure(ctx)
        if proc is None:
            return t("op_note.postop_plan_not_documented", lang), []
        facts = ["ctx.procedures"]
        enc_type_raw = _o(ctx.encounter, "encounter_type", None)
        enc_type = str(_o(enc_type_raw, "value", enc_type_raw) or "").lower()
        outcome_code = str(_o(proc, "outcome_code", "") or "")
        intraop = list(_o(proc, "intraop_complications", []) or [])
        # Recovery destination: ICU/high-acuity or general ward
        icu_flag = enc_type == "icu" or bool(intraop) or outcome_code == "385670004"
        dest = t("op_note.postop_dest_icu" if icu_flag else "op_note.postop_dest_ward", lang)
        monitor = t("op_note.postop_monitor", lang)
        return t("op_note.postop_plan_line", lang, dest=dest, monitor=monitor), facts

    # Issue #992: PROCEDURE_NOTE (処置記録, LOINC 28570-0) section builders.
    # Each builder resolves the ProcedureRecord identified by
    # ``ctx.related_procedure_id`` (populated per-stub by
    # ``NarrativePass.run``) out of ``ctx.procedures`` and renders one
    # section of the note. When the procedure is missing (defensive
    # fallback — should never happen because the enricher only creates a
    # stub when a matching ProcedureRecord exists) the builders emit a
    # short "記録なし" / "not documented" line rather than raising, so a
    # single stale narrative version never blocks the whole pipeline.
    # ─────────────────────────────────────────────────────────────────

    def _pn_resolve_procedure(self, ctx: NarrativeContext) -> tuple[Any | None, list[str]]:
        """Locate the ProcedureRecord this stub describes."""
        proc_id = str(getattr(ctx, "related_procedure_id", "") or "")
        if not proc_id:
            return None, []
        for proc in ctx.procedures or []:
            if str(_o(proc, "procedure_id", "") or "") == proc_id:
                return proc, [f"ctx.procedures[{proc_id}]"]
        return None, []

    def _build_pn_procedure_name(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """処置名 / Procedure name — resolved from procedure_code."""
        lang = ctx.target_lang
        proc, facts = self._pn_resolve_procedure(ctx)
        if proc is None:
            return t("proc_note.procedure_not_documented", lang), facts
        code_jp = str(_o(proc, "procedure_code_jp", "") or "")
        code_us = str(_o(proc, "procedure_code_us", "") or "")
        code = str(_o(proc, "procedure_code", "") or "")
        # Pick the locale-appropriate code system for the display lookup.
        # JA-locale prefers ``code_jp`` (K-codes / 診療報酬点数コード),
        # other locales prefer ``code_us`` (CPT); fall back to the base
        # ``code`` field when the locale-specific slot is empty.
        if lang == "ja" and code_jp:
            primary_code = code_jp
            system_key = "k-codes"
        elif lang != "ja" and code_us:
            primary_code = code_us
            system_key = "cpt"
        else:
            primary_code = code
            system_key = "k-codes"
        display = code_lookup(system_key, primary_code, lang) or primary_code or ""
        proc_type = str(_o(proc, "procedure_type", "") or "")
        # Phase 1c-6 (2026-09-23): localize the procedure_type slug
        # (urinary_catheter / central_line / intubation / …) via the
        # bedside-procedures SoT so JA emits 「術式区分: 尿道カテーテル
        # 挿入」 rather than 「術式区分: urinary_catheter」.
        proc_type_display = _localize_proc_type(proc_type, lang) if proc_type else ""
        facts.append("ctx.procedures.procedure_code")
        core = t("proc_note.procedure_head", lang, display=display)
        if primary_code:
            core += t("proc_note.procedure_code_paren", lang, code=primary_code)
        if proc_type_display:
            core += t("proc_note.procedure_type_suffix", lang, ptype=proc_type_display)
        return core + t("list_sep.period", lang), facts

    def _build_pn_consent(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """インフォームド・コンセント / Consent — boilerplate.

        clinosim does not model per-Procedure consent artefacts. The
        template emits the standard "consent obtained" phrase every real
        JP electronic-chart procedure note carries; sites that need a
        richer consent trail should record it upstream (Order /
        Procedure.note) and extend this builder.
        """
        _proc, facts = self._pn_resolve_procedure(ctx)
        lang = ctx.target_lang
        return t("proc_note.consent_line", lang), facts

    def _build_pn_performer(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """実施者 / Performer — from ProcedureRecord.primary_surgeon_id."""
        lang = ctx.target_lang
        proc, facts = self._pn_resolve_procedure(ctx)
        if proc is None:
            return t("proc_note.operator_not_documented", lang), facts
        performer_id = str(_o(proc, "primary_surgeon_id", "") or "")
        assistant_ids = list(_o(proc, "assistant_ids", []) or [])
        anesth_id = str(_o(proc, "anesthesiologist_id", "") or "")

        # Roster lookup — if the pass populated ``ctx.roster_map`` we can
        # substitute the raw id with a full name; otherwise the raw id
        # goes through and downstream roster localizers may still
        # rewrite it (feedback: staff-id leak was already fixed for
        # Composition, this keeps parity).
        def _localise(raw_id: str) -> str:
            entry = (ctx.roster_map or {}).get(raw_id) if raw_id else None
            if entry:
                name = str(_o(entry, "name", "") or _o(entry, "display", "") or raw_id)
                return t("proc_note.performer_role_suffix", lang, name=name)
            return raw_id

        performer = _localise(performer_id)
        assistants = [_localise(a) for a in assistant_ids if a]
        anesth = _localise(anesth_id) if anesth_id else ""
        facts.extend(["ctx.procedures.primary_surgeon_id"])
        parts = [
            t("proc_note.performer_head", lang, performer=performer)
            if performer
            else t("proc_note.performer_none", lang)
        ]
        if assistants:
            # Assistants join uses ", " for both locales in the source
            # (JA also used ", " inline). Preserve that.
            parts.append(t("proc_note.performer_assistants", lang, list=", ".join(assistants)))
        if anesth:
            parts.append(t("proc_note.performer_anesth", lang, name=anesth))
        return t("list_sep.period_space", lang).join(parts) + t("list_sep.period", lang), facts

    def _build_pn_analgesia(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """麻酔・鎮静 / Analgesia — from ProcedureRecord.anesthesia_type."""
        lang = ctx.target_lang
        proc, facts = self._pn_resolve_procedure(ctx)
        if proc is None:
            return t("proc_note.analgesia_not_documented", lang), facts
        anesth = str(_o(proc, "anesthesia_type", "") or "").strip().lower()
        # Bedside procedures use local / sedation almost exclusively —
        # if the record says "general" we still honor it (some
        # cardioversion cases are done under brief GA). Analgesia
        # vocabulary moved to ``narrative_labels.yaml::pn_analgesia_type``
        # (Phase 1d-25). Fallback is ``local`` (bedside procedures default).
        default_method = _label("pn_analgesia_type", "local", lang)
        method = _label("pn_analgesia_type", anesth, lang, fallback=default_method)
        facts.append("ctx.procedures.anesthesia_type")
        return t("proc_note.analgesia_line", lang, method=method), facts

    def _build_pn_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """処置経過 / Procedure course — from duration + approach + outcome."""
        lang = ctx.target_lang
        proc, facts = self._pn_resolve_procedure(ctx)
        if proc is None:
            return t("proc_note.course_not_documented", lang), facts
        duration = int(_o(proc, "duration_minutes", 0) or 0)
        approach = str(_o(proc, "approach", "") or "")
        outcome_code = str(_o(proc, "outcome_code", "") or "")
        # SNOMED outcome codes 385669000 / 385670004 / 385671000 moved
        # to ``narrative_labels.yaml::pn_outcome_code`` (Phase 1d-25).
        # Missing / unknown code falls back to the "planned completion"
        # phrase (still language-agnostic via the same YAML).
        outcome_default = t("proc_note.course_outcome_default", lang)
        outcome = (
            _label("pn_outcome_code", outcome_code, lang, fallback=outcome_default) if outcome_code else outcome_default
        )
        facts.extend(["ctx.procedures.duration_minutes", "ctx.procedures.outcome_code"])
        core = t("proc_note.course_duration_head", lang, duration=duration)
        if approach:
            core += t("proc_note.course_approach_part", lang, approach=approach)
        return core + t("proc_note.course_outcome_suffix", lang, outcome=outcome), facts

    def _build_pn_complications(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """合併症の有無 / Complications — from intraop_complications + complication_codes."""
        lang = ctx.target_lang
        proc, facts = self._pn_resolve_procedure(ctx)
        if proc is None:
            return t("proc_note.complications_not_documented", lang), facts
        intraop = [str(x) for x in (_o(proc, "intraop_complications", []) or []) if x]
        codes = [str(x) for x in (_o(proc, "complication_codes", []) or []) if x]
        facts.append("ctx.procedures.intraop_complications")
        if intraop or codes:
            code_display = []
            for c in codes:
                disp = code_lookup("snomed-ct", c, lang) or c
                code_display.append(t("list_item.inline_dx_with_code", lang, display=disp, code=c))
            all_items = intraop + code_display
            # Complications use "; " in EN (semicolon-space) not "; ".
            # Reuse list_sep.semicolon which is 「、」 / 「; 」.
            sep = t("list_sep.semicolon", lang)
            joined = sep.join(all_items)
            return t("proc_note.complications_present", lang, list=joined), facts
        return t("proc_note.complications_none", lang), facts

    def _build_pn_specimens(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """検体の有無 / Specimens — from ProcedureRecord.specimens_sent."""
        lang = ctx.target_lang
        proc, facts = self._pn_resolve_procedure(ctx)
        if proc is None:
            return t("proc_note.specimens_not_documented", lang), facts
        specimens = [str(x) for x in (_o(proc, "specimens_sent", []) or []) if x]
        facts.append("ctx.procedures.specimens_sent")
        if specimens:
            sep = t("list_sep.serial", lang)
            joined = sep.join(specimens)
            return t("proc_note.specimens_present", lang, list=joined), facts
        return t("proc_note.specimens_none", lang), facts

    def _build_pn_postop_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """術後方針 / Post-procedure plan — outcome-aware boilerplate."""
        lang = ctx.target_lang
        proc, facts = self._pn_resolve_procedure(ctx)
        if proc is None:
            return t("proc_note.postop_plan_not_documented", lang), facts
        outcome_code = str(_o(proc, "outcome_code", "") or "")
        facts.append("ctx.procedures.outcome_code")
        # Simple, defensible plans: baseline monitoring for successful
        # procedures; escalation-of-care phrasing for unsuccessful ones.
        if outcome_code == "385671000":
            return t("proc_note.postop_unsuccessful", lang), facts
        return t("proc_note.postop_baseline", lang), facts

    # ─────────────────────────────────────────────────────────────────
    # Formatting helpers
    # ─────────────────────────────────────────────────────────────────

    def _pydantic_day_findings_to_dict(self, day_findings: Any) -> dict[str, Any]:
        """Convert a Pydantic PhysicalExamDayFindings to a plain dict."""
        if isinstance(day_findings, dict):
            return day_findings
        # Pydantic model: extract body system fields
        result: dict[str, Any] = {}
        for sys_key in ("general", "cardiovascular", "respiratory", "abdominal", "neurological"):
            val = _o(day_findings, sys_key, None)
            if val is not None:
                if isinstance(val, str):
                    result[sys_key] = val
                else:
                    # PhysicalExamSystemFindings Pydantic model
                    result[sys_key] = {
                        "mild": _o(val, "mild", ""),
                        "moderate": _o(val, "moderate", ""),
                        "severe": _o(val, "severe", ""),
                        "all": _o(val, "all", None),
                    }
        return result

    def _format_physical_exam(self, phys_exam: dict[str, Any], severity: str, lang: str) -> str:
        """Format a physical exam findings dict to a single text string.

        Picks the most appropriate severity level per system:
          - prefer "all" (severity-agnostic) if present
          - else pick severity-matched text (mild/moderate/severe)
          - else pick any non-empty text
        """
        if not phys_exam:
            return ""

        # Phase 1d-16: per-body-system labels moved to
        # ``narrative_labels.yaml::body_system``. Adding a new language
        # extends each entry with ``<lang>: <display>`` — no code change.

        parts = []
        for sys_key in ("general", "cardiovascular", "respiratory", "abdominal", "neurological"):
            entry = phys_exam.get(sys_key)
            if entry is None:
                continue
            if isinstance(entry, str):
                text = entry
            elif isinstance(entry, dict):
                # Pick severity-specific text
                text = (
                    entry.get("all")
                    or entry.get(severity)
                    or entry.get("moderate")
                    or entry.get("mild")
                    or entry.get("severe")
                    or ""
                )
                if text is None:
                    text = ""
            else:
                text = ""
            if text:
                label = _label("body_system", sys_key, lang, fallback=sys_key)
                parts.append(f"{label}: {text}")

        return t("list_sep.period_space", lang).join(parts)
