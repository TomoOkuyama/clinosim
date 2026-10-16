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
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.types.document import NarrativeContext

logger = logging.getLogger(__name__)


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


# Issue #819 follow-up: staff-id → name + role suffix resolution for
# narrative templates. Used by the small number of builders that inject
# `nurse_id` / `physician_id` verbatim into the narrative text seen by
# the LLM. Without this the LLM saw raw ids (`DR-CA-002`, `NS-OR-004`)
# and preserved them into its output — my PR #828 caught them at
# Composition FHIR-emit time but DocumentReference attachments
# (Progress Notes, Nursing Records, ED Notes) were untouched, producing
# a 68% staff-id leak in the deployed cohort.


def _resolve_staff_name(staff_id: str, roster_map: dict[str, dict]) -> str:
    """Return `<name>` from ``roster_map``, or the raw ``staff_id``
    when the id is not resolvable.

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
        _resolve_staff_name("XYZ-999", {})        → "XYZ-999"
    """
    if not staff_id:
        return staff_id
    staff = roster_map.get(staff_id) if roster_map else None
    if not staff:
        return staff_id
    return staff.get("name") or staff_id


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
    def _drug(value: str | None) -> str:
        """Lang-aware drug-name katakana wrapper — no-op for lang
        without a lookup table. Broad except keeps a narrative
        render from failing on an i18n edge case (mirrors
        `discontinue_flip._log_treatment_change`)."""
        if not value:
            return ""
        try:
            from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

            return localize_drug_name(value, lang) or value
        except Exception:  # noqa: BLE001
            return value

    # Localized-field selectors: prefer ``<field>_<lang>`` (JA only
    # populates this slot; EN falls straight through to the base field).
    def _localized_field(s: dict, base: str) -> str:
        return str(s.get(f"{base}_{lang}") or s.get(base) or "")

    for s in skips:
        event = str(s.get("event_type") or "avoid").lower()
        considered = _drug(_localized_field(s, "considered"))
        conflict = _localized_field(s, "avoided_due_to")
        substituted = _drug(_localized_field(s, "substituted_with"))

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


# Narrative localization helpers were extracted to ``_localization.py``
# as the first slice of the META #1633 P6 narrative-package
# decomposition. The imports at the top of this module re-export
# ``_localize_*``, ``_format_lab_unit_for_prose``,
# ``_PROC_TYPE_LOCALE_CACHE`` and ``_load_proc_type_locale`` so
# external callers (``discharge_rx.py``, ``replacement_strategy.py``)
# and the god class below keep their imports working unchanged.


# SOAP section labels live in `narrative_labels.yaml` under
# `soap_label:` (`subjective` / `objective` / `assessment` / `plan`)
# — resolved by `_label()` at render time.
