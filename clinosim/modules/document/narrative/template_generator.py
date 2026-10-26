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
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from clinosim.codes import get_display as code_display
from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.disease.localization import target_los_config
from clinosim.modules.document.narrative._localization import (
    _format_lab_unit_for_prose as _format_lab_unit_for_prose,
)
from clinosim.modules.document.narrative._localization import (
    _localize_complication as _localize_complication,
)
from clinosim.modules.document.narrative._localization import (
    _localize_imaging as _localize_imaging,
)
from clinosim.modules.document.narrative._localization import (
    _localize_lab_flag as _localize_lab_flag,
)
from clinosim.modules.document.narrative._localization import (
    _localize_lab_name as _localize_lab_name,
)
from clinosim.modules.document.narrative._localization import (
    _localize_op_approach as _localize_op_approach,
)
from clinosim.modules.document.narrative._localization import (
    _localize_op_implant as _localize_op_implant,
)
from clinosim.modules.document.narrative._localization import (
    _localize_proc_type as _localize_proc_type,
)
from clinosim.modules.document.narrative._localization import (
    _localize_stage as _localize_stage,
)
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_BP_HIGH_NORMAL_DBP_THRESHOLD,
    NARRATIVE_BP_HIGH_NORMAL_SBP_THRESHOLD,
    NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD,
    NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD,
    NARRATIVE_HBA1C_DIABETES_THRESHOLD,
    NARRATIVE_LDL_BORDERLINE_THRESHOLD,
    NARRATIVE_LDL_ELEVATED_THRESHOLD,
    NARRATIVE_LDL_HIGH_THRESHOLD,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _DDS_AUTOPSY_PROB_CUTOFF as _DDS_AUTOPSY_PROB_CUTOFF,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _age_at as _age_at,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _autopsy_performed_sha256 as _autopsy_performed_sha256,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _cc_altered_consciousness_keywords as _cc_altered_consciousness_keywords,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _cc_keyword_positively_present as _cc_keyword_positively_present,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _cc_severe_dyspnea_keywords as _cc_severe_dyspnea_keywords,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _filter_vitals_for_day as _filter_vitals_for_day,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _lookup_nursing_content as _lookup_nursing_content,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _parse_iso_datetime as _parse_iso_datetime,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _pe_altered_consciousness_pool_ja as _pe_altered_consciousness_pool_ja,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _pe_severe_dyspnea_pool_ja as _pe_severe_dyspnea_pool_ja,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _pick_from_pool_by_encounter as _pick_from_pool_by_encounter,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _rewrite_pe_clause as _rewrite_pe_clause,
)
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_ASSESSMENT_EN as _GENERIC_ASSESSMENT_EN,
)
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_ASSESSMENT_JA as _GENERIC_ASSESSMENT_JA,
)
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_FALLBACK_EN as _GENERIC_FALLBACK_EN,
)
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_FALLBACK_JA as _GENERIC_FALLBACK_JA,
)
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_PLAN_EN as _GENERIC_PLAN_EN,
)
from clinosim.modules.document.narrative._template_helpers import (
    _GENERIC_PLAN_JA as _GENERIC_PLAN_JA,
)
from clinosim.modules.document.narrative._template_helpers import (
    _KNOWN_PLACEHOLDERS as _KNOWN_PLACEHOLDERS,
)
from clinosim.modules.document.narrative._template_helpers import (
    _fill_template_placeholders as _fill_template_placeholders,
)
from clinosim.modules.document.narrative._template_helpers import (
    _format_vital_value as _format_vital_value,
)
from clinosim.modules.document.narrative._template_helpers import (
    _hpi_onset_en as _hpi_onset_en,
)
from clinosim.modules.document.narrative._template_helpers import (
    _label as _label,
)
from clinosim.modules.document.narrative._template_helpers import (
    _pick_localized as _pick_localized,
)
from clinosim.modules.document.narrative._template_helpers import (
    _render_home_med_name as _render_home_med_name,
)
from clinosim.modules.document.narrative._template_helpers import (
    _render_safety_skips_line as _render_safety_skips_line,
)
from clinosim.modules.document.narrative._template_helpers import (
    _resolve_staff_name as _resolve_staff_name,
)
from clinosim.modules.document.narrative._template_helpers import (
    _resolve_vital_placeholders as _resolve_vital_placeholders,
)
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.reference_data_loaders import (
    load_chief_complaint_variants,
    load_discharge_instructions,
    load_hpi_pertinent_negatives,
    load_physical_exam_findings,
)
from clinosim.types.document import DocumentType, FormatType, NarrativeContext, NarrativeOutput

logger = logging.getLogger(__name__)


@cache
def _chronic_med_class_hints_raw() -> dict[str, dict[str, Any]]:
    """Load `clinosim/codes/data/chronic-med-class-hints.yaml`.

    Returns a `{class_key: {prefix, en: [...], ja: [...]}}` dict.
    """
    import yaml

    path = Path(__file__).resolve().parents[3] / "codes" / "data" / "chronic-med-class-hints.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    classes = raw.get("classes") or {}
    out: dict[str, dict[str, Any]] = {}
    for class_key, row in classes.items():
        if isinstance(row, dict):
            out[str(class_key)] = row
    return out


def _chronic_med_class_hints(class_key: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return `(en_hints, ja_hints)` tuple for a chronic-condition class.

    Looked up in `chronic-med-class-hints.yaml` by `class_key`
    (`hypertension`, `diabetes`, `dyslipidemia`, `afib_anticoagulation`,
    `copd`, `asthma`). Missing locale lists return `()` — the caller's
    `_pick_med_containing` treats that as "no med cited".
    """
    row = _chronic_med_class_hints_raw().get(class_key) or {}
    en = tuple(str(h) for h in (row.get("en") or []) if isinstance(h, str))
    ja = tuple(str(h) for h in (row.get("ja") or []) if isinstance(h, str))
    return (en, ja)


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
        """Build a SOAP-style progress note as plain text (PROGRESS_NOTE).
        Delegates to the standalone renderer at
        ``clinosim/modules/document/narrative/renderers/progress_note.py``
        (full-review Phase C1b — third renderer split, CRITICAL C1).
        """
        from clinosim.modules.document.narrative.renderers.progress_note import (
            render_progress_note,
        )

        return render_progress_note(self, ctx, spec)

    # ─────────────────────────────────────────────────────────────────
    # Renderer: COMPOSITION (ADMISSION_HP, DISCHARGE_SUMMARY)
    # ─────────────────────────────────────────────────────────────────

    def _render_composition_sections(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build section dict per spec.composition_sections. Delegates
        to the standalone renderer at
        ``clinosim/modules/document/narrative/renderers/composition_sections.py``
        (full-review Phase C1c — fourth renderer split, CRITICAL C1).
        """
        from clinosim.modules.document.narrative.renderers.composition_sections import (
            render_composition_sections,
        )

        return render_composition_sections(self, ctx, spec)

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
                        lang,
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
            lang,
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
        lang: str,
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
        if lang != "ja" or not text:
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
        if lang != "ja":
            onset_text_en = _hpi_onset_en(ctx.severity)
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
        # This branch only fires for JA output (early return above), so
        # we pin lang=ja for the yaml lookup. hardcoded-review Phase A15.
        sex_label = t(f"patient_demographics.sex_display.{str(sex).lower()}", "ja") if sex else ""
        # When the lookup misses (unknown sex code), t() falls through to
        # the raw key, which we don't want in the preamble. Treat a
        # dotted-key passthrough as empty so the age-only branch fires.
        if "." in sex_label:
            sex_label = ""
        if age and sex_label:
            parts.append(t("patient_demographics.patient_preamble_with_sex", "ja", age=age, sex=sex_label))
        elif age:
            parts.append(t("patient_demographics.patient_preamble_age_only", "ja", age=age))
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

        # Issue #1156: EN PE previously short-circuited to a bare
        # "No special findings" placeholder. The JP-only per-disease
        # ``physical_exam_findings`` YAML content still cannot be reused
        # (would leak CJK), but the vitals line ``_compose_pe_vitals_line``
        # produces a language-neutral prose string ("BP 130/80 mmHg, HR
        # 88/min, T 37.5°C, SpO2 96% (RA), RR 20/min") that reads
        # cleanly in either locale. EN now prepends the vitals block
        # so admission H&P PE carries at least the encounter's
        # objective vitals instead of being blank.
        if lang != "ja":
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
        if lang != "ja":
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
        text = t("ap_combined.assessment_plan_block", lang, assessment=assessment, plan=plan)
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
            # Drug-name katakana lookup is a JA-locale-specific data
            # pipeline via `localize_drug_name(name, lang)` — a no-op
            # for any lang without a lookup table (today: any non-`"ja"`).
            # Adding a new locale is a data-only extension of
            # `drug_names_<lang>.yaml`; no branch here.
            from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

            med_names.append(localize_drug_name(str(name), lang))
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

    # ─────────────────────────────────────────────────────────────────
    # JP-CLINS section builders — thin delegators dispatching to
    # free-standing functions in ``renderers/section_builders/jp_clins.py``
    # (full-review Phase C1g, CRITICAL C1). ``_render_composition_sections``
    # still looks up ``generator._build_<section>`` by name, so the
    # method entry point stays on the class.
    # ─────────────────────────────────────────────────────────────────

    def _build_admission_reason(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_admission_reason,
        )

        return build_admission_reason(self, ctx)

    def _build_admission_details(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_admission_details,
        )

        return build_admission_details(self, ctx)

    def _build_discharge_details(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_discharge_details,
        )

        return build_discharge_details(self, ctx)

    def _build_admission_diagnoses(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_admission_diagnoses,
        )

        return build_admission_diagnoses(self, ctx)

    def _build_present_illness(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_present_illness,
        )

        return build_present_illness(self, ctx)

    def _build_referring_institution(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_referring_institution,
        )

        return build_referring_institution(self, ctx)

    def _build_referral_destination(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_referral_destination,
        )

        return build_referral_destination(self, ctx)

    def _build_referral_purpose(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_referral_purpose,
        )

        return build_referral_purpose(self, ctx)

    def _build_diagnoses_and_complaint(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_diagnoses_and_complaint,
        )

        return build_diagnoses_and_complaint(self, ctx)

    def _build_present_illness_ref(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_present_illness_ref,
        )

        return build_present_illness_ref(self, ctx)

    def _build_checkup_lab_results(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_checkup_lab_results,
        )

        return build_checkup_lab_results(self, ctx)

    def _build_checkup_questionnaire(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.jp_clins import (
            build_checkup_questionnaire,
        )

        return build_checkup_questionnaire(self, ctx)

    # ─────────────────────────────────────────────────────────────────
    # DISCHARGE_SUMMARY section builders — thin delegators dispatching
    # to free-standing functions in
    # ``renderers/section_builders/discharge_summary.py`` (full-review
    # Phase C1i, CRITICAL C1).
    # ─────────────────────────────────────────────────────────────────

    def _build_hospital_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
            build_hospital_course,
        )

        return build_hospital_course(self, ctx)

    def _build_discharge_diagnoses(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
            build_discharge_diagnoses,
        )

        return build_discharge_diagnoses(self, ctx)

    def _build_discharge_medications(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
            build_discharge_medications,
        )

        return build_discharge_medications(self, ctx)

    def _build_discharge_instructions(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
            build_discharge_instructions,
        )

        return build_discharge_instructions(self, ctx)

    def _build_follow_up(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.discharge_summary import (
            build_follow_up,
        )

        return build_follow_up(self, ctx)

    # ─────────────────────────────────────────────────────────────────
    # Free-text renderers (NURSING_SHIFT_NOTE, ED_TRIAGE_NOTE)
    # ─────────────────────────────────────────────────────────────────

    def _render_nursing_shift_note_text(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build NURSING_SHIFT_NOTE as free text. Delegates to the
        standalone renderer at
        ``clinosim/modules/document/narrative/renderers/nursing_shift_note.py``
        (full-review Phase C1a — second renderer split after B8 pilot,
        CRITICAL C1).
        """
        from clinosim.modules.document.narrative.renderers.nursing_shift_note import (
            render_nursing_shift_note,
        )

        return render_nursing_shift_note(ctx, spec)

    def _render_ed_triage_note_text(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Build ED_TRIAGE_NOTE as free text. Delegates to the
        standalone renderer at
        ``clinosim/modules/document/narrative/renderers/ed_triage_note.py``
        (full-review Phase B8 — the pilot for the per-document-type
        renderer split of this god class, CRITICAL C1).
        """
        from clinosim.modules.document.narrative.renderers.ed_triage_note import (
            render_ed_triage_note,
        )

        return render_ed_triage_note(ctx, spec)

    # ─────────────────────────────────────────────────────────────────
    # ADMISSION_NURSING_ASSESSMENT section builders
    # ─────────────────────────────────────────────────────────────────

    def _build_nursing_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_nursing_history,
        )

        return build_nursing_history(self, ctx)

    def _build_adl_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_adl_assessment,
        )

        return build_adl_assessment(self, ctx)

    def _build_risk_assessments(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_risk_assessments,
        )

        return build_risk_assessments(self, ctx)

    def _build_nursing_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_nursing_diagnosis,
        )

        return build_nursing_diagnosis(self, ctx)

    def _build_care_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_care_plan,
        )

        return build_care_plan(self, ctx)

    # ─────────────────────────────────────────────────────────────────
    # ADMISSION_CARE_PLAN (Phase 2) section builders (入院診療計画書, LOINC 18776-5)
    #
    # MHLW form 別紙２ (10 core fields, verified 2026-07-03 — design spec §2).
    # JP-only doc type (countries_supported=[jp]); both language branches are
    # implemented for consistency with every other builder in this file, even
    # though only target_lang="ja" is ever reached through the registry gate.
    # ─────────────────────────────────────────────────────────────────

    # ─────────────────────────────────────────────────────────────────
    # ADMISSION_CARE_PLAN + NUTRITION_CARE_PLAN + REHABILITATION_PLAN
    # section builders — thin delegators dispatching to free-standing
    # functions in ``renderers/section_builders/care_plans.py``
    # (full-review Phase C1e, CRITICAL C1). ``_render_composition_sections``
    # still looks up ``generator._build_<section>`` by name, so the
    # method entry point stays on the class.
    #
    # ``_estimated_los_days`` is a shared helper for ACP + RP + the
    # discharge-planning section elsewhere in the class; it stays on
    # the class so other builders / delegators that call
    # ``generator._estimated_los_days`` keep working.
    # ─────────────────────────────────────────────────────────────────

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

    def _build_acp_ward_and_room(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_ward_and_room,
        )

        return build_acp_ward_and_room(self, ctx)

    def _build_acp_other_staff(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_other_staff,
        )

        return build_acp_other_staff(self, ctx)

    def _build_acp_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_diagnosis,
        )

        return build_acp_diagnosis(self, ctx)

    def _build_acp_symptoms(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_symptoms,
        )

        return build_acp_symptoms(self, ctx)

    def _build_acp_treatment_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_treatment_plan,
        )

        return build_acp_treatment_plan(self, ctx)

    def _build_acp_test_schedule(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_test_schedule,
        )

        return build_acp_test_schedule(self, ctx)

    def _build_acp_surgery_schedule(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_surgery_schedule,
        )

        return build_acp_surgery_schedule(self, ctx)

    def _build_acp_estimated_los(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_estimated_los,
        )

        return build_acp_estimated_los(self, ctx)

    def _build_acp_special_nutrition_management(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_special_nutrition_management,
        )

        return build_acp_special_nutrition_management(self, ctx)

    def _build_acp_other_plans(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_acp_other_plans,
        )

        return build_acp_other_plans(self, ctx)

    def _build_ncp_ward_and_physician(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_ward_and_physician,
        )

        return build_ncp_ward_and_physician(self, ctx)

    def _build_ncp_dietitian(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_dietitian,
        )

        return build_ncp_dietitian(self, ctx)

    def _build_ncp_nutrition_risk(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_nutrition_risk,
        )

        return build_ncp_nutrition_risk(self, ctx)

    def _build_ncp_nutrition_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_nutrition_assessment,
        )

        return build_ncp_nutrition_assessment(self, ctx)

    def _build_ncp_nutrition_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_nutrition_goals,
        )

        return build_ncp_nutrition_goals(self, ctx)

    def _build_ncp_nutrition_supply(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_nutrition_supply,
        )

        return build_ncp_nutrition_supply(self, ctx)

    def _build_ncp_dysphagia_diet(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_dysphagia_diet,
        )

        return build_ncp_dysphagia_diet(self, ctx)

    def _build_ncp_dietary_content(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_dietary_content,
        )

        return build_ncp_dietary_content(self, ctx)

    def _build_ncp_nutrition_counseling(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_nutrition_counseling,
        )

        return build_ncp_nutrition_counseling(self, ctx)

    def _build_ncp_other_issues(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_other_issues,
        )

        return build_ncp_other_issues(self, ctx)

    def _build_ncp_reassessment_timing(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_reassessment_timing,
        )

        return build_ncp_reassessment_timing(self, ctx)

    def _build_ncp_discharge_evaluation(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_ncp_discharge_evaluation,
        )

        return build_ncp_discharge_evaluation(self, ctx)

    def _build_rp_patient_and_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_patient_and_diagnosis,
        )

        return build_rp_patient_and_diagnosis(self, ctx)

    def _build_rp_rehab_team(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_rehab_team,
        )

        return build_rp_rehab_team(self, ctx)

    def _build_rp_functional_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_functional_status,
        )

        return build_rp_functional_status(self, ctx)

    def _build_rp_basic_movement(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_basic_movement,
        )

        return build_rp_basic_movement(self, ctx)

    def _build_rp_session_frequency(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_session_frequency,
        )

        return build_rp_session_frequency(self, ctx)

    def _build_rp_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_goals,
        )

        return build_rp_goals(self, ctx)

    def _build_rp_policy(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_policy,
        )

        return build_rp_policy(self, ctx)

    def _build_rp_discharge_estimate(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_discharge_estimate,
        )

        return build_rp_discharge_estimate(self, ctx)

    def _build_rp_explanation_consent(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.care_plans import (
            build_rp_explanation_consent,
        )

        return build_rp_explanation_consent(self, ctx)

    # ─────────────────────────────────────────────────────────────────
    # NURSING_DISCHARGE_SUMMARY section builders
    # ─────────────────────────────────────────────────────────────────

    def _build_nursing_admission_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_nursing_admission_status,
        )

        return build_nursing_admission_status(self, ctx)

    def _build_nursing_interventions_provided(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_nursing_interventions_provided,
        )

        return build_nursing_interventions_provided(self, ctx)

    def _build_patient_education(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_patient_education,
        )

        return build_patient_education(self, ctx)

    def _build_discharge_readiness(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.nursing import (
            build_discharge_readiness,
        )

        return build_discharge_readiness(self, ctx)

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
            disp = _code_lookup(key, emit_code, lang)
            # Issue #1777: when the display lookup misses, SKIP the entry
            # rather than leak the raw ICD code into narrative free text.
            # The prose sentence "Follow-up of chronic conditions: G47.30"
            # reads as a coding sheet, not a clinical note; a shorter list
            # with only resolvable items reads correctly.
            if not disp or disp == emit_code:
                continue
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
                unit_disp = _format_lab_unit_for_prose(unit)
                # Phase 1d-80: drop the unit when it collapses to the same
                # string as the lab_name (real case: pH lab with UCUM unit
                # "[pH]" strips to "pH" → visible duplicate "pH 7.4 pH [L]").
                if unit_disp and unit_disp.lower() == str(disp_name).lower():
                    unit_disp = ""
                unit_part = f" {unit_disp}" if unit_disp else ""
                abn.append(f"{disp_name} {val}{unit_part} [{disp_flag}]")
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
            # Drug-name katakana lookup via lang-aware wrapper (no-op
            # when lang has no lookup table).
            from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

            med_names.append(localize_drug_name(str(name), lang))
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

        if _cc_keyword_positively_present(cc, _cc_altered_consciousness_keywords()):
            replacement = _pick_from_pool_by_encounter(_pe_altered_consciousness_pool_ja(), enc_id, "pe_consciousness")
            new_text = _rewrite_pe_clause(text, ("意識清明",), replacement)
            if new_text != text:
                facts.append("cc_pe_consistency:consciousness")
                text = new_text

        if _cc_keyword_positively_present(cc, _cc_severe_dyspnea_keywords()):
            replacement = _pick_from_pool_by_encounter(_pe_severe_dyspnea_pool_ja(), enc_id, "pe_respiratory")
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

        def _pick_med_by_class(class_key: str) -> str | None:
            """Shorthand for `_pick_med_containing(*_chronic_med_class_hints(key))`."""
            en, ja = _chronic_med_class_hints(class_key)
            return _pick_med_containing(en_hints=en, ja_hints=ja)

        def _pick_med_containing(en_hints: tuple[str, ...], ja_hints: tuple[str, ...]) -> str | None:
            """Return the first current-med whose (locale-rendered) name
            contains any hint. Hints must be provided for both locales — the
            match set is chosen by ``ctx.target_lang`` so a US assessment
            searches on English tokens and a JP assessment on katakana.
            """
            hints = ja_hints if lang == "ja" else en_hints
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
                target = t(
                    "chronic_assessment.bp_target",
                    lang,
                    sbp=NARRATIVE_BP_HYPERTENSION_SBP_THRESHOLD,
                    dbp=NARRATIVE_BP_HYPERTENSION_DBP_THRESHOLD,
                )
                med = _pick_med_by_class("hypertension")
                med_tail = t("chronic_assessment.med_continue_tail", lang, med=med) if med else ""
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
                med = _pick_med_by_class("diabetes")
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
                    target = t(
                        "chronic_assessment.ldl_target_primary_prevention",
                        lang,
                        ldl=NARRATIVE_LDL_ELEVATED_THRESHOLD,
                    )
                    med = _pick_med_by_class("dyslipidemia")
                    med_tail = t("chronic_assessment.med_continue_tail", lang, med=med) if med else ""
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

            # ── I48: Atrial fibrillation / flutter ─────────────────────
            # Anticoagulation is the primary monitoring axis. INR is the
            # therapeutic marker for warfarin (2.0-3.0 for non-valvular
            # AFib per ACC/AHA + JCS guidelines); DOACs skip INR but the
            # med-continuation tail still records the drug.
            elif code_prefix.startswith("I48"):
                parts_afib: list[str] = []
                inr = lab_by_name.get("pt-inr") or lab_by_name.get("pt_inr") or lab_by_name.get("inr")
                if inr:
                    v, u = inr
                    try:
                        vf = float(v)
                        if 2.0 <= vf <= 3.0:
                            ctrl = t("control_status.inr_therapeutic", lang)
                        elif vf < 2.0:
                            ctrl = t("control_status.inr_subtherapeutic", lang)
                        else:
                            ctrl = t("control_status.inr_supratherapeutic", lang)
                    except (TypeError, ValueError):
                        ctrl = ""
                    target = t("chronic_assessment.inr_target_standard", lang)
                    parts_afib.append(f"PT-INR {v} — {target} — {ctrl}" if ctrl else f"PT-INR {v} — {target}")
                med = _pick_med_by_class("afib_anticoagulation")
                if med:
                    parts_afib.append(t("prescription.medication_continue", lang, med=med))
                if parts_afib:
                    interp = t("list_sep.serial", lang).join(parts_afib) + t("list_sep.period", lang)

            # ── J44: COPD (stable) ─────────────────────────────────────
            elif code_prefix.startswith("J44"):
                spo2 = _o(v0, "spo2", None) if v0 else None
                bits: list[str] = []
                if spo2:
                    bits.append(f"SpO2 {float(spo2):.0f}%")
                med = _pick_med_by_class("copd")
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
                med = _pick_med_by_class("asthma")
                if med:
                    bits2.append(t("prescription.medication_continue", lang, med=med))
                if bits2:
                    interp = t("list_sep.serial", lang).join(bits2) + (t("chronic_monitoring.act_control_review", lang))

            if interp:
                lines.append(f"{i}. {label}: {interp}")
            else:
                # Issue #1776: the pre-fix fallback re-cited Objective-
                # section vitals (BP / HR / T / SpO2) and emitted a
                # "today's measurements not condition-specific; defer
                # focused review" clause that admitted no clinical
                # reasoning fired. That phrase saturated 74% of
                # populated narratives (197k / 263k on US p=10k seed=42
                # 5y) and taught downstream LLMs a procrastination
                # pattern. Replace with a structured-data fallback that
                # reads the chronic condition's ``stage`` (populated by
                # the longitudinal engine as of #1753): staged → cite
                # the stage; stageless → acknowledge the problem-list
                # entry with no acute change. Neither phrase re-quotes
                # the vitals and neither defers the judgement.
                condition_stage = str(_o(c, "stage", "") or "").strip()
                if condition_stage:
                    follow = t(
                        "chronic_assessment.chronic_stage_stable",
                        lang,
                        label=label,
                        stage=condition_stage,
                    )
                    lines.append(follow)
                else:
                    follow = t("chronic_assessment.chronic_noted", lang, label=label)
                    lines.append(f"{i}. {follow}")

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
            vital_lines.append(t("chronic_assessment.tachycardia", lang, hr=int(round(hr_f))))
        if spo2_f is not None and spo2_f < 95:
            key = "chronic_assessment.hypoxemia_severe" if spo2_f < 90 else "chronic_assessment.hypoxemia"
            vital_lines.append(t(key, lang, spo2=spo2_f))
        if temp_f is not None and temp_f >= 38.0:
            vital_lines.append(t("chronic_assessment.fever", lang, temp=temp_f))
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
            # Drug-name katakana lookup via lang-aware wrapper.
            from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

            drug = localize_drug_name(drug, lang)
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
            if isinstance(m, str):
                # Drug-name katakana lookup for str-only entries via
                # lang-aware wrapper (dict entries already routed through
                # `_render_home_med_name`).
                from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

                n = localize_drug_name(m, lang)
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

    # ─────────────────────────────────────────────────────────────────
    # ED_NOTE section builders — thin delegators dispatching to
    # free-standing functions in ``renderers/section_builders/ed_note.py``
    # (full-review Phase C1j, CRITICAL C1).
    # ─────────────────────────────────────────────────────────────────

    def _build_triage_details(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
            build_triage_details,
        )

        return build_triage_details(self, ctx)

    def _build_ed_physical_exam(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
            build_ed_physical_exam,
        )

        return build_ed_physical_exam(self, ctx)

    def _build_ed_workup(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
            build_ed_workup,
        )

        return build_ed_workup(self, ctx)

    def _build_ed_disposition(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
            build_ed_disposition,
        )

        return build_ed_disposition(self, ctx)

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

    # ─────────────────────────────────────────────────────────────────
    # DEATH_CERTIFICATE + DEATH_DISCHARGE_SUMMARY section builders —
    # thin delegators dispatching to free-standing functions in
    # ``renderers/section_builders/mortality.py`` (full-review Phase C1f,
    # CRITICAL C1). ``_render_composition_sections`` still looks up
    # ``generator._build_<section>`` by name, so the method entry point
    # stays on the class. The DC/DDS-local helpers
    # (``_dc_resolve_primary_cause``, ``_dc_disease_pattern``,
    # ``_dc_admission_to_discharge_hours``, ``_dc_duration_phrase``,
    # ``_dds_severity``) are moved alongside the builders — no caller
    # outside the DC/DDS cluster uses them.
    # ─────────────────────────────────────────────────────────────────

    def _build_dc_immediate_cause(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dc_immediate_cause,
        )

        return build_dc_immediate_cause(self, ctx)

    def _build_dc_duration_of_immediate_cause(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dc_duration_of_immediate_cause,
        )

        return build_dc_duration_of_immediate_cause(self, ctx)

    def _build_dc_underlying_cause(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dc_underlying_cause,
        )

        return build_dc_underlying_cause(self, ctx)

    def _build_dc_contributing_conditions(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dc_contributing_conditions,
        )

        return build_dc_contributing_conditions(self, ctx)

    def _build_dc_manner_of_death(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dc_manner_of_death,
        )

        return build_dc_manner_of_death(self, ctx)

    def _build_dc_autopsy_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dc_autopsy_status,
        )

        return build_dc_autopsy_status(self, ctx)

    def _build_dds_admission_state(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_admission_state,
        )

        return build_dds_admission_state(self, ctx)

    def _build_dds_treatment_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_treatment_course,
        )

        return build_dds_treatment_course(self, ctx)

    def _build_dds_terminal_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_terminal_course,
        )

        return build_dds_terminal_course(self, ctx)

    def _build_dds_circumstances_of_death(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_circumstances_of_death,
        )

        return build_dds_circumstances_of_death(self, ctx)

    def _build_dds_cause_of_death(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_cause_of_death,
        )

        return build_dds_cause_of_death(self, ctx)

    def _build_dds_complications_and_comorbidities(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_complications_and_comorbidities,
        )

        return build_dds_complications_and_comorbidities(self, ctx)

    def _build_dds_family_communication(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_family_communication,
        )

        return build_dds_family_communication(self, ctx)

    def _build_dds_autopsy_status_and_findings(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
            build_dds_autopsy_status_and_findings,
        )

        return build_dds_autopsy_status_and_findings(self, ctx)

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

    # ─────────────────────────────────────────────────────────────────
    # OPERATIVE_NOTE + PROCEDURE_NOTE section builders — thin delegators
    # that dispatch to free-standing functions in
    # ``renderers/section_builders/op_pn_notes.py`` (full-review Phase
    # C1d, CRITICAL C1). ``_render_composition_sections`` still looks up
    # ``generator._build_<section>`` by name, so the method entry point
    # stays on the class.
    # ─────────────────────────────────────────────────────────────────

    def _build_op_procedure_name(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_procedure_name,
        )

        return build_op_procedure_name(self, ctx)

    def _build_op_anesthesia(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_anesthesia,
        )

        return build_op_anesthesia(self, ctx)

    def _build_op_surgeon(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_surgeon,
        )

        return build_op_surgeon(self, ctx)

    def _build_op_findings(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_findings,
        )

        return build_op_findings(self, ctx)

    def _build_op_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_course,
        )

        return build_op_course(self, ctx)

    def _build_op_specimens(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_specimens,
        )

        return build_op_specimens(self, ctx)

    def _build_op_blood_loss(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_blood_loss,
        )

        return build_op_blood_loss(self, ctx)

    def _build_op_equipment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_equipment,
        )

        return build_op_equipment(self, ctx)

    def _build_op_postop_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_op_postop_plan,
        )

        return build_op_postop_plan(self, ctx)

    def _build_pn_procedure_name(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_procedure_name,
        )

        return build_pn_procedure_name(self, ctx)

    def _build_pn_consent(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_consent,
        )

        return build_pn_consent(self, ctx)

    def _build_pn_performer(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_performer,
        )

        return build_pn_performer(self, ctx)

    def _build_pn_analgesia(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_analgesia,
        )

        return build_pn_analgesia(self, ctx)

    def _build_pn_course(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_course,
        )

        return build_pn_course(self, ctx)

    def _build_pn_complications(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_complications,
        )

        return build_pn_complications(self, ctx)

    def _build_pn_specimens(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_specimens,
        )

        return build_pn_specimens(self, ctx)

    def _build_pn_postop_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
            build_pn_postop_plan,
        )

        return build_pn_postop_plan(self, ctx)

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
