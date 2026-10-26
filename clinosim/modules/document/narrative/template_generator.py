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

import logging
from datetime import datetime
from typing import Any

from clinosim.codes import lookup as code_lookup
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
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
    load_discharge_instructions,
    load_physical_exam_findings,
)
from clinosim.types.document import DocumentType, FormatType, NarrativeContext, NarrativeOutput

logger = logging.getLogger(__name__)


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

    # ─────────────────────────────────────────────────────────────────
    # chief_complaint section builder — thin delegator dispatching to
    # the free-standing function in
    # ``renderers/section_builders/chief_complaint.py`` (full-review
    # Phase C1n, CRITICAL C1). The 3 cluster-local static helpers
    # (``_disease_canonical_cc``, ``_maybe_swap_cc_variant``,
    # ``_cc_variant_index``) moved alongside.
    # ─────────────────────────────────────────────────────────────────

    def _build_chief_complaint(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import (
            build_chief_complaint,
        )

        return build_chief_complaint(self, ctx)

    # ─────────────────────────────────────────────────────────────────
    # hpi section builder — thin delegator dispatching to the
    # free-standing function in ``renderers/section_builders/hpi.py``
    # (full-review Phase C1o, CRITICAL C1). The 3 HPI-cluster helpers
    # (``_build_hpi_core``, ``_maybe_append_newborn_workup``,
    # ``_compose_hpi_extras_from_state``) moved alongside.
    # ─────────────────────────────────────────────────────────────────

    def _build_hpi(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.hpi import (
            build_hpi,
        )

        return build_hpi(self, ctx)

    def _build_past_medical_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
            build_past_medical_history,
        )

        return build_past_medical_history(self, ctx)

    def _build_medications_at_home(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
            build_medications_at_home,
        )

        return build_medications_at_home(self, ctx)

    def _build_allergies(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
            build_allergies,
        )

        return build_allergies(self, ctx)

    def _build_social_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
            build_social_history,
        )

        return build_social_history(self, ctx)

    def _build_family_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
            build_family_history,
        )

        return build_family_history(self, ctx)

    def _build_physical_examination(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
            build_physical_examination,
        )

        return build_physical_examination(self, ctx)

    # ─────────────────────────────────────────────────────────────────
    # assessment_and_plan section builder — thin delegator dispatching
    # to the free-standing function in
    # ``renderers/section_builders/assessment_and_plan.py`` (full-review
    # Phase C1m, CRITICAL C1). The 2 outpatient/admission-only
    # composers (``_compose_ap_assessment_from_state``,
    # ``_compose_ap_plan_from_state``) moved alongside; private-method
    # delegators preserved below for the test
    # (``test_assessment_and_plan.py`` reaches
    # ``gen._compose_ap_plan_from_state`` directly).
    # ─────────────────────────────────────────────────────────────────

    def _build_assessment_and_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
            build_assessment_and_plan,
        )

        return build_assessment_and_plan(self, ctx)

    def _compose_ap_assessment_from_state(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
            _compose_ap_assessment_from_state,
        )

        return _compose_ap_assessment_from_state(ctx)

    def _compose_ap_plan_from_state(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers.section_builders.assessment_and_plan import (
            _compose_ap_plan_from_state,
        )

        return _compose_ap_plan_from_state(self, ctx)

    def _build_admission_summary(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
            build_admission_summary,
        )

        return build_admission_summary(self, ctx)

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

    # ─────────────────────────────────────────────────────────────────
    # OUTPATIENT_SOAP section builders — thin delegators dispatching to
    # free-standing functions in
    # ``renderers/section_builders/outpatient_soap.py`` (full-review
    # Phase C1l, CRITICAL C1). The 10 outpatient-only composers moved
    # alongside (``_get_soap_template``, ``_compose_outpatient_subjective_from_state``,
    # ``_compose_ed_assessment_from_state``, ``_compose_encounter_reason_line``,
    # ``_compose_chronic_condition_line``,
    # ``_compose_chronic_assessment_integrated``,
    # ``_compose_today_prescription_line``, ``_compose_today_procedures_line``,
    # ``_compose_follow_up_line``, ``_compose_current_medications_line``).
    # ─────────────────────────────────────────────────────────────────

    # Private-helper delegators preserved for tests that reach in by
    # name (test_chronic_assessment_structured_fallback_1776,
    # test_assessment_observation_aware, test_dm_nathan_consistency,
    # test_plan_variation). Behavior is identical to the free-standing
    # functions in the extracted module.

    def _compose_chronic_assessment_integrated(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            _compose_chronic_assessment_integrated,
        )

        return _compose_chronic_assessment_integrated(ctx)

    def _compose_follow_up_line(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            _compose_follow_up_line,
        )

        return _compose_follow_up_line(ctx)

    def _compose_encounter_reason_line(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            _compose_encounter_reason_line,
        )

        return _compose_encounter_reason_line(ctx)

    def _compose_ed_assessment_from_state(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            _compose_ed_assessment_from_state,
        )

        return _compose_ed_assessment_from_state(ctx)

    def _compose_today_prescription_line(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            _compose_today_prescription_line,
        )

        return _compose_today_prescription_line(ctx)

    def _build_outpatient_subjective(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            build_outpatient_subjective,
        )

        return build_outpatient_subjective(self, ctx)

    def _build_outpatient_objective(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            build_outpatient_objective,
        )

        return build_outpatient_objective(self, ctx)

    def _build_outpatient_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            build_outpatient_assessment,
        )

        return build_outpatient_assessment(self, ctx)

    def _build_outpatient_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
            build_outpatient_plan,
        )

        return build_outpatient_plan(self, ctx)

    def _compose_progress_subjective_from_state(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers._composers import (
            compose_progress_subjective_from_state,
        )

        return compose_progress_subjective_from_state(ctx)

    def _compose_progress_assessment_from_state(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers._composers import (
            compose_progress_assessment_from_state,
        )

        return compose_progress_assessment_from_state(ctx)

    def _compose_progress_plan_from_state(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers._composers import (
            compose_progress_plan_from_state,
        )

        return compose_progress_plan_from_state(ctx)

    def _compose_today_vitals_line(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers._composers import (
            compose_today_vitals_line,
        )

        return compose_today_vitals_line(ctx)

    def _compose_pe_vitals_line(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers._composers import (
            compose_pe_vitals_line,
        )

        return compose_pe_vitals_line(ctx)

    def _apply_cc_pe_consistency(self, text: str, ctx: NarrativeContext) -> tuple[str, list[str]]:
        from clinosim.modules.document.narrative.renderers._composers import (
            apply_cc_pe_consistency,
        )

        return apply_cc_pe_consistency(text, ctx)

    def _compose_vital_signs_line(self, ctx: NarrativeContext) -> str:
        from clinosim.modules.document.narrative.renderers._composers import (
            compose_vital_signs_line,
        )

        return compose_vital_signs_line(ctx)

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
