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
from typing import Any

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
        from clinosim.modules.document.narrative.renderers._resolvers import (
            resolve_physical_exam,
        )

        return resolve_physical_exam(self, ctx, archetype, day_index)

    def _resolve_daily_trajectory(self, ctx: NarrativeContext, archetype: str, day_index: int) -> dict[str, str]:
        from clinosim.modules.document.narrative.renderers._resolvers import (
            resolve_daily_trajectory,
        )

        return resolve_daily_trajectory(self, ctx, archetype, day_index)

    def _resolve_daily_trajectory_with_source(
        self, ctx: NarrativeContext, archetype: str, day_index: int
    ) -> tuple[dict[str, str], str]:
        from clinosim.modules.document.narrative.renderers._resolvers import (
            resolve_daily_trajectory_with_source,
        )

        return resolve_daily_trajectory_with_source(self, ctx, archetype, day_index)

    def _resolve_discharge_instructions(self, ctx: NarrativeContext) -> dict[str, dict[str, str]]:
        from clinosim.modules.document.narrative.renderers._resolvers import (
            resolve_discharge_instructions,
        )

        return resolve_discharge_instructions(ctx)

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
        from clinosim.modules.document.narrative.renderers._shared_helpers import (
            primary_surgical_procedure,
        )

        return primary_surgical_procedure(ctx)

    def _resolve_procedure_display(self, proc: Any, lang: str) -> str:
        from clinosim.modules.document.narrative.renderers._shared_helpers import (
            resolve_procedure_display,
        )

        return resolve_procedure_display(proc, lang)

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
        from clinosim.modules.document.narrative.renderers._shared_helpers import (
            pydantic_day_findings_to_dict,
        )

        return pydantic_day_findings_to_dict(day_findings)

    def _format_physical_exam(self, phys_exam: dict[str, Any], severity: str, lang: str) -> str:
        from clinosim.modules.document.narrative.renderers._shared_helpers import (
            format_physical_exam,
        )

        return format_physical_exam(phys_exam, severity, lang)
