"""ADMISSION_CARE_PLAN (LOINC 18776-5) + NUTRITION_CARE_PLAN
(LOINC 80791-7) + REHABILITATION_PLAN (LOINC 34823-5) section builders.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1e of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Shared helpers accessed via ``generator``:
  - ``generator._build_chief_complaint`` (acp_symptoms, acp_diagnosis fallback)
  - ``generator._build_assessment_and_plan`` (acp_treatment_plan)
  - ``generator._estimated_los_days`` (acp_estimated_los, rp_discharge_estimate)
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import _localize_proc_type
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE,
    NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE,
    NUTRITION_ENERGY_KCAL_PER_KG_MIDPOINT,
    NUTRITION_PROTEIN_G_PER_KG_MIDPOINT,
)
from clinosim.modules.document.narrative._template_helpers import _label, _resolve_staff_name, allergen_display
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


# ─────────────────────────────────────────────────────────────────────
# ADMISSION_CARE_PLAN (LOINC 18776-5) section builders.
# ─────────────────────────────────────────────────────────────────────


def build_acp_ward_and_room(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_acp_other_staff(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """Healthcare staff names other than attending physician — mapped to
    Encounter.primary_nurse_id (shares field with CareTeam)."""
    facts: list[str] = []
    lang = ctx.target_lang
    nurse_id = str(_o(ctx.encounter, "primary_nurse_id", "") or "")
    if not nurse_id:
        return (t("fallback.acp_other_staff_fallback", lang)), facts
    facts.append("encounter.primary_nurse_id")
    nurse_disp = _resolve_staff_name(nurse_id, ctx.roster_map)
    return t("acp.assigned_nurse_line", lang, name=nurse_disp), facts


def build_acp_diagnosis(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """病名（他に考え得る病名）— ctx.diagnoses, admission code preferred
    (discharge dx is not yet known when this document is written at
    admission — unlike _build_discharge_diagnoses which prefers discharge)."""
    facts: list[str] = []
    lang = ctx.target_lang
    diagnoses = ctx.diagnoses or []
    if not diagnoses:
        return generator._build_chief_complaint(ctx)

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
    return generator._build_chief_complaint(ctx)


def build_acp_symptoms(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """症状 — reuses chief_complaint extraction (presenting symptom)."""
    return generator._build_chief_complaint(ctx)


def build_acp_treatment_plan(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """治療計画 — reuses assessment_and_plan extraction (admission_hp precedent)."""
    return generator._build_assessment_and_plan(ctx)


def build_acp_test_schedule(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_acp_surgery_schedule(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_acp_estimated_los(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """推定される入院期間 — see _estimated_los_days for the shared calculation."""
    lang = ctx.target_lang
    los_days, facts = generator._estimated_los_days(ctx)
    return t("acp.estimated_los_line", lang, days=los_days), facts


def build_acp_special_nutrition_management(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """特別な栄養管理の必要性 — MVP: always「無」(no NutritionOrder subsystem
    exists yet; TODO.md tracks the future nutrition subsystem chain)."""
    lang = ctx.target_lang
    return (t("fallback.acp_nutrition_no", lang)), []


def build_acp_other_plans(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """その他（看護計画・リハビリテーション等の計画）— fixed cross-reference
    phrase. NarrativeContext does not carry other stub types' rendered
    content at this call site (each spec walked independently), so this
    section cannot dynamically pull admission_nursing_assessment content
    without a larger architecture change (out of scope, see plan)."""
    lang = ctx.target_lang
    return (t("fallback.acp_other_plans", lang)), []


# ─────────────────────────────────────────────────────────────────────
# NUTRITION_CARE_PLAN (LOINC 80791-7, 栄養管理計画書) section builders.
#
# MHLW form 別紙23 (verified 2026-07-03 — design spec §2). JP-only,
# LOS>7-gated. Only 3 of 12 sections are data-driven (ward_and_physician /
# nutrition_risk / nutrition_supply); the rest are MVP fixed fallbacks —
# no dietitian role or real nutrition-assessment data source exists yet
# (TODO.md tracks this). Both language branches implemented for
# consistency with every other builder in this file, though this doc
# type is JP-only in production.
# ─────────────────────────────────────────────────────────────────────


def build_ncp_ward_and_physician(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
    physician_disp = _resolve_staff_name(physician, ctx.roster_map) if physician else t("common.tbd", lang)
    return t("ncp.ward_and_physician_line", lang, ward=ward_disp, physician=physician_disp), facts


def build_ncp_dietitian(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """担当管理栄養士名 — MVP: no dietitian staff role exists yet."""
    lang = ctx.target_lang
    return (t("fallback.ncp_dietitian_fallback", lang)), []


def build_ncp_nutrition_risk(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_ncp_nutrition_assessment(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
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


def build_ncp_nutrition_goals(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """栄養管理計画 目標 — MVP fixed fallback."""
    lang = ctx.target_lang
    return (t("fallback.ncp_goals_fallback", lang)), []


def build_ncp_nutrition_supply(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_ncp_dysphagia_diet(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """嚥下調整食の必要性 — MVP fixed 「なし」."""
    lang = ctx.target_lang
    return (t("fallback.ncp_dysphagia_none", lang)), []


def build_ncp_dietary_content(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """食事内容 — MVP fixed fallback."""
    lang = ctx.target_lang
    return (t("fallback.ncp_dietary_content_fallback", lang)), []


def build_ncp_nutrition_counseling(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """栄養食事相談に関する事項 — MVP fixed fallback (collapses the 3 MHLW
    sub-items — admission/consult/discharge instruction — into one
    section; no per-item data source exists, design spec §2 row 7)."""
    lang = ctx.target_lang
    return (t("fallback.ncp_counseling_fallback", lang)), []


def build_ncp_other_issues(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """その他栄養管理上解決すべき課題 — v9 density fix: derive from
    allergies + high-risk chronic combo. Falls back to placeholder
    when CIF has no relevant markers."""
    facts: list[str] = []
    lang = ctx.target_lang
    parts: list[str] = []
    # Food allergies (subset)
    for a in (ctx.allergies or [])[:3]:
        substance = allergen_display(a, lang)
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


def build_ncp_reassessment_timing(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """栄養状態の再評価の時期 — MVP fixed fallback."""
    lang = ctx.target_lang
    return (t("fallback.ncp_reassessment_fallback", lang)), []


def build_ncp_discharge_evaluation(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """退院時及び終了時の総合的評価 — genuinely unknowable at plan-creation
    time; this system has no mechanism to revise a Stage-1 stub at a
    later encounter phase for this doc type (design spec §2 row 10)."""
    lang = ctx.target_lang
    return (t("fallback.ncp_discharge_eval_fallback", lang)), []


# ─────────────────────────────────────────────────────────────────────
# REHABILITATION_PLAN (LOINC 34823-5) section builders.
# ─────────────────────────────────────────────────────────────────────


def build_rp_patient_and_diagnosis(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """患者・原因疾患 — reuses admission_care_plan's diagnosis extraction
    (same ctx.diagnoses source, design spec §3e)."""
    return build_acp_diagnosis(generator, ctx)


def build_rp_rehab_team(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
    joined = t("list_sep.serial", lang).join(_label("rp_therapy_type", tt, lang, fallback=tt) for tt in therapy_types)
    therapist_note = t("fallback.rp_therapist_fallback", lang)
    return t("rp_note.rehab_team_line", lang, disciplines=joined, therapist_note=therapist_note), facts


def build_rp_functional_status(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_rp_basic_movement(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_rp_session_frequency(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_rp_goals(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """本人の希望・家族の希望 — CIF に患者意向を表すフィールドなし
    (design spec §3d)、固定フォールバック。"""
    return t("fallback.rp_goals_fallback", ctx.target_lang), []


def build_rp_policy(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """リハビリテーション治療方針 — 固定フォールバック(design spec §3d)。"""
    return t("fallback.rp_policy_fallback", ctx.target_lang), []


def build_rp_discharge_estimate(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """リハビリテーション終了の目安・時期 — _estimated_los_days を再利用
    (admission_care_plan の estimated_los と同じ target_los データ、
    リハ完了フレーミングの文言のみ異なる)。"""
    lang = ctx.target_lang
    los_days, facts = generator._estimated_los_days(ctx)
    return t("rp_note.discharge_estimate_line", lang, days=los_days), facts


def build_rp_explanation_consent(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """本人・家族への説明(署名欄) — 固定フォールバック
    (admission_care_plan/nutrition_care_plan と同じ signature-block pattern)。"""
    lang = ctx.target_lang
    return (t("fallback.rp_explanation_fallback", lang)), []
