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
import string
from datetime import datetime, timedelta
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


# Placeholders _fill_template_placeholders can resolve today (chain 1a
# statics + chain 1b T4 vitals). Everything else ({lab_summary_ja},
# {severity_desc_en}, {weight}, ...) makes the whole section fall back to the
# locale generic phrase.
_KNOWN_PLACEHOLDERS = frozenset({"onset_days", "chief_complaint_ja", "chief_complaint_en"})

# β-JP-1 chain 1b T4: numeric vitals placeholders resolved from ctx.vitals
# (wired in chain 1a). Placeholder name → structural-CIF vital_signs field.
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


def _resolve_vital_placeholders(
    ctx: NarrativeContext, wanted: set[str]
) -> dict[str, str]:
    """T4: resolve vitals placeholders from ctx.vitals for the stub's day.

    Readings are ranked by day distance to (admission date + ctx.day_index),
    ties broken by original list order (structural CIF vital_signs order is
    chronological + deterministic — AD-16, no RNG). Per placeholder, the
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
    target_date = (
        admission_dt.date() + timedelta(days=ctx.day_index)
        if admission_dt is not None
        else None
    )

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
    """Substitute `{placeholder}` tokens in encounter-template text (chain 1a).

    Known placeholders:
      - ``{onset_days}`` → fixed default 3 (α-min-1 convention, see module
        docstring: computed values use a fixed reasonable default until they
        can be derived from CIF).
      - ``{chief_complaint_ja}`` / ``{chief_complaint_en}`` → the encounter
        protocol's own ``chief_complaint`` multi-language dict.
      - ``{sbp}`` / ``{dbp}`` / ``{hr}`` / ``{temp}`` / ``{spo2}`` / ``{rr}``
        (chain 1b T4) → nearest non-null reading in ``ctx.vitals`` for the
        stub's day (``_resolve_vital_placeholders``).

    adv-1 I-2: if the text carries ANY placeholder outside the known set —
    including a vitals placeholder with NO resolvable reading — the WHOLE
    text falls back to the locale generic phrase (pre-chain-1a parity). The
    earlier per-placeholder generic substitution produced broken sentences
    ("BP No special findings/No special findings mmHg").
    """
    if "{" not in text:
        return text
    is_ja = lang == "ja"
    generic = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
    try:
        fields = {
            fname
            for _, fname, _, _ in string.Formatter().parse(text)
            if fname is not None
        }
    except ValueError:
        # Malformed braces (e.g. literal "{" in clinical text) — emit as-is
        # rather than raise; never fail narrative generation on template data.
        return text
    if not fields:
        return text
    vital_values = _resolve_vital_placeholders(
        ctx, fields & _VITAL_PLACEHOLDER_FIELDS.keys()
    )
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

# chain 2: ADMISSION_CARE_PLAN fallback phrases
_ACP_WARD_ROOM_FALLBACK_JA = "病棟・病室：未定"
_ACP_WARD_ROOM_FALLBACK_EN = "Ward/Room: not yet assigned"
_ACP_OTHER_STAFF_FALLBACK_JA = "担当なし"
_ACP_OTHER_STAFF_FALLBACK_EN = "No additional staff assigned"
_ACP_TEST_SCHEDULE_FALLBACK_JA = "検査：担当医の判断により決定"
_ACP_TEST_SCHEDULE_FALLBACK_EN = "Tests: to be determined by the attending physician"
_ACP_SURGERY_NONE_JA = "手術：予定なし"
_ACP_SURGERY_NONE_EN = "Surgery: none planned"
_ACP_NUTRITION_NO_JA = "特別な栄養管理の必要性：無"
_ACP_NUTRITION_NO_EN = "Special nutritional management required: No"
_ACP_OTHER_PLANS_JA = "その他：看護計画・リハビリテーション等の計画については看護記録を参照。"
_ACP_OTHER_PLANS_EN = (
    "Other: see nursing documentation for the nursing care plan and rehabilitation plan."
)

# chain 2: NUTRITION_CARE_PLAN fallback phrases
_NCP_DIETITIAN_FALLBACK_JA = "担当なし"
_NCP_DIETITIAN_FALLBACK_EN = "No dietitian assigned"
_NCP_ASSESSMENT_FALLBACK_JA = "栄養状態の評価と課題：特記事項なし"
_NCP_ASSESSMENT_FALLBACK_EN = "Nutrition status assessment: no significant findings"
_NCP_GOALS_FALLBACK_JA = "栄養管理計画の目標：現在の栄養状態を維持"
_NCP_GOALS_FALLBACK_EN = "Nutrition management goal: maintain current nutritional status"
_NCP_DYSPHAGIA_NONE_JA = "嚥下調整食の必要性：なし"
_NCP_DYSPHAGIA_NONE_EN = "Dysphagia diet required: No"
_NCP_DIETARY_CONTENT_FALLBACK_JA = "食事内容：常食"
_NCP_DIETARY_CONTENT_FALLBACK_EN = "Dietary content: regular diet"
_NCP_COUNSELING_FALLBACK_JA = "栄養食事相談：必要に応じて実施"
_NCP_COUNSELING_FALLBACK_EN = "Nutrition counseling: to be provided as needed"
_NCP_OTHER_ISSUES_FALLBACK_JA = "その他栄養管理上の課題：特記事項なし"
_NCP_OTHER_ISSUES_FALLBACK_EN = "Other nutrition management issues: none noted"
_NCP_REASSESSMENT_FALLBACK_JA = "栄養状態の再評価：入院後1週間を目安に実施"
_NCP_REASSESSMENT_FALLBACK_EN = (
    "Nutrition status reassessment: planned approximately 1 week after admission"
)
_NCP_DISCHARGE_EVAL_FALLBACK_JA = "退院時及び終了時の総合的評価：退院時に評価予定"
_NCP_DISCHARGE_EVAL_FALLBACK_EN = (
    "Comprehensive evaluation at discharge: pending, to be assessed at discharge"
)

# chain 2: REHABILITATION_PLAN fallback phrases
_RP_TEAM_FALLBACK_JA = "リハビリ実施なし"
_RP_TEAM_FALLBACK_EN = "No rehabilitation therapy on record"
_RP_THERAPIST_FALLBACK_JA = "担当者未定"
_RP_THERAPIST_FALLBACK_EN = "Named therapist: not yet assigned"
_RP_FUNCTIONAL_FALLBACK_JA = "機能評価：記録なし"
_RP_FUNCTIONAL_FALLBACK_EN = "Functional assessment: no record"
_RP_MOVEMENT_FALLBACK_JA = "基本動作：記録なし"
_RP_MOVEMENT_FALLBACK_EN = "Basic movement: no record"
_RP_FREQUENCY_FALLBACK_JA = "実施回数：記録なし"
_RP_FREQUENCY_FALLBACK_EN = "Session frequency: no record"
_RP_GOALS_FALLBACK_JA = (
    "本人の希望：現在の身体機能の回復・自宅復帰を希望／"
    "家族の希望：早期の日常生活動作自立を希望"
)
_RP_GOALS_FALLBACK_EN = (
    "Patient goal: recovery of function and return home / "
    "Family goal: early independence in activities of daily living"
)
_RP_POLICY_FALLBACK_JA = (
    "リハビリテーション治療方針：疾患特異的リハビリテーションを継続し、"
    "日常生活動作の自立度向上を図る"
)
_RP_POLICY_FALLBACK_EN = (
    "Rehabilitation policy: continue disease-specific rehabilitation therapy "
    "to improve independence in activities of daily living"
)
_RP_EXPLANATION_FALLBACK_JA = "本人・家族への説明：説明予定"
_RP_EXPLANATION_FALLBACK_EN = "Explanation to patient/family: pending"

_RP_THERAPY_TYPE_JA = {"PT": "理学療法(PT)", "OT": "作業療法(OT)", "ST": "言語聴覚療法(ST)"}
_RP_THERAPY_TYPE_EN = {
    "PT": "Physical therapy (PT)", "OT": "Occupational therapy (OT)", "ST": "Speech therapy (ST)",
}
_RP_PROGRESS_JA = {"improved": "改善", "stable": "維持", "unable_to_assess": "評価不能"}
_RP_PROGRESS_EN = {
    "improved": "improved", "stable": "stable", "unable_to_assess": "unable to assess",
}
_RP_PARTICIPATION_JA = {"good": "良好", "fair": "やや不良", "refused": "拒否"}
_RP_PARTICIPATION_EN = {"good": "good", "fair": "fair", "refused": "refused"}
_RP_PHASE_JA = {
    "early": "早期(ベッド上運動・座位保持練習)",
    "mid": "中期(歩行器歩行・移乗動作練習)",
    "late": "後期(独立歩行・ADL練習)",
}
_RP_PHASE_EN = {
    "early": "Early phase (bed exercises, sitting practice)",
    "mid": "Mid phase (walker ambulation, transfer training)",
    "late": "Late phase (independent ambulation, ADL practice)",
}

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
            # chain 2: ADMISSION_CARE_PLAN sections (LOINC 18776-5)
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
            # chain 2: NUTRITION_CARE_PLAN sections (LOINC 80791-7)
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
            # chain 2: REHABILITATION_PLAN sections (LOINC 34823-5)
            "patient_and_diagnosis": self._build_rp_patient_and_diagnosis,
            "rehab_team": self._build_rp_rehab_team,
            "functional_status": self._build_rp_functional_status,
            "basic_movement": self._build_rp_basic_movement,
            "session_frequency": self._build_rp_session_frequency,
            "goals": self._build_rp_goals,
            "policy": self._build_rp_policy,
            "discharge_estimate": self._build_rp_discharge_estimate,
            "explanation_consent": self._build_rp_explanation_consent,
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
        """Build allergies section from ctx.allergies.

        Resolves display via code_lookup (AD-30 — CIF stores allergen_code
        only, not display text; this mirrors _build_discharge_diagnoses'
        code_lookup pattern in this same file).
        """
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        allergies = ctx.allergies or []
        if not allergies:
            return _NKDA_JA if is_ja else _NKDA_EN, facts

        facts.append("ctx.allergies")
        parts = []
        for allergy in allergies:
            allergen_code = _o(allergy, "allergen_code", "") or ""
            display = code_lookup("snomed-ct", allergen_code, lang) if allergen_code else ""
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
    # chain 2: ADMISSION_CARE_PLAN section builders (入院診療計画書, LOINC 18776-5)
    #
    # MHLW form 別紙２ (10 core fields, verified 2026-07-03 — design spec §2).
    # JP-only doc type (countries_supported=[jp]); both language branches are
    # implemented for consistency with every other builder in this file, even
    # though only target_lang="ja" is ever reached through the registry gate.
    # ─────────────────────────────────────────────────────────────────

    def _build_acp_ward_and_room(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病棟（病室）— Encounter.ward_id + bed_number."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        ward = str(_o(ctx.encounter, "ward_id", "") or "")
        bed = str(_o(ctx.encounter, "bed_number", "") or "")
        if not ward and not bed:
            return (_ACP_WARD_ROOM_FALLBACK_JA if is_ja else _ACP_WARD_ROOM_FALLBACK_EN), facts
        if ward:
            facts.append("encounter.ward_id")
        if bed:
            facts.append("encounter.bed_number")
        if is_ja:
            return f"病棟：{ward or '未定'}　病室：{bed or '未定'}", facts
        return f"Ward: {ward or 'TBD'}, Room: {bed or 'TBD'}", facts

    def _build_acp_other_staff(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """主治医以外の担当者名 — Encounter.primary_nurse_id (same field AD-64 CareTeam uses)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        nurse_id = str(_o(ctx.encounter, "primary_nurse_id", "") or "")
        if not nurse_id:
            return (_ACP_OTHER_STAFF_FALLBACK_JA if is_ja else _ACP_OTHER_STAFF_FALLBACK_EN), facts
        facts.append("encounter.primary_nurse_id")
        return (f"担当看護師：{nurse_id}" if is_ja else f"Assigned nurse: {nurse_id}"), facts

    def _build_acp_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """病名（他に考え得る病名）— ctx.diagnoses, admission code preferred
        (discharge dx is not yet known when this document is written at
        admission — unlike _build_discharge_diagnoses which prefers discharge)."""
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
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
                or ("icd-10" if is_ja else "icd-10-cm")
            )
            display = code_lookup(system, code, ctx.target_lang)
            if display and display != code:
                parts.append(f"{display}（{code}）" if is_ja else f"{display} ({code})")
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
        is_ja = ctx.target_lang == "ja"
        names: set[str] = set()
        for lab in ctx.lab_results or []:
            name = _o(lab, "test_name", None)
            if name:
                names.add(str(name))
        if not names:
            fallback = _ACP_TEST_SCHEDULE_FALLBACK_JA if is_ja else _ACP_TEST_SCHEDULE_FALLBACK_EN
            return fallback, facts
        facts.append("ctx.lab_results")
        joined = "、".join(sorted(names)) if is_ja else ", ".join(sorted(names))
        return (f"検査項目：{joined} を実施予定" if is_ja else f"Planned tests: {joined}"), facts

    def _build_acp_surgery_schedule(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """手術内容及び日程 — ctx.procedures filtered to category_code=387713003 (surgical)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        surgical = [
            p for p in (ctx.procedures or [])
            if str(_o(p, "category_code", "") or "") == "387713003"
        ]
        if not surgical:
            return (_ACP_SURGERY_NONE_JA if is_ja else _ACP_SURGERY_NONE_EN), facts
        facts.append("ctx.procedures")
        types = [
            str(_o(p, "procedure_type", "") or "") for p in surgical if _o(p, "procedure_type", "")
        ]
        joined = "、".join(types) if is_ja else ", ".join(types)
        return (f"手術予定：{joined}" if is_ja else f"Planned surgery: {joined}"), facts

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
            country_key = "japan" if ctx.locale == "jp" else "us"
            target_los = _o(proto, "target_los", {}) or {}
            los_cfg = (target_los.get(country_key) or {}).get(ctx.severity) or {}
            if "mean" in los_cfg:
                los = los_cfg["mean"]
                facts.append("disease_protocol.target_los")
        if not los:
            los = ctx.los_days or 1
            facts.append("ctx.los_days")
        return round(los), facts

    def _build_acp_estimated_los(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """推定される入院期間 — see _estimated_los_days for the shared calculation."""
        is_ja = ctx.target_lang == "ja"
        los_days, facts = self._estimated_los_days(ctx)
        if is_ja:
            return f"推定入院期間：約{los_days}日間", facts
        return f"Estimated length of stay: approximately {los_days} days", facts

    def _build_acp_special_nutrition_management(
        self, ctx: NarrativeContext
    ) -> tuple[str, list[str]]:
        """特別な栄養管理の必要性 — MVP: always「無」(no NutritionOrder subsystem
        exists yet; TODO.md tracks the future nutrition subsystem chain)."""
        is_ja = ctx.target_lang == "ja"
        return (_ACP_NUTRITION_NO_JA if is_ja else _ACP_NUTRITION_NO_EN), []

    def _build_acp_other_plans(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """その他（看護計画・リハビリテーション等の計画）— fixed cross-reference
        phrase. NarrativeContext does not carry other stub types' rendered
        content at this call site (each spec walked independently), so this
        section cannot dynamically pull admission_nursing_assessment content
        without a larger architecture change (out of scope, see plan)."""
        is_ja = ctx.target_lang == "ja"
        return (_ACP_OTHER_PLANS_JA if is_ja else _ACP_OTHER_PLANS_EN), []

    # ─────────────────────────────────────────────────────────────────
    # chain 2: NUTRITION_CARE_PLAN section builders (栄養管理計画書, LOINC 80791-7)
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
        is_ja = ctx.target_lang == "ja"
        ward = str(_o(ctx.encounter, "ward_id", "") or "")
        physician = str(_o(ctx.encounter, "attending_physician_id", "") or "")
        if ward:
            facts.append("encounter.ward_id")
        if physician:
            facts.append("encounter.attending_physician_id")
        ward_disp = ward or ("未定" if is_ja else "TBD")
        physician_disp = physician or ("未定" if is_ja else "TBD")
        if is_ja:
            return f"病棟：{ward_disp}　担当医師：{physician_disp}", facts
        return f"Ward: {ward_disp}, Attending physician: {physician_disp}", facts

    def _build_ncp_dietitian(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """担当管理栄養士名 — MVP: no dietitian staff role exists yet."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_DIETITIAN_FALLBACK_JA if is_ja else _NCP_DIETITIAN_FALLBACK_EN), []

    def _build_ncp_nutrition_risk(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """入院時栄養状態に関するリスク — BMI 3-tier threshold (coarse screening
        proxy, not a validated instrument like GLIM/MUST — design spec §4)."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        bmi = _o(ctx.patient, "bmi", None)
        if bmi is None:
            fallback = (
                "栄養リスク：評価データなし" if is_ja else "Nutrition risk: no assessment data"
            )
            return fallback, facts
        facts.append("patient.bmi")
        bmi_r = round(float(bmi), 1)
        if bmi_r < 18.5:
            return (
                f"低栄養リスク：高（BMI {bmi_r}）" if is_ja
                else f"Malnutrition risk: high (BMI {bmi_r})"
            ), facts
        if bmi_r > 25:
            return (
                f"過栄養傾向（BMI {bmi_r}）" if is_ja
                else f"Overnutrition tendency (BMI {bmi_r})"
            ), facts
        return (
            f"低栄養リスク：低（BMI {bmi_r}、リスクなし）" if is_ja
            else f"Malnutrition risk: low (BMI {bmi_r}, no risk identified)"
        ), facts

    def _build_ncp_nutrition_assessment(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養状態の評価と課題 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_ASSESSMENT_FALLBACK_JA if is_ja else _NCP_ASSESSMENT_FALLBACK_EN), []

    def _build_ncp_nutrition_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養管理計画 目標 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_GOALS_FALLBACK_JA if is_ja else _NCP_GOALS_FALLBACK_EN), []

    def _build_ncp_nutrition_supply(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養補給に関する事項 (エネルギー/たんぱく質/補給方法) — standard
        initial-planning estimation formulas from PatientProfile.weight_kg
        (25-30 kcal/kg/day energy midpoint, 1.0-1.2 g/kg/day protein
        midpoint — design spec §3c). Route fixed to 経口 (oral) MVP default."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        weight = _o(ctx.patient, "weight_kg", None)
        if weight is None:
            fallback = (
                "栄養補給量：算出データなし" if is_ja
                else "Nutrition supply: no data to compute"
            )
            return fallback, facts
        facts.append("patient.weight_kg")
        energy = round(float(weight) * 27.5)
        protein = round(float(weight) * 1.1, 1)
        if is_ja:
            return (
                f"エネルギー：{energy}kcal／日　たんぱく質：{protein}g／日　"
                f"補給方法：経口"
            ), facts
        return (
            f"Energy: {energy} kcal/day, Protein: {protein} g/day, Route: oral"
        ), facts

    def _build_ncp_dysphagia_diet(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """嚥下調整食の必要性 — MVP fixed 「なし」."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_DYSPHAGIA_NONE_JA if is_ja else _NCP_DYSPHAGIA_NONE_EN), []

    def _build_ncp_dietary_content(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """食事内容 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (
            _NCP_DIETARY_CONTENT_FALLBACK_JA if is_ja else _NCP_DIETARY_CONTENT_FALLBACK_EN
        ), []

    def _build_ncp_nutrition_counseling(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養食事相談に関する事項 — MVP fixed fallback (collapses the 3 MHLW
        sub-items — admission/consult/discharge instruction — into one
        section; no per-item data source exists, design spec §2 row 7)."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_COUNSELING_FALLBACK_JA if is_ja else _NCP_COUNSELING_FALLBACK_EN), []

    def _build_ncp_other_issues(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """その他栄養管理上解決すべき課題 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_OTHER_ISSUES_FALLBACK_JA if is_ja else _NCP_OTHER_ISSUES_FALLBACK_EN), []

    def _build_ncp_reassessment_timing(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """栄養状態の再評価の時期 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (
            _NCP_REASSESSMENT_FALLBACK_JA if is_ja else _NCP_REASSESSMENT_FALLBACK_EN
        ), []

    def _build_ncp_discharge_evaluation(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """退院時及び終了時の総合的評価 — genuinely unknowable at plan-creation
        time; this system has no mechanism to revise a Stage-1 stub at a
        later encounter phase for this doc type (design spec §2 row 10)."""
        is_ja = ctx.target_lang == "ja"
        return (
            _NCP_DISCHARGE_EVAL_FALLBACK_JA if is_ja else _NCP_DISCHARGE_EVAL_FALLBACK_EN
        ), []

    # ─────────────────────────────────────────────────────────────────
    # chain 2: REHABILITATION_PLAN sections (LOINC 34823-5)
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
        is_ja = ctx.target_lang == "ja"
        therapy_types = sorted({
            str(_o(s, "therapy_type", "") or "") for s in (ctx.rehab_sessions or [])
            if _o(s, "therapy_type", "")
        })
        if not therapy_types:
            return (_RP_TEAM_FALLBACK_JA if is_ja else _RP_TEAM_FALLBACK_EN), facts
        facts.append("ctx.rehab_sessions")
        labels = _RP_THERAPY_TYPE_JA if is_ja else _RP_THERAPY_TYPE_EN
        joined = ("、" if is_ja else ", ").join(labels.get(t, t) for t in therapy_types)
        therapist_note = _RP_THERAPIST_FALLBACK_JA if is_ja else _RP_THERAPIST_FALLBACK_EN
        if is_ja:
            return f"担当リハビリ職種：{joined}／{therapist_note}", facts
        return f"Rehab discipline(s): {joined} / {therapist_note}", facts

    def _build_rp_functional_status(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """機能評価 — latest (by session_date) session's functional_progress /
        patient_participation / pain_score."""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (_RP_FUNCTIONAL_FALLBACK_JA if is_ja else _RP_FUNCTIONAL_FALLBACK_EN), facts
        latest = max(sessions, key=lambda s: _o(s, "session_date", datetime(1970, 1, 1)))
        facts.append("ctx.rehab_sessions")
        progress = str(_o(latest, "functional_progress", "") or "")
        participation = str(_o(latest, "patient_participation", "") or "")
        pain = _o(latest, "pain_score", None)
        progress_label = (_RP_PROGRESS_JA if is_ja else _RP_PROGRESS_EN).get(progress, progress)
        participation_label = (
            _RP_PARTICIPATION_JA if is_ja else _RP_PARTICIPATION_EN
        ).get(participation, participation)
        pain_text = f"{pain}/10" if pain is not None else ("評価なし" if is_ja else "not assessed")
        if is_ja:
            return (
                f"機能的改善度：{progress_label}／リハビリへの参加度：{participation_label}／"
                f"疼痛スコア：{pain_text}"
            ), facts
        return (
            f"Functional progress: {progress_label} / Participation: {participation_label} / "
            f"Pain score: {pain_text}"
        ), facts

    def _build_rp_basic_movement(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """基本動作 — day_post_op から phase (early/mid/late) を再導出。
        generate_rehab_sessions (modules/procedure/engine.py) が内部で使う閾値
        (<=3 early, <=14 mid, else late) と同一 — RehabSession に phase フィールド
        はないため再計算する。AD-30: RehabSession.activities の生英語文は使わない
        (design spec §4)。"""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (_RP_MOVEMENT_FALLBACK_JA if is_ja else _RP_MOVEMENT_FALLBACK_EN), facts
        latest = max(sessions, key=lambda s: _o(s, "session_date", datetime(1970, 1, 1)))
        facts.append("ctx.rehab_sessions")
        day_post_op = _o(latest, "day_post_op", 0) or 0
        if day_post_op <= 3:
            phase = "early"
        elif day_post_op <= 14:
            phase = "mid"
        else:
            phase = "late"
        return (_RP_PHASE_JA if is_ja else _RP_PHASE_EN)[phase], facts

    def _build_rp_session_frequency(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """実施回数・期間・1回あたりの時間。"""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        sessions = ctx.rehab_sessions or []
        if not sessions:
            return (_RP_FREQUENCY_FALLBACK_JA if is_ja else _RP_FREQUENCY_FALLBACK_EN), facts
        facts.append("ctx.rehab_sessions")
        dates = [_o(s, "session_date", datetime(1970, 1, 1)) for s in sessions]
        first_date, last_date = min(dates), max(dates)
        duration = _o(sessions[0], "duration_minutes", 0) or 0
        count = len(sessions)
        if is_ja:
            return (
                f"実施回数：{count}回（{first_date.date().isoformat()}〜"
                f"{last_date.date().isoformat()}）、1回あたり{duration}分"
            ), facts
        return (
            f"Sessions: {count} ({first_date.date().isoformat()} to "
            f"{last_date.date().isoformat()}), {duration} min each"
        ), facts

    def _build_rp_goals(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """本人の希望・家族の希望 — CIF に患者意向を表すフィールドなし
        (design spec §3d)、固定フォールバック。"""
        is_ja = ctx.target_lang == "ja"
        return (_RP_GOALS_FALLBACK_JA if is_ja else _RP_GOALS_FALLBACK_EN), []

    def _build_rp_policy(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハビリテーション治療方針 — 固定フォールバック(design spec §3d)。"""
        is_ja = ctx.target_lang == "ja"
        return (_RP_POLICY_FALLBACK_JA if is_ja else _RP_POLICY_FALLBACK_EN), []

    def _build_rp_discharge_estimate(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """リハビリテーション終了の目安・時期 — _estimated_los_days を再利用
        (admission_care_plan の estimated_los と同じ target_los データ、
        リハ完了フレーミングの文言のみ異なる)。"""
        is_ja = ctx.target_lang == "ja"
        los_days, facts = self._estimated_los_days(ctx)
        if is_ja:
            return f"リハビリテーション終了の目安：入院後約{los_days}日", facts
        return (
            f"Estimated rehabilitation completion: approximately {los_days} days post-admission"
        ), facts

    def _build_rp_explanation_consent(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """本人・家族への説明(署名欄) — 固定フォールバック
        (admission_care_plan/nutrition_care_plan と同じ signature-block pattern)。"""
        is_ja = ctx.target_lang == "ja"
        return (_RP_EXPLANATION_FALLBACK_JA if is_ja else _RP_EXPLANATION_FALLBACK_EN), []

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
