"""Template-based narrative generator (Tier 1 #3 α-min-1 PR1 Task 6).

Stage 1 default generator producing deterministic narrative text from CIF
+ disease YAML + reference data. No LLM dependency. Dispatches by
DocumentTypeSpec.format_type to one of 3 renderers.

Multi-day fallback chain (Task 4 lesson):
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
str.format_map() with named placeholders. For α-min-1, templates that
require computed values (e.g. "{onset_days_ago}日前より") use a fixed
reasonable default (3 days) when onset cannot be derived from CIF without
complex date arithmetic.
"""

from __future__ import annotations

import logging
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import strip_protocol_prefix
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.modules.document.reference_data_loaders import (
    load_discharge_instructions,
    load_physical_exam_findings,
)
from clinosim.types.document import DocumentType, FormatType, NarrativeContext, NarrativeOutput

logger = logging.getLogger(__name__)


def _pick_localized(
    tmpl: Any, key_base: str, lang: str, ctx: NarrativeContext | None = None
) -> str:
    """AD-65 Bug A fix: locale-aware field access.

    Reads `<key_base>_<lang>` from tmpl (attribute or dict access), returning
    an empty string + a warning log on missing. The silent ja fallback that
    previously caused US (en) narratives to contain Japanese characters is
    retired: a structurally empty section is preferable to silent locale
    contamination.

    β-JP-1 chain 1a: when ``ctx`` is provided, ``{placeholder}`` tokens in the
    template text are substituted via ``_fill_template_placeholders`` (the
    encounter YAML narrative templates carry them; they never reached output
    before chain 1a wired ctx.encounter_protocol).
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


class _PlaceholderDefaults(dict[str, str]):
    """format_map mapping that never raises KeyError (unknown → fallback)."""

    def __init__(self, mapping: dict[str, str], fallback: str):
        super().__init__(mapping)
        self._fallback = fallback

    def __missing__(self, key: str) -> str:
        return self._fallback


def _fill_template_placeholders(text: str, ctx: NarrativeContext, lang: str) -> str:
    """Substitute `{placeholder}` tokens in encounter-template text (chain 1a).

    Known placeholders:
      - ``{onset_days}`` → fixed default 3 (α-min-1 convention, see module
        docstring: computed values use a fixed reasonable default until they
        can be derived from CIF).
      - ``{chief_complaint_ja}`` / ``{chief_complaint_en}`` → the encounter
        protocol's own ``chief_complaint`` multi-language dict.

    Every other placeholder (``{lab_summary_ja}``, ``{severity_desc_en}``,
    ...) resolves to the locale generic phrase — raw braces must never leak
    into narrative output, and a generic phrase is the pre-chain-1a behavior
    for those slots (β-JP-1 chain 1b may derive real values from CIF).
    """
    if "{" not in text:
        return text
    is_ja = lang == "ja"
    cc = _o(ctx.encounter_protocol, "chief_complaint", {}) if ctx.encounter_protocol else {}
    if not isinstance(cc, dict):
        cc = {}
    generic = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
    mapping = _PlaceholderDefaults(
        {
            "onset_days": "3",
            "chief_complaint_ja": str(cc.get("ja") or "") or generic,
            "chief_complaint_en": str(cc.get("en") or "") or generic,
        },
        generic,
    )
    try:
        return text.format_map(mapping)
    except (ValueError, IndexError):
        # Malformed braces (e.g. literal "{" in clinical text) — emit as-is
        # rather than raise; never fail narrative generation on template data.
        return text


# Generic fallback phrases per locale
_GENERIC_FALLBACK_JA = "特記事項なし"
_GENERIC_FALLBACK_EN = "No special findings"
_GENERIC_ASSESSMENT_JA = "経過観察中"
_GENERIC_ASSESSMENT_EN = "Clinical assessment ongoing"
_GENERIC_PLAN_JA = "治療継続"
_GENERIC_PLAN_EN = "Continue current management"

# α-min-2: Nursing section fallback phrases
_NURSING_HISTORY_FALLBACK_JA = "入院目的・既往歴：特記事項なし"
_NURSING_HISTORY_FALLBACK_EN = "Nursing history: no significant findings"
_ADL_FALLBACK_JA = "ADL：自立（問題なし）"
_ADL_FALLBACK_EN = "ADL: independent (no issues noted)"
_RISK_FALLBACK_JA = "転倒・褥瘡リスク：評価中"
_RISK_FALLBACK_EN = "Fall / pressure ulcer risk: assessment pending"
_NURSING_DX_FALLBACK_JA = "看護診断：特記事項なし"
_NURSING_DX_FALLBACK_EN = "Nursing diagnosis: no significant findings"
_CARE_PLAN_FALLBACK_JA = "看護計画：標準的ケア継続"
_CARE_PLAN_FALLBACK_EN = "Care plan: continue standard nursing care"
_INTERVENTIONS_FALLBACK_JA = "実施した看護介入：特記事項なし"
_INTERVENTIONS_FALLBACK_EN = "Nursing interventions provided: no significant findings"
_PATIENT_EDUCATION_FALLBACK_JA = "患者教育：退院指導実施"
_PATIENT_EDUCATION_FALLBACK_EN = "Patient education: discharge instructions provided"
_DISCHARGE_READINESS_FALLBACK_JA = "退院準備：退院基準を満たす"
_DISCHARGE_READINESS_FALLBACK_EN = "Discharge readiness: criteria met"

# α-min-3: nursing shift labels, keyed by the neutral shift key stored in
# structural CIF (ClinicalDocument.shift → NarrativeContext.shift). Labels are
# resolved here at render time by language (AD-30 spirit — never baked into
# CIF). Keys must cover engine.SHIFT_SCHEDULE exactly (guarded by
# tests/unit/modules/document/narrative/test_template_generator_3shift.py).
_SHIFT_LABELS_JA: dict[str, str] = {
    "night": "深夜",
    "day": "日勤",
    "evening": "準夜",
}
_SHIFT_LABELS_EN: dict[str, str] = {
    "night": "night",
    "day": "day",
    "evening": "evening",
}

# α-min-2: ED section fallback phrases
_ED_WORKUP_FALLBACK_JA = "検査・処置：特記事項なし"
_ED_WORKUP_FALLBACK_EN = "ED workup: no significant findings"
_DISPOSITION_FALLBACK_JA = "帰宅または入院加療"
_DISPOSITION_FALLBACK_EN = "Disposition: to be determined"
_TRIAGE_FALLBACK_JA = "トリアージ情報：未記録"
_TRIAGE_FALLBACK_EN = "Triage information: not recorded"

# α-min-2: Arrival mode display
_ARRIVAL_MODE_JA: dict[str, str] = {
    "ambulance": "救急車搬送",
    "walk-in": "自来院（Walk-in）",
    "helicopter": "ドクターヘリ搬送",
    "police": "警察搬送",
    "private_vehicle": "自家用車来院",
}
_ARRIVAL_MODE_EN: dict[str, str] = {
    "ambulance": "ambulance",
    "walk-in": "walk-in",
    "helicopter": "helicopter/air transport",
    "police": "police transport",
    "private_vehicle": "private vehicle",
}

# NKDA phrases per locale
_NKDA_JA = "薬物アレルギーなし（NKDA）"
_NKDA_EN = "No known drug allergies (NKDA)"

# Social history smoking labels
_SMOKING_JA: dict[str, str] = {
    "never": "非喫煙者",
    "former": "元喫煙者",
    "current": "喫煙者（現在）",
    "unknown": "喫煙歴不明",
}
_SMOKING_EN: dict[str, str] = {
    "never": "Non-smoker",
    "former": "Former smoker",
    "current": "Current smoker",
    "unknown": "Smoking history unknown",
}

# Alcohol use labels
_ALCOHOL_JA: dict[str, str] = {
    "none": "飲酒なし",
    "occasional": "機会飲酒",
    "moderate": "適度な飲酒",
    "heavy": "多量飲酒",
    "unknown": "飲酒状況不明",
}
_ALCOHOL_EN: dict[str, str] = {
    "none": "Non-drinker",
    "occasional": "Occasional drinker",
    "moderate": "Moderate drinker",
    "heavy": "Heavy drinker",
    "unknown": "Alcohol use unknown",
}

# SOAP section labels per locale
_SOAP_JA = ("S（主観）", "O（客観）", "A（評価）", "P（計画）")
_SOAP_EN = ("S:", "O:", "A:", "P:")


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

        α-min-2 new types dispatch to specialized renderers; everything else
        falls through to the existing PROGRESS_NOTE SOAP renderer.
        """
        if ctx.document_type == DocumentType.NURSING_SHIFT_NOTE:
            return self._render_nursing_shift_note_text(ctx, spec)
        if ctx.document_type == DocumentType.ED_TRIAGE_NOTE:
            return self._render_ed_triage_note_text(ctx, spec)
        return self._render_progress_note_text(ctx, spec)

    def _render_progress_note_text(
        self, ctx: NarrativeContext, spec: DocumentTypeSpec
    ) -> NarrativeOutput:
        """Build a SOAP-style progress note as plain text (PROGRESS_NOTE)."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        soap_labels = _SOAP_JA if is_ja else _SOAP_EN

        # Resolve daily trajectory for this day (with fallback chain)
        traj, traj_source = self._resolve_daily_trajectory_with_source(
            ctx, ctx.clinical_course_archetype, ctx.day_index
        )
        if traj_source:
            facts.append(traj_source)

        _generic_s = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
        _generic_a = _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN
        _generic_p = _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN
        subjective = traj.get("subjective") or _generic_s
        objective = traj.get("objective") or _generic_s
        assessment = traj.get("assessment") or _generic_a
        plan = traj.get("plan") or _generic_p

        # Add physical exam findings to the objective section
        phys_exam = self._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
        if phys_exam:
            facts.append(
                f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}"
            )
        phys_summary = self._format_physical_exam(phys_exam, ctx.severity, is_ja)
        if phys_summary:
            objective = f"{objective}。{phys_summary}" if is_ja else f"{objective}. {phys_summary}"

        # Build SOAP note
        sep = "\n"
        raw_text = sep.join([
            f"{soap_labels[0]} {subjective}",
            f"{soap_labels[1]} {objective}",
            f"{soap_labels[2]} {assessment}",
            f"{soap_labels[3]} {plan}",
        ])

        # Always add at least ctx reference
        facts.append("ctx.day_index")
        facts.append("ctx.clinical_course_archetype")

        return NarrativeOutput(
            raw_text=raw_text,
            metadata={"generator": "template", "lang": lang, "day_index": ctx.day_index},
            facts_used=facts,
        )

    # ─────────────────────────────────────────────────────────────────
    # Renderer: COMPOSITION (ADMISSION_HP, DISCHARGE_SUMMARY + α-min-2)
    # ─────────────────────────────────────────────────────────────────

    def _render_composition_sections(
        self, ctx: NarrativeContext, spec: DocumentTypeSpec
    ) -> NarrativeOutput:
        """Build section dict per spec.composition_sections."""
        facts: list[str] = []
        sections: dict[str, str] = {}

        section_builders = {
            # α-min-1 sections
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
            # α-min-2: ADMISSION_NURSING_ASSESSMENT sections
            "nursing_history": self._build_nursing_history,
            "adl_assessment": self._build_adl_assessment,
            "risk_assessments": self._build_risk_assessments,
            "nursing_diagnosis": self._build_nursing_diagnosis,
            "care_plan": self._build_care_plan,
            # α-min-2: NURSING_DISCHARGE_SUMMARY sections
            "admission_status": self._build_nursing_admission_status,
            "nursing_interventions_provided": self._build_nursing_interventions_provided,
            "patient_education": self._build_patient_education,
            "discharge_readiness": self._build_discharge_readiness,
            # α-min-2: OUTPATIENT_SOAP sections (reads encounter_protocol.narrative)
            "subjective": self._build_outpatient_subjective,
            "objective": self._build_outpatient_objective,
            "assessment": self._build_outpatient_assessment,
            "plan": self._build_outpatient_plan,
            # α-min-2: ED_NOTE sections
            "triage_details": self._build_triage_details,
            "physical_exam": self._build_ed_physical_exam,
            "ed_workup": self._build_ed_workup,
            "disposition": self._build_ed_disposition,
        }

        for section in spec.composition_sections:
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

    def _render_structured_form(
        self, ctx: NarrativeContext, spec: DocumentTypeSpec
    ) -> NarrativeOutput:
        """QUESTIONNAIRE_RESPONSE infrastructure stub for α-min-1.

        Returns empty structured dict with metadata indicating stub stage.
        β-JP-1 phase will implement the full form structure.
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

    def _build_chief_complaint(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build chief_complaint section.

        For ED_NOTE: reads from
        encounter_protocol.narrative.ed_note_template.chief_complaint_<lang>
        (with fallback to generic). For all other document types: reads from disease_protocol.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = "発熱・全身倦怠感" if is_ja else "Chief complaint not specified"

        # α-min-2: ED_NOTE reads from ed_note_template
        if ctx.document_type == DocumentType.ED_NOTE:
            ed_tmpl = self._get_ed_note_template(ctx)
            if ed_tmpl is not None:
                text = _pick_localized(ed_tmpl, "chief_complaint", lang, ctx)
                if text:
                    facts.append(
                        f"encounter_protocol.narrative.ed_note_template.chief_complaint_{lang}"
                    )
                    return text, facts
            return fallback, facts

        proto = ctx.disease_protocol
        if proto is None:
            return fallback, facts

        cc = _o(proto, "chief_complaint", None)
        if cc is None:
            return fallback, facts

        if isinstance(cc, dict):
            text = cc.get(lang) or cc.get("ja" if is_ja else "en") or cc.get("en") or fallback
            key = "ja" if is_ja else "en"
            facts_key = f"disease_protocol.chief_complaint.{key}"
            if text == fallback:
                facts_key += ":fallback"
            facts.append(facts_key)
        else:
            # Plain string (pre-Task-4 format)
            text = str(cc)
            facts.append("disease_protocol.chief_complaint:str")

        return text, facts

    def _build_hpi(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build HPI section.

        For ED_NOTE: reads from encounter_protocol.narrative.ed_note_template.hpi_<lang>.
        For all other document types: reads from narrative.hpi_template.onset_pattern[severity]
        (onset_pattern has no per-language split; see ja_only_fallback tagging below).
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = (
            f"{ctx.severity}の症状で受診。" if is_ja
            else f"Patient presented with {ctx.severity} symptoms."
        )

        # α-min-2: ED_NOTE reads from ed_note_template
        if ctx.document_type == DocumentType.ED_NOTE:
            ed_tmpl = self._get_ed_note_template(ctx)
            if ed_tmpl is not None:
                text = _pick_localized(ed_tmpl, "hpi", lang, ctx)
                if text:
                    facts.append(
                        f"encounter_protocol.narrative.ed_note_template.hpi_{lang}"
                    )
                    return text, facts
            return fallback, facts

        proto = ctx.disease_protocol
        narrative = _o(proto, "narrative", None) if proto is not None else None
        if narrative is None:
            return fallback, facts

        hpi_tmpl = _o(narrative, "hpi_template", None)
        if hpi_tmpl is None:
            return fallback, facts

        onset_pattern = _o(hpi_tmpl, "onset_pattern", {})
        if isinstance(onset_pattern, dict):
            onset_text = onset_pattern.get(ctx.severity) or onset_pattern.get("moderate") or ""
        else:
            onset_text = ""

        trigger_options = _o(hpi_tmpl, "trigger_options", []) or []
        trigger = trigger_options[0] if trigger_options else ""

        if onset_text:
            text = f"{onset_text} {trigger}".strip() if trigger else onset_text
            fact = f"disease_protocol.narrative.hpi_template.onset_pattern.{ctx.severity}"
            # hpi_template.onset_pattern (disease YAML) has no per-language split —
            # only severity keys (mild/moderate/severe), Japanese-sourced text.
            # Tag + warn for EN-locale auditability (AD-65 Bug A, documented
            # ja_only_fallback convention — see module docstring).
            if not is_ja:
                fact += ":ja_only_fallback"
                logger.warning(
                    "hpi_template.onset_pattern has no English variant; falling back "
                    "to Japanese source text for severity=%s",
                    ctx.severity,
                )
            facts.append(fact)
            if trigger:
                facts.append("disease_protocol.narrative.hpi_template.trigger_options[0]")
        else:
            text = fallback

        return text, facts

    def _build_past_medical_history(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build past medical history from ctx.patient.chronic_conditions."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        none_text = "特記既往歴なし" if is_ja else "No significant past medical history"

        patient = ctx.patient
        if patient is None:
            return none_text, facts

        conditions = _o(patient, "chronic_conditions", []) or []
        if not conditions:
            return none_text, facts

        facts.append("ctx.patient.chronic_conditions")
        # Each condition: use code field (display resolved at output time; CIF rule)
        lines = []
        for cond in conditions:
            code = _o(cond, "code", "")
            stage = _o(cond, "stage", "")
            if code:
                lines.append(f"{code}{' (' + stage + ')' if stage else ''}")
        if lines:
            return "; ".join(lines), facts
        return none_text, facts

    def _build_medications_at_home(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build home medications from ctx.patient.current_medications."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        none_text = "常用薬なし" if is_ja else "No home medications"

        patient = ctx.patient
        if patient is None:
            return none_text, facts

        meds = _o(patient, "current_medications", []) or []
        if not meds:
            return none_text, facts

        facts.append("ctx.patient.current_medications")
        return "; ".join(str(m) for m in meds), facts

    def _build_allergies(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build allergies section from ctx.allergies."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        allergies = ctx.allergies or []
        if not allergies:
            return _NKDA_JA if is_ja else _NKDA_EN, facts

        facts.append("ctx.allergies")
        parts = []
        for allergy in allergies:
            display = _o(allergy, "allergen_display", "") or ""
            criticality = _o(allergy, "criticality", "") or ""
            if display:
                if criticality:
                    crit_str = f"（{criticality}）" if is_ja else f" ({criticality})"
                    parts.append(f"{display}{crit_str}")
                else:
                    parts.append(display)
        return "; ".join(parts) if parts else (_NKDA_JA if is_ja else _NKDA_EN), facts

    def _build_social_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build social history from patient smoking_status, alcohol_use, occupation."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        patient = ctx.patient
        if patient is None:
            return _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN, facts

        smoking_status = _o(patient, "smoking_status", "unknown") or "unknown"
        alcohol_use = _o(patient, "alcohol_use", "unknown") or "unknown"
        occupation = _o(patient, "occupation", "") or ""

        smoke_map = _SMOKING_JA if is_ja else _SMOKING_EN
        alcohol_map = _ALCOHOL_JA if is_ja else _ALCOHOL_EN

        smoke_text = smoke_map.get(smoking_status, smoke_map.get("unknown", ""))
        alcohol_text = alcohol_map.get(alcohol_use, alcohol_map.get("unknown", ""))

        parts = []
        if smoke_text:
            key = "喫煙歴" if is_ja else "Smoking"
            parts.append(f"{key}: {smoke_text}")
        if alcohol_text:
            key = "飲酒歴" if is_ja else "Alcohol"
            parts.append(f"{key}: {alcohol_text}")
        if occupation:
            key = "職業" if is_ja else "Occupation"
            parts.append(f"{key}: {occupation}")

        facts.append("ctx.patient.smoking_status")
        facts.append("ctx.patient.alcohol_use")
        facts.append("ctx.patient.occupation")

        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
        return "; ".join(parts) if parts else fallback, facts

    def _build_family_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build family history — generic placeholder for α-min-1."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        text = "特記家族歴なし" if is_ja else "No significant family history"
        return text, []

    def _build_physical_examination(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build physical_examination using multi-step fallback chain."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        phys_exam = self._resolve_physical_exam(
            ctx, ctx.clinical_course_archetype, ctx.day_index
        )
        if phys_exam:
            fact = f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}"
            # physical_exam_findings (disease YAML + reference_data) carries no
            # per-language split at all (data-authoring gap, tracked separately
            # from this code fix) — content is always Japanese-sourced clinical
            # text. Tag + warn so EN-locale (US) narratives are auditable
            # instead of silently emitting Japanese with no trace (AD-65 Bug A,
            # documented ja_only_fallback convention — see module docstring).
            if not is_ja:
                fact += ":ja_only_fallback"
                logger.warning(
                    "physical_exam_findings has no English variant; falling back to "
                    "Japanese source text for archetype=%s day=%s",
                    ctx.clinical_course_archetype,
                    ctx.day_index,
                )
            facts.append(fact)

        text = self._format_physical_exam(phys_exam, ctx.severity, is_ja)
        if not text:
            text = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        return text, facts

    def _build_assessment_and_plan(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build assessment_and_plan from daily_trajectory day_0 assessment + plan."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        traj, traj_src = self._resolve_daily_trajectory_with_source(
            ctx, ctx.clinical_course_archetype, 0
        )
        if traj_src:
            # daily_trajectory (disease YAML) has no per-language split —
            # Japanese-sourced text only (same data-authoring gap class as
            # hpi_template.onset_pattern / physical_exam_findings). Tag + warn
            # for EN-locale auditability (AD-65 Bug A documented
            # ja_only_fallback convention — see module docstring; β-JP-1
            # chain 1a: this section only started emitting trajectory text
            # once ctx.disease_protocol was wired).
            if not is_ja:
                traj_src += ":ja_only_fallback"
                logger.warning(
                    "daily_trajectory has no English variant; falling back to "
                    "Japanese source text for archetype=%s",
                    ctx.clinical_course_archetype,
                )
            facts.append(traj_src)

        _generic_a = _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN
        _generic_p = _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN
        assessment = traj.get("assessment") or _generic_a
        plan = traj.get("plan") or _generic_p

        if is_ja:
            text = f"評価: {assessment}。方針: {plan}。"
        else:
            text = f"Assessment: {assessment}. Plan: {plan}."

        return text, facts

    def _build_admission_summary(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build admission_summary for DISCHARGE_SUMMARY."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        cc_text, cc_facts = self._build_chief_complaint(ctx)
        facts.extend(cc_facts)

        if is_ja:
            text = f"主訴: {cc_text}。入院日: {ctx.day_index + 1} 日目現在。"
        else:
            text = f"Chief complaint: {cc_text}. Admitted for inpatient care."

        return text, facts

    def _build_hospital_course(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build hospital_course — 1-3 sentence summary across all days."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        los = ctx.los_days or 1

        if is_ja:
            text = f"入院 {los} 日間の治療を経て経過良好。症状は改善し退院となった。"
        else:
            text = (
                f"The patient was hospitalized for {los} days. "
                "Clinical course was favorable with improvement in presenting symptoms."
            )

        return text, facts

    def _build_discharge_diagnoses(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build discharge_diagnoses from ctx.diagnoses.

        β-JP-1 chain 1a: ctx.diagnoses is now wired (clinical_diagnosis), so
        this section resolves display text at render time via
        ``clinosim.codes.lookup`` (AD-30 — CIF stores codes only; a bare
        "I63.9" in a JP narrative fails the JP language gate). Format:
        ``<display>（<code>）`` (ja) / ``<display> (<code>)`` (en); when the
        code has no authoritative entry, ``lookup`` returns the code itself
        and the section emits the code alone.
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"

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
                or ("icd-10" if is_ja else "icd-10-cm")
            )
            display = code_lookup(system, code, ctx.target_lang)
            if display and display != code:
                parts.append(f"{display}（{code}）" if is_ja else f"{display} ({code})")
            else:
                parts.append(code)

        if parts:
            return "; ".join(parts), facts

        # No codes — fall back
        cc_text, _ = self._build_chief_complaint(ctx)
        return cc_text, []

    def _build_discharge_medications(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build discharge_medications from ctx.discharge_medications (rx only).

        adv-1 I-1: reads ONLY the normalized discharge_prescription items —
        never ctx.medications (MAR), whose in-hospital entries (ICU drips,
        protocol-prefixed orders) previously leaked into this section.
        Protocol prefixes ("DVT_prophylaxis:", "antipyretic:", ...) are
        stripped via the shared AD-50 helper (same normalization as the FHIR
        medication builders).
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        none_text = "退院処方なし" if is_ja else "No discharge medications"

        meds = getattr(ctx, "discharge_medications", None) or []
        if not meds:
            return none_text, facts

        facts.append("ctx.discharge_medications")
        seen: set[str] = set()
        drug_names = []
        for med in meds:
            drug = _o(med, "drug_name", "") or ""
            drug, _protocol_category = strip_protocol_prefix(drug)
            if drug and drug not in seen:
                seen.add(drug)
                drug_names.append(drug)

        if drug_names:
            return "; ".join(drug_names), facts
        return none_text, facts

    def _build_discharge_instructions(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
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
        text = (
            follow_up_entry.get(lang)
            or follow_up_entry.get("ja")
            or follow_up_entry.get("en")
            or ""
        )
        if not text:
            text = (
                "外来フォローアップ予定" if lang == "ja"
                else "Follow up with outpatient provider"
            )
        return text, ["discharge_instructions.follow_up"]

    # ─────────────────────────────────────────────────────────────────
    # α-min-2: Free-text renderers (NURSING_SHIFT_NOTE, ED_TRIAGE_NOTE)
    # ─────────────────────────────────────────────────────────────────

    def _render_nursing_shift_note_text(
        self, ctx: NarrativeContext, spec: DocumentTypeSpec
    ) -> NarrativeOutput:
        """Build NURSING_SHIFT_NOTE as free text.

        Includes: day/shift info, primary_nurse_id (graceful when absent),
        and a generic per-shift status summary.

        α-min-3: when ``ctx.shift`` carries a neutral shift key
        ("night"/"day"/"evening" from a daily_3shift stub), the localized
        shift label (en: night/day/evening, ja: 深夜/日勤/準夜) is resolved
        here at render time and included in the header, so the 3 per-day
        notes differ at least by the shift label. ``ctx.shift == ""``
        (legacy callers) keeps the pre-α-min-3 header unchanged.

        EN locale note: nursing shift data is JP-primary in α-min-2. EN locale
        produces an English summary using the same CIF fields.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        day_num = ctx.day_index + 1  # 1-based display
        los = ctx.los_days or 1

        shift_key = ctx.shift or ""
        shift_label = ""
        if shift_key:
            facts.append("ctx.shift")
            labels = _SHIFT_LABELS_JA if is_ja else _SHIFT_LABELS_EN
            # Unknown key → render the neutral key itself (never drop silently).
            shift_label = labels.get(shift_key, shift_key)

        nurse_id = _o(ctx.encounter, "primary_nurse_id", "") or ""
        nurse_line = ""
        if nurse_id:
            facts.append("encounter.primary_nurse_id")
            if is_ja:
                nurse_line = f"担当看護師: {nurse_id}"
            else:
                nurse_line = f"Nurse: {nurse_id}"

        if is_ja:
            title = f"【看護記録({shift_label})】" if shift_label else "【看護記録】"
            header = f"{title} 入院 {day_num} 日目 / 入院予定 {los} 日間"
            status = "患者状態：バイタルサイン安定。観察・ケア継続。"
            observations = "特記事項：特記事項なし。"
        else:
            title = (
                f"[Nursing Shift Note - {shift_label} shift]" if shift_label
                else "[Nursing Shift Note]"
            )
            header = f"{title} Day {day_num} / LOS {los} days"
            status = "Patient status: vital signs stable. Observation and care ongoing."
            observations = "Notes: no significant findings."

        lines = [header]
        if nurse_line:
            lines.append(nurse_line)
        lines.extend([status, observations])
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

    def _render_ed_triage_note_text(
        self, ctx: NarrativeContext, spec: DocumentTypeSpec
    ) -> NarrativeOutput:
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
        is_ja = lang == "ja"

        triage = _o(ctx.encounter, "triage_data", None)

        if triage is None:
            raw_text = _TRIAGE_FALLBACK_JA if is_ja else _TRIAGE_FALLBACK_EN
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

        arrival_mode_display_map = _ARRIVAL_MODE_JA if is_ja else _ARRIVAL_MODE_EN
        arrival_display = arrival_mode_display_map.get(arrival_mode, arrival_mode)

        if is_ja:
            level_line = (
                f"トリアージレベル: {level_system} Level {level}" if level_system and level
                else "トリアージレベル: 未評価"
            )
            arrival_line = f"来院形態: {arrival_display}" if arrival_display else "来院形態: 不明"
            cc_line = f"主訴: {cc_summary}" if cc_summary else "主訴: 未記録"
            raw_text = "\n".join([level_line, arrival_line, cc_line])
        else:
            level_line = (
                f"Triage level: {level_system} Level {level}" if level_system and level
                else "Triage level: not assessed"
            )
            arrival_line = f"Arrival mode: {arrival_display}" if arrival_display else "Arrival mode: unknown"
            cc_line = f"Chief complaint: {cc_summary}" if cc_summary else "Chief complaint: not recorded"
            raw_text = "\n".join([level_line, arrival_line, cc_line])

        return NarrativeOutput(
            raw_text=raw_text,
            metadata={"generator": "template", "lang": lang},
            facts_used=facts,
        )

    # ─────────────────────────────────────────────────────────────────
    # α-min-2: ADMISSION_NURSING_ASSESSMENT section builders
    # ─────────────────────────────────────────────────────────────────

    def _build_nursing_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build nursing_history — admission reason + primary_nurse_id."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        nurse_id = _o(ctx.encounter, "primary_nurse_id", "") or ""
        if nurse_id:
            facts.append("encounter.primary_nurse_id")
            if is_ja:
                nurse_part = f"担当看護師: {nurse_id}。"
            else:
                nurse_part = f"Assigned nurse: {nurse_id}. "
        else:
            nurse_part = ""

        base = _NURSING_HISTORY_FALLBACK_JA if is_ja else _NURSING_HISTORY_FALLBACK_EN
        return f"{nurse_part}{base}", facts

    def _build_adl_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build adl_assessment — generic placeholder for α-min-2."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _ADL_FALLBACK_JA if is_ja else _ADL_FALLBACK_EN, []

    def _build_risk_assessments(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build risk_assessments — generic placeholder for α-min-2."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _RISK_FALLBACK_JA if is_ja else _RISK_FALLBACK_EN, []

    def _build_nursing_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build nursing_diagnosis — generic placeholder for α-min-2."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _NURSING_DX_FALLBACK_JA if is_ja else _NURSING_DX_FALLBACK_EN, []

    def _build_care_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build care_plan — generic placeholder for α-min-2."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _CARE_PLAN_FALLBACK_JA if is_ja else _CARE_PLAN_FALLBACK_EN, []

    # ─────────────────────────────────────────────────────────────────
    # α-min-2: NURSING_DISCHARGE_SUMMARY section builders
    # ─────────────────────────────────────────────────────────────────

    def _build_nursing_admission_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build admission_status for NURSING_DISCHARGE_SUMMARY."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        los = ctx.los_days or 1
        facts.append("ctx.los_days")

        if is_ja:
            text = f"入院期間: {los} 日間。入院目的達成後、退院となった。"
        else:
            text = f"Hospital stay: {los} days. Discharge criteria met."

        return text, facts

    def _build_nursing_interventions_provided(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """Build nursing_interventions_provided — generic placeholder for α-min-2."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _INTERVENTIONS_FALLBACK_JA if is_ja else _INTERVENTIONS_FALLBACK_EN, []

    def _build_patient_education(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build patient_education — generic placeholder for α-min-2."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _PATIENT_EDUCATION_FALLBACK_JA if is_ja else _PATIENT_EDUCATION_FALLBACK_EN, []

    def _build_discharge_readiness(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build discharge_readiness — generic placeholder for α-min-2."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _DISCHARGE_READINESS_FALLBACK_JA if is_ja else _DISCHARGE_READINESS_FALLBACK_EN, []

    # ─────────────────────────────────────────────────────────────────
    # α-min-2: OUTPATIENT_SOAP section builders
    # Reads from encounter_protocol.narrative.outpatient_soap_template via
    # _pick_localized(soap, "<field>", ctx.target_lang) (AD-65 Bug A fix).
    # A missing "<field>_en" (currently the case for all encounter YAMLs —
    # data-authoring gap, not a code bug) yields a generic English fallback
    # phrase with a warn log, instead of silently emitting Japanese text.
    # ─────────────────────────────────────────────────────────────────

    def _get_soap_template(self, ctx: NarrativeContext) -> Any | None:
        """Extract outpatient_soap_template from encounter_protocol (or None)."""
        ep = ctx.encounter_protocol
        if ep is None:
            return None
        narrative = _o(ep, "narrative", None)
        if narrative is None:
            return None
        return _o(narrative, "outpatient_soap_template", None)

    def _build_outpatient_subjective(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP subjective from outpatient_soap_template.subjective_<lang>."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        soap = self._get_soap_template(ctx)
        if soap is None:
            return fallback, facts

        text = _pick_localized(soap, "subjective", lang, ctx)
        if not text:
            return fallback, facts

        facts.append(f"encounter_protocol.narrative.outpatient_soap_template.subjective_{lang}")
        return text, facts

    def _build_outpatient_objective(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP objective from outpatient_soap_template.objective_<lang>."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        soap = self._get_soap_template(ctx)
        if soap is None:
            return fallback, facts

        text = _pick_localized(soap, "objective", lang, ctx)
        if not text:
            return fallback, facts

        facts.append(f"encounter_protocol.narrative.outpatient_soap_template.objective_{lang}")
        return text, facts

    def _build_outpatient_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP assessment from outpatient_soap_template.assessment_<lang>.

        Also handles ED_NOTE context (falls back to generic if no encounter_protocol).
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        # ED_NOTE: read from ed_note_template (no separate assessment field in current schema;
        # use generic assessment fallback — ED assessment is embedded in ed_workup)
        if ctx.document_type == DocumentType.ED_NOTE:
            fallback = _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN
            return fallback, facts

        fallback = _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN
        soap = self._get_soap_template(ctx)
        if soap is None:
            return fallback, facts

        text = _pick_localized(soap, "assessment", lang, ctx)
        if not text:
            return fallback, facts

        facts.append(f"encounter_protocol.narrative.outpatient_soap_template.assessment_{lang}")
        return text, facts

    def _build_outpatient_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP plan from outpatient_soap_template.plan_<lang>."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN

        soap = self._get_soap_template(ctx)
        if soap is None:
            return fallback, facts

        text = _pick_localized(soap, "plan", lang, ctx)
        if not text:
            return fallback, facts

        facts.append(f"encounter_protocol.narrative.outpatient_soap_template.plan_{lang}")
        return text, facts

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
        is_ja = lang == "ja"
        fallback = _TRIAGE_FALLBACK_JA if is_ja else _TRIAGE_FALLBACK_EN

        triage = _o(ctx.encounter, "triage_data", None)
        if triage is None:
            return fallback, facts

        facts.append("encounter.triage_data")
        level = _o(triage, "level", "") or ""
        level_system = _o(triage, "level_system", "") or ""
        arrival_mode = _o(triage, "arrival_mode", "") or ""
        arrival_map = _ARRIVAL_MODE_JA if is_ja else _ARRIVAL_MODE_EN
        arrival_display = arrival_map.get(arrival_mode, arrival_mode)

        if level_system and level:
            level_text = f"{level_system} Level {level}"
        else:
            level_text = "未評価" if is_ja else "not assessed"

        if is_ja:
            text = (
                f"トリアージレベル: {level_text}。"
                f"来院形態: {arrival_display or '不明'}。"
            )
        else:
            text = (
                f"Triage level: {level_text}. "
                f"Arrival mode: {arrival_display or 'unknown'}."
            )

        return text, facts

    def _build_ed_physical_exam(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build physical_exam for ED_NOTE from ed_note_template.physical_exam_<lang>."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is None:
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
        # etc.; β-JP-1 chain 1a, same policy as _pick_localized).
        systems = ("general", "cardiovascular", "respiratory", "abdominal", "neurological")
        parts = []
        for sys_key in systems:
            val = _o(pe, sys_key, "") or ""
            if val:
                parts.append(_fill_template_placeholders(str(val), ctx, lang))

        if parts:
            facts.append(f"encounter_protocol.narrative.ed_note_template.{field}")
            sep = "。" if is_ja else ". "
            return sep.join(parts), facts

        return fallback, facts

    def _build_ed_workup(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build ed_workup from ed_note_template.ed_workup_summary_<lang>."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _ED_WORKUP_FALLBACK_JA if is_ja else _ED_WORKUP_FALLBACK_EN

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is None:
            return fallback, facts

        text = _pick_localized(ed_tmpl, "ed_workup_summary", lang, ctx)
        if not text:
            return fallback, facts

        facts.append(f"encounter_protocol.narrative.ed_note_template.ed_workup_summary_{lang}")
        return text, facts

    def _build_ed_disposition(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build disposition from ed_note_template.disposition_<lang>."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _DISPOSITION_FALLBACK_JA if is_ja else _DISPOSITION_FALLBACK_EN

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is None:
            return fallback, facts

        text = _pick_localized(ed_tmpl, "disposition", lang, ctx)
        if not text:
            return fallback, facts

        facts.append(f"encounter_protocol.narrative.ed_note_template.disposition_{lang}")
        return text, facts

    # ─────────────────────────────────────────────────────────────────
    # Fallback helpers
    # ─────────────────────────────────────────────────────────────────

    def _resolve_physical_exam(
        self, ctx: NarrativeContext, archetype: str, day_index: int
    ) -> dict[str, Any]:
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

    def _resolve_daily_trajectory(
        self, ctx: NarrativeContext, archetype: str, day_index: int
    ) -> dict[str, str]:
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
                source = (
                    f"disease_protocol.course_archetypes.{archetype}"
                    f".daily_trajectory.{day_key}"
                )
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
        is_ja = ctx.target_lang == "ja"
        return {
            "subjective": _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN,
            "objective": _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN,
            "assessment": _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN,
            "plan": _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN,
        }

    def _resolve_discharge_instructions(
        self, ctx: NarrativeContext
    ) -> dict[str, dict[str, str]]:
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
                _di_sections = (
                    "follow_up", "activity", "medications", "emergency", "diet_lifestyle"
                )
                for section in _di_sections:
                    sec_data = _o(proto_di, section, {})
                    if isinstance(sec_data, dict) and (sec_data.get("en") or sec_data.get("ja")):
                        merged[section] = dict(sec_data)

        return merged

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

    def _format_physical_exam(
        self, phys_exam: dict[str, Any], severity: str, is_ja: bool
    ) -> str:
        """Format a physical exam findings dict to a single text string.

        Picks the most appropriate severity level per system:
          - prefer "all" (severity-agnostic) if present
          - else pick severity-matched text (mild/moderate/severe)
          - else pick any non-empty text
        """
        if not phys_exam:
            return ""

        body_system_labels_ja = {
            "general": "一般状態",
            "cardiovascular": "循環器",
            "respiratory": "呼吸器",
            "abdominal": "腹部",
            "neurological": "神経",
        }
        body_system_labels_en = {
            "general": "General",
            "cardiovascular": "Cardiovascular",
            "respiratory": "Respiratory",
            "abdominal": "Abdomen",
            "neurological": "Neurological",
        }
        labels = body_system_labels_ja if is_ja else body_system_labels_en

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
                label = labels.get(sys_key, sys_key)
                parts.append(f"{label}: {text}")

        return "。".join(parts) if is_ja else ". ".join(parts)
