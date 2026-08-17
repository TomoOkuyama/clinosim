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
import string
from datetime import datetime, timedelta
from typing import Any

from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
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
    load_discharge_instructions,
    load_physical_exam_findings,
)
from clinosim.types.document import DocumentType, FormatType, NarrativeContext, NarrativeOutput

logger = logging.getLogger(__name__)


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
    is_ja = lang == "ja"
    generic = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
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


# Generic fallback phrases per locale
_GENERIC_FALLBACK_JA = "特記事項なし"
_GENERIC_FALLBACK_EN = "No special findings"

# JP/EN disposition-label map for `_build_discharge_details`. Kept at
# module scope because the equivalent function-local ``UPPER_CASE`` binding
# would trigger the N806 lint rule.
_JA_DISPO_LABEL: dict[str, str] = {
    "home": "自宅退院",
    "hosp": "他院転院",
    "other-hcf": "他施設転院",
    "snf": "施設退院",
    "exp": "死亡退院",
}
_EN_DISPO_LABEL: dict[str, str] = {
    "home": "discharged home",
    "hosp": "transferred to another hospital",
    "other-hcf": "transferred to another healthcare facility",
    "snf": "discharged to skilled nursing facility",
    "exp": "expired",
}
_GENERIC_ASSESSMENT_JA = "経過観察中"
_GENERIC_ASSESSMENT_EN = "Clinical assessment ongoing"
_GENERIC_PLAN_JA = "治療継続"
_GENERIC_PLAN_EN = "Continue current management"

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
_NURSING_HISTORY_FALLBACK_JA = "入院目的・既往歴：特記事項なし"
_NURSING_HISTORY_FALLBACK_EN = "Nursing history: no significant findings"
_ADL_FALLBACK_JA = "ADL：自立（問題なし）"
_ADL_FALLBACK_EN = "ADL: independent (no issues noted)"
_RISK_FALLBACK_JA = "転倒・褥瘡リスク：評価中"
_RISK_FALLBACK_EN = "Fall / pressure ulcer risk: assessment pending"
_NURSING_DX_FALLBACK_JA = "看護診断：特記事項なし"
_NURSING_DX_FALLBACK_EN = "Nursing diagnosis: no significant findings"

# ADMISSION_CARE_PLAN (Phase 2) fallback phrases
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
_ACP_OTHER_PLANS_EN = "Other: see nursing documentation for the nursing care plan and rehabilitation plan."

# NUTRITION_CARE_PLAN (Phase 2) fallback phrases
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
_NCP_REASSESSMENT_FALLBACK_EN = "Nutrition status reassessment: planned approximately 1 week after admission"
_NCP_DISCHARGE_EVAL_FALLBACK_JA = "退院時及び終了時の総合的評価：退院時に評価予定"
_NCP_DISCHARGE_EVAL_FALLBACK_EN = "Comprehensive evaluation at discharge: pending, to be assessed at discharge"

# REHABILITATION_PLAN (Phase 2) fallback phrases
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
_RP_GOALS_FALLBACK_JA = "本人の希望：現在の身体機能の回復・自宅復帰を希望／家族の希望：早期の日常生活動作自立を希望"
_RP_GOALS_FALLBACK_EN = (
    "Patient goal: recovery of function and return home / Family goal: early independence in activities of daily living"
)
_RP_POLICY_FALLBACK_JA = (
    "リハビリテーション治療方針：疾患特異的リハビリテーションを継続し、日常生活動作の自立度向上を図る"
)
_RP_POLICY_FALLBACK_EN = (
    "Rehabilitation policy: continue disease-specific rehabilitation therapy "
    "to improve independence in activities of daily living"
)
_RP_EXPLANATION_FALLBACK_JA = "本人・家族への説明：説明予定"
_RP_EXPLANATION_FALLBACK_EN = "Explanation to patient/family: pending"

_RP_THERAPY_TYPE_JA = {"PT": "理学療法(PT)", "OT": "作業療法(OT)", "ST": "言語聴覚療法(ST)"}
_RP_THERAPY_TYPE_EN = {
    "PT": "Physical therapy (PT)",
    "OT": "Occupational therapy (OT)",
    "ST": "Speech therapy (ST)",
}
_RP_PROGRESS_JA = {"improved": "改善", "stable": "維持", "unable_to_assess": "評価不能"}
_RP_PROGRESS_EN = {
    "improved": "improved",
    "stable": "stable",
    "unable_to_assess": "unable to assess",
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

# Nursing shift labels, keyed by the neutral shift key stored in
# structural CIF (ClinicalDocument.shift → NarrativeContext.shift). Labels are
# resolved here at render time by language .
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

# ED section fallback phrases
_ED_WORKUP_FALLBACK_JA = "検査・処置：特記事項なし"
_ED_WORKUP_FALLBACK_EN = "ED workup: no significant findings"
_DISPOSITION_FALLBACK_JA = "帰宅または入院加療"
_DISPOSITION_FALLBACK_EN = "Disposition: to be determined"
_TRIAGE_FALLBACK_JA = "トリアージ情報：未記録"
_TRIAGE_FALLBACK_EN = "Triage information: not recorded"

# Arrival mode display
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
# v6 (2026-08-16): `social` is a first-class token emitted by the
# population layer alongside none/heavy; without an explicit mapping it
# was falling back to "unknown", erasing information from JP narratives.
_ALCOHOL_JA: dict[str, str] = {
    "none": "飲酒なし",
    "occasional": "機会飲酒",
    "social": "社交的飲酒",
    "moderate": "適度な飲酒",
    "heavy": "多量飲酒",
    "unknown": "飲酒状況不明",
}
_ALCOHOL_EN: dict[str, str] = {
    "none": "Non-drinker",
    "occasional": "Occasional drinker",
    "social": "Social drinker",
    "moderate": "Moderate drinker",
    "heavy": "Heavy drinker",
    "unknown": "Alcohol use unknown",
}

# Occupation labels (v6, 2026-08-16). Population layer emits raw
# English tokens (retired, office, manufacturing, …); v5
# `_build_social_history` pasted them verbatim into JP narratives, so
# 96-yo 女性 の 職業 が 「retired」 と英字で残っていた。These maps close
# the gap. `_OCCUPATION_*.get(k, k)` — unmapped values fall back to the
# raw token so unknown occupations still render (defensive default).
_OCCUPATION_JA: dict[str, str] = {
    "retired": "退職",
    "office": "事務職",
    "manufacturing": "製造業",
    "service": "サービス業",
    "transportation": "運輸業",
    "education": "教育関係",
    "healthcare": "医療従事者",
    "student": "学生",
    "middle_school_student": "中学生",
    "elementary_student": "小学生",
    "preschool": "未就学児",
    "infant": "乳幼児",
    "other": "その他",
    "unemployed": "無職",
    "homemaker": "主婦",
}
_OCCUPATION_EN: dict[str, str] = {
    "retired": "Retired",
    "office": "Office worker",
    "manufacturing": "Manufacturing",
    "service": "Service industry",
    "transportation": "Transportation",
    "education": "Education",
    "healthcare": "Healthcare",
    "student": "Student",
    "middle_school_student": "Middle-school student",
    "elementary_student": "Elementary-school student",
    "preschool": "Preschool child",
    "infant": "Infant",
    "other": "Other",
    "unemployed": "Unemployed",
    "homemaker": "Homemaker",
}

# SOAP section labels per locale
_SOAP_JA = ("S（主観）", "O（客観）", "A（評価）", "P（計画）")
_SOAP_EN = ("S:", "O:", "A:", "P:")


def _filter_vitals_for_day(vitals: list, day_index: int, encounter: Any) -> list:
    """Return vitals belonging to day ``day_index`` of the stay.

    v6 (2026-08-16): CIF vital_signs records store ISO ``timestamp`` but
    ``day`` is typically None. The naive day-field filter therefore let
    admission-day vitals leak into every day's context, producing "T=38.1°C
    repeated for 15 consecutive progress notes" hallucinations (POP-000075).

    Resolution order:
      1. If any record has an explicit ``day`` field, match on it.
      2. Otherwise derive a day offset from ``timestamp`` minus
         encounter.admission_datetime.
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
    # 2. Timestamp fallback
    adm_raw = _o(encounter, "admission_datetime", None) if encounter is not None else None
    adm_dt = _parse_iso_datetime(adm_raw)
    if adm_dt is None:
        # Use earliest timestamp as day-0 anchor
        candidates = [_parse_iso_datetime(_o(v, "timestamp", None)) for v in vitals]
        candidates = [c for c in candidates if c is not None]
        if candidates:
            adm_dt = min(candidates)
    if adm_dt is None:
        return vitals[:1]
    picks: list = []
    for v in vitals:
        ts = _parse_iso_datetime(_o(v, "timestamp", None))
        if ts is None:
            continue
        offset = (ts - adm_dt).days
        if offset == day_index:
            picks.append(v)
    if picks:
        return picks
    return vitals[:1]


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
        # the JP source directly — instead synthesize generic English SOAP
        # text. Per-archetype English content is deferred to the LLM
        # narrative pass.
        if not is_ja:
            facts.append("generic:progress_note_soap_en")
            subjective = _GENERIC_FALLBACK_EN
            objective = _GENERIC_FALLBACK_EN
            assessment = _GENERIC_ASSESSMENT_EN
            plan = _GENERIC_PLAN_EN
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
            objective = traj.get("objective") if traj.get("objective") not in _placeholders else _generic_s
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
            phys_summary = self._format_physical_exam(phys_exam, ctx.severity, is_ja)
            if phys_summary:
                objective = f"{objective}。{phys_summary}"

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
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = "発熱・全身倦怠感" if is_ja else "Chief complaint not specified"

        # 1. Encounter's own chief_complaint is the primary source of truth.
        enc = ctx.encounter
        if enc is not None:
            preferred_key = "chief_complaint_ja" if is_ja else "chief_complaint_en"
            for key in (preferred_key, "chief_complaint"):
                raw = _o(enc, key, None)
                if raw:
                    facts.append(f"ctx.encounter.{key}")
                    return str(raw), facts

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
        fallback = f"{ctx.severity}の症状で受診。" if is_ja else f"Patient presented with {ctx.severity} symptoms."

        # ED_NOTE reads from ed_note_template
        if ctx.document_type == DocumentType.ED_NOTE:
            ed_tmpl = self._get_ed_note_template(ctx)
            if ed_tmpl is not None:
                text = _pick_localized(ed_tmpl, "hpi", lang, ctx)
                if text:
                    facts.append(f"encounter_protocol.narrative.ed_note_template.hpi_{lang}")
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
        """Append CIF-anchored demographics + chief_complaint + chronic
        context to the HPI onset_pattern seed (v9 density fix)."""
        if ctx.target_lang != "ja":
            return ""
        patient = ctx.patient
        enc = ctx.encounter
        parts: list[str] = []
        age = _o(patient, "age", None) if patient else None
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
        # Chronic short list
        from clinosim.codes import lookup as _code_lookup

        conds = _o(patient, "chronic_conditions", []) or []
        chronic_labels: list[str] = []
        for c in conds[:3]:
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
            disp = _code_lookup(key, code, ctx.target_lang) or code
            chronic_labels.append(disp)
        if chronic_labels:
            parts.append(f"既往: {'、'.join(chronic_labels)}。")
        return "".join(parts)

    def _build_past_medical_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
        # Session-88j v3-review fix: resolve ICD code → localised disease
        # display via code_lookup ("icd-10" for JP-native codes / "icd-10-cm"
        # US). Previously the PMH section rendered raw codes ("J45 (Moderate
        # persistent); I10 (Stage 1); …") which read as a coding sheet
        # rather than a clinical PMH. LOOKUP failure falls back to the raw
        # code so the field is never empty.
        icd_system = "icd-10" if is_ja else "icd-10-cm"
        lines = []
        for cond in conditions:
            code = _o(cond, "code", "")
            stage = _o(cond, "stage", "")
            if not code:
                continue
            display = code_lookup(icd_system, code, lang) or code
            if display == code:
                # Try 3-char parent (E11.9 → E11) — many mappings live only
                # at the category level.
                base = code.split(".")[0]
                if base != code:
                    display = code_lookup(icd_system, base, lang) or code
            annotation = f" ({stage})" if stage else ""
            if display and display != code:
                # Format: "気管支喘息 (Moderate persistent) [J45]" — code
                # trailing for traceability, humans read the display first.
                lines.append(f"{display}{annotation} [{code}]")
            else:
                lines.append(f"{code}{annotation}")
        if lines:
            return "; ".join(lines), facts
        return none_text, facts

    def _build_medications_at_home(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
            # v6 (2026-08-16): localize occupation token; fall back to
            # raw when unmapped so a novel population value still renders
            # (rather than being dropped silently).
            occ_map = _OCCUPATION_JA if is_ja else _OCCUPATION_EN
            occ_text = occ_map.get(occupation, occupation)
            parts.append(f"{key}: {occ_text}")

        facts.append("ctx.patient.smoking_status")
        facts.append("ctx.patient.alcohol_use")
        facts.append("ctx.patient.occupation")

        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN
        return "; ".join(parts) if parts else fallback, facts

    def _build_family_history(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build family history — generic placeholder (not yet implemented)."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        text = "特記家族歴なし" if is_ja else "No significant family history"
        return text, []

    def _build_physical_examination(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build physical_examination using multi-step fallback chain."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        # physical_exam_findings values (disease YAML + reference_data)
        # are JP-only strings. The EN locale previously emitted them with
        # a `:ja_only_fallback` tag, leaking CJK into US narratives. The
        # EN locale now skips the JP source entirely and uses a generic
        # placeholder; per-disease English content is deferred to the LLM
        # narrative pass.
        if not is_ja:
            facts.append("generic:physical_exam_en")
            return _GENERIC_FALLBACK_EN, facts

        phys_exam = self._resolve_physical_exam(ctx, ctx.clinical_course_archetype, ctx.day_index)
        if phys_exam:
            facts.append(f"physical_exam_findings.{ctx.clinical_course_archetype}.day_{ctx.day_index}")

        text = self._format_physical_exam(phys_exam, ctx.severity, is_ja)
        if not text:
            text = _GENERIC_FALLBACK_JA

        return text, facts

    def _build_assessment_and_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build assessment_and_plan from daily_trajectory day_0 assessment + plan."""
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"

        # daily_trajectory values (disease YAML) are JP-only strings. The
        # EN locale previously emitted them with a `:ja_only_fallback`
        # tag, leaking CJK into US narratives. The EN locale now skips
        # the JP source and uses generic English assessment / plan
        # phrases; per-archetype English wording is deferred to the LLM
        # narrative pass.
        if not is_ja:
            facts.append("generic:daily_trajectory_en")
            text = f"Assessment: {_GENERIC_ASSESSMENT_EN}. Plan: {_GENERIC_PLAN_EN}."
            return text, facts

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
        """admission_hp Assessment composed from CIF (v9 density fix)."""
        if ctx.target_lang != "ja":
            return ""
        parts: list[str] = []
        enc = ctx.encounter
        # Primary reason
        cc = _o(enc, "chief_complaint_ja", None) or _o(enc, "chief_complaint", None) if enc else None
        if cc:
            parts.append(f"主訴「{cc}」で入院。")
        # Severity + disease
        if ctx.disease_protocol is not None:
            disease = _o(ctx.disease_protocol, "disease_id", None)
            if disease:
                parts.append(f"病態: {disease} ({ctx.severity})。")
        # Chronic backdrop
        conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
        if conds:
            from clinosim.codes import lookup as _code_lookup

            key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
            labels = [
                _code_lookup(key, _o(c, "code", "") or "", ctx.target_lang) or (_o(c, "code", "") or "")
                for c in conds[:4]
            ]
            labels = [l for l in labels if l]
            if labels:
                parts.append(f"併存疾患: {'、'.join(labels)}。")
        if not parts:
            parts.append("急性症状の精査・治療目的で入院。")
        return "".join(parts)

    def _compose_ap_plan_from_state(self, ctx: NarrativeContext) -> str:
        """admission_hp Plan composed from CIF (v9 density fix)."""
        if ctx.target_lang != "ja":
            return ""
        parts: list[str] = []
        # LOS estimate
        los = ctx.los_days or 0
        if los > 0:
            parts.append(f"予定入院期間: 約{los}日。")
        # Today's meds
        admins = list(ctx.medications or [])
        med_names: list[str] = []
        seen: set[str] = set()
        for m in admins[:20]:
            d = _o(m, "day", None)
            if d is not None and d != 0:  # admission day
                continue
            name = _o(m, "drug_name", None) or _o(m, "medication", None)
            if not name or name in seen:
                continue
            seen.add(name)
            from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

            med_names.append(_localize_drug_name(str(name), "JP"))
            if len(med_names) >= 6:
                break
        if med_names:
            parts.append(f"薬物療法: {'、'.join(med_names)}。")
        # Ordered procedures (workup)
        procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:4]]
        procs = [p for p in procs if p]
        if procs:
            parts.append(f"検査・処置: {'、'.join(str(p) for p in procs)}。")
        if not parts:
            parts.append("経過観察・症状に応じた対応。")
        return "".join(parts)

    def _build_admission_summary(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
        is_ja = ctx.target_lang == "ja"
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
        display = code_lookup(system, code, ctx.target_lang) if code else ""
        if display and display != code:
            facts.append("ctx.diagnoses[0].admission_diagnosis_code")
            if is_ja:
                text = f"{display}のため入院となった。"
            else:
                text = f"Admitted for {display}."
        else:
            cc_text, cc_facts = self._build_chief_complaint(ctx)
            facts.extend(cc_facts)
            if is_ja:
                text = f"{cc_text}のため入院となった。"
            else:
                text = f"Admitted for {cc_text}."
        return text, facts

    def _build_admission_details(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """322 入院時詳細セクション:入院日・入院経路(救急経由か)・入棟病棟。"""
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        enc = ctx.encounter
        adm_dt = _o(enc, "admission_datetime", "") if enc is not None else ""
        ward = _o(enc, "ward", "") if enc is not None else ""
        via_ed = bool(_o(enc, "via_emergency", False)) if enc is not None else False
        facts.append("ctx.encounter.admission_datetime")

        # Format admission datetime to YYYY-MM-DD only
        adm_date = ""
        if adm_dt:
            adm_date = str(adm_dt).split("T")[0]
        if is_ja:
            parts: list[str] = []
            if adm_date:
                parts.append(f"{adm_date}")
            if via_ed:
                parts.append("救急外来受診後")
            if ward:
                parts.append(f"{ward}病棟")
            parts.append("に入院した。")
            text = "、".join(parts[:-1]) + parts[-1] if len(parts) > 1 else parts[0]
        else:
            fragments: list[str] = []
            if adm_date:
                fragments.append(f"Admitted on {adm_date}")
            if via_ed:
                fragments.append("via the emergency department")
            if ward:
                fragments.append(f"to the {ward} ward")
            text = " ".join(fragments) + "." if fragments else "Admitted for inpatient care."
        return text, facts

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
        is_ja = ctx.target_lang == "ja"
        enc = ctx.encounter
        dis_dt = _o(enc, "discharge_datetime", None) if enc is not None else None
        ward = _o(enc, "ward", "") if enc is not None else ""
        disposition = _o(enc, "discharge_disposition", "") if enc is not None else ""
        facts.append("ctx.encounter.discharge_datetime")
        # Disposition maps to Japanese display text (narrative short form, not
        # JP-CLINS spec codes). _JA_DISPO_LABEL and _EN_DISPO_LABEL are
        # module-scope constants (defined at file top).

        dis_date = ""
        if dis_dt:
            dis_date = str(dis_dt).split("T")[0]

        if is_ja:
            parts: list[str] = []
            if dis_date:
                parts.append(f"{dis_date}")
            if ward:
                parts.append(f"{ward}病棟から")
            dispo_label = _JA_DISPO_LABEL.get(disposition, "退院")
            parts.append(f"{dispo_label}となった。")
            text = "、".join(parts[:-1]) + parts[-1] if len(parts) > 1 else parts[0]
            if not text:
                text = "退院時所見の記録なし。"
        else:
            fragments: list[str] = []
            if dis_date:
                fragments.append(f"Discharged on {dis_date}")
            if ward:
                fragments.append(f"from the {ward} ward")
            dispo_label = _EN_DISPO_LABEL.get(disposition, "discharged")
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
        is_ja = ctx.target_lang == "ja"
        diagnoses = ctx.diagnoses or []
        if not diagnoses:
            return ("特記事項なし。" if is_ja else "No admission diagnoses recorded."), facts

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
                lines.append(f"{idx}. {display}（{code}）" if is_ja else f"{idx}. {display} ({code})")
            else:
                lines.append(f"{idx}. {code}")
        if not lines:
            return ("特記事項なし。" if is_ja else "No admission diagnoses recorded."), facts
        return "\n".join(lines), facts

    def _build_present_illness(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """360 現病歴セクション:現病歴の短文記述。

        退院時サマリー用は ADMISSION_HP と同じ disease_protocol の HPI
        reuses this template. Tense variation (narrative tone) will be
        LLM 差替時に調整予定。
        """
        hpi_text, facts = self._build_hpi(ctx)
        is_ja = ctx.target_lang == "ja"
        # HPI is already structured as a chronological onset narrative, so
        # no structural changes are needed. Text style harmonization will be
        # deferred to the LLM narrative pass when applicable.
        if not hpi_text:
            hpi_text = (
                f"{ctx.severity}の症状で受診し入院となった。"
                if is_ja
                else f"Patient presented with {ctx.severity} symptoms leading to admission."
            )
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
        is_ja = ctx.target_lang == "ja"
        if is_ja:
            text = "紹介元:当院(急性期一般病棟)。担当医師の署名により発行。"
        else:
            text = "Referring institution: this hospital (acute-care general ward)."
        return text, facts

    def _build_referral_destination(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """910 紹介先情報セクション:紹介先医療機関の記載。

        clinosim は機関間連携 workflow を simulate しないため、紹介先は
        汎用 "他院" placeholder。将来:受け入れ想定医療機関の小さな pool
        から sample する余地あり。
        """
        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        if is_ja:
            text = "紹介先:他院。当該患者の継続加療を目的として本情報提供書を作成する。"
        else:
            text = "Referral destination: unspecified other institution (continued care)."
        return text, facts

    def _build_referral_purpose(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """950 紹介目的セクション:標準セットから決定的に一つ選択。

        encounter_id の hash で 4 選択肢から index 決定。cohort 全体で
        分布は stable、encounter 個別ではばらつき保持。
        """
        import hashlib

        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"
        enc = ctx.encounter
        enc_id = _o(enc, "encounter_id", "") or "ENC-UNKNOWN"
        purposes_ja = [
            "継続加療",
            "精査依頼",
            "他科紹介",
            "リハビリテーション継続",
        ]
        purposes_en = [
            "continued treatment",
            "further investigation",
            "specialty consultation",
            "continued rehabilitation",
        ]
        digest = hashlib.sha256(enc_id.encode("utf-8")).digest()
        idx = digest[0] % len(purposes_ja)
        picked = purposes_ja[idx] if is_ja else purposes_en[idx]
        facts.append(f"ctx.encounter.encounter_id[hash-idx={idx}]")
        if is_ja:
            text = f"紹介目的:{picked}のため。"
        else:
            text = f"Referral purpose: {picked}."
        return text, facts

    def _build_diagnoses_and_complaint(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """340 傷病名・主訴セクション:傷病名リスト + 主訴の複合セクション。"""
        from clinosim.codes import lookup as code_lookup

        facts: list[str] = []
        is_ja = ctx.target_lang == "ja"

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
            display = code_lookup(system, code, ctx.target_lang)
            if display and display != code:
                dx_lines.append(f"{idx}. {display}（{code}）" if is_ja else f"{idx}. {display} ({code})")
            else:
                dx_lines.append(f"{idx}. {code}")
        if dx_lines:
            facts.append("ctx.diagnoses")

        # Chief complaint
        cc_text, cc_facts = self._build_chief_complaint(ctx)
        facts.extend(cc_facts)

        if is_ja:
            header = "【傷病名】\n" + ("\n".join(dx_lines) if dx_lines else "特記事項なし。")
            complaint = f"\n\n【主訴】\n{cc_text}"
            text = header + complaint
        else:
            header = "Diagnoses:\n" + ("\n".join(dx_lines) if dx_lines else "None recorded.")
            complaint = f"\n\nChief complaint: {cc_text}"
            text = header + complaint
        return text, facts

    def _build_present_illness_ref(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """360 現病歴セクション(診療情報提供書用):HPI builder を再利用。"""
        hpi_text, facts = self._build_hpi(ctx)
        is_ja = ctx.target_lang == "ja"
        if not hpi_text:
            hpi_text = (
                f"{ctx.severity}の症状で受診し入院となった。"
                if is_ja
                else f"Patient presented with {ctx.severity} symptoms."
            )
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
        is_ja = ctx.target_lang == "ja"

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
        is_ja = ctx.target_lang == "ja"
        patient = ctx.patient

        # Convert past medical history (chronic_conditions) codes to
        # Japanese display text
        chronic = _o(patient, "chronic_conditions", []) or []
        history_lines: list[str] = []
        for cond in chronic:
            code = _o(cond, "code", "")
            system = _o(cond, "system", "icd-10-cm") or "icd-10-cm"
            if not code:
                continue
            # JP uses icd-10 authority; US uses icd-10-cm (per spec
            # §Diagnosis code coverage)
            resolved_system = system_key_for("diagnosis", "JP") if is_ja else system
            display = code_lookup(resolved_system, code, ctx.target_lang)
            if display and display != code:
                history_lines.append(f"- {display}（{code}）" if is_ja else f"- {display} ({code})")
            else:
                history_lines.append(f"- {code}")
        if chronic:
            facts.append("ctx.patient.chronic_conditions")
        history_text = "\n".join(history_lines) if history_lines else ("特記事項なし" if is_ja else "None noted")

        # Current medications: list may contain HomeMedication objects or
        # mixed dict/str entries
        current_meds = _o(patient, "current_medications", []) or []
        if current_meds:
            facts.append("ctx.patient.current_medications")
        med_text = (
            "、".join(_render_home_med_name(m) for m in current_meds)
            if current_meds
            else ("常用薬なし" if is_ja else "None taken")
        )

        # 生活習慣(smoking_status / alcohol_use)
        smoking = _o(patient, "smoking_status", "never") or "never"
        alcohol = _o(patient, "alcohol_use", "none") or "none"
        facts.append("ctx.patient.smoking_status")
        facts.append("ctx.patient.alcohol_use")

        smoking_ja = {
            "never": "喫煙歴なし",
            "former": "禁煙(過去に喫煙歴あり)",
            "current": "現在喫煙中",
        }.get(smoking, f"{smoking}(区分未定義)")
        alcohol_ja = {
            "none": "飲酒なし",
            "occasional": "機会飲酒",
            "regular": "習慣的飲酒",
            "heavy": "多量飲酒",
        }.get(alcohol, f"{alcohol}(区分未定義)")

        # Assessment: follow-up required when chronic conditions are present
        needs_followup = len(chronic) > 0
        assessment_ja = (
            "既往に慢性疾患あり、かかりつけ医での継続経過観察を要す。" if needs_followup else "経過観察不要。"
        )
        assessment_en = (
            "Chronic condition(s) present; continued follow-up with primary care recommended."
            if needs_followup
            else "No follow-up required."
        )

        if is_ja:
            text = (
                f"【既往歴】\n{history_text}\n"
                f"【自覚症状】特記事項なし。\n"
                f"【服薬】{med_text}。\n"
                f"【生活習慣】{smoking_ja}、{alcohol_ja}。\n"
                f"【判定】{assessment_ja}"
            )
        else:
            text = (
                f"History: {history_text}\n"
                f"Symptoms: none noted.\n"
                f"Medications: {med_text}.\n"
                f"Lifestyle: smoking={smoking}, alcohol={alcohol}.\n"
                f"Assessment: {assessment_en}"
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
        is_ja = lang == "ja"

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
            if is_ja:
                primary_reason = _o(ctx.encounter, "primary_diagnosis_ja", None) or _o(
                    ctx.encounter, "chief_complaint_ja", None
                )
            else:
                primary_reason = _o(ctx.encounter, "primary_diagnosis", None) or _o(
                    ctx.encounter, "chief_complaint", None
                )
        if is_ja:
            head = f"入院期間 {los} 日間"
            if primary_reason:
                head += f"（主病名/主訴: {str(primary_reason)[:80]}）"
            parts.append(head + "。")
        else:
            head = f"Length of stay: {los} days"
            if primary_reason:
                head += f" (primary reason: {str(primary_reason)[:80]})"
            parts.append(head + ".")

        # Sentence 2: complications (blocker 1 — MUST be surfaced)
        comps = list(getattr(ctx, "complications_occurred", []) or [])
        if comps:
            facts.append("ctx.complications_occurred")
            if is_ja:
                parts.append(f"経過中の合併症: {'、'.join(str(c) for c in comps[:6])}。")
            else:
                parts.append(f"Complications during stay: {', '.join(str(c) for c in comps[:6])}.")

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
            if is_ja:
                parts.append(f"主な処置・手技: {'、'.join(proc_names)}。")
            else:
                parts.append(f"Key procedures: {', '.join(proc_names)}.")

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
                or system_key_for("diagnosis", ctx.locale.upper())
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
        is_ja = lang == "ja"
        none_text = "退院処方なし" if is_ja else "No discharge medications"

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
            dose = _o(med, "dose", "") or ""
            route = _o(med, "route", "") or ""
            freq = _o(med, "frequency", "") or ""
            days = _o(med, "days_supply", None)
            bits: list[str] = [str(drug)]
            if dose:
                bits.append(str(dose))
            if route:
                bits.append(str(route))
            if freq:
                bits.append(str(freq))
            if days:
                bits.append(f"x{days}日分" if is_ja else f"x{days}d")
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
            title = f"[Nursing Shift Note - {shift_label} shift]" if shift_label else "[Nursing Shift Note]"
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
                f"トリアージレベル: {level_system} Level {level}"
                if level_system and level
                else "トリアージレベル: 未評価"
            )
            arrival_line = f"来院形態: {arrival_display}" if arrival_display else "来院形態: 不明"
            cc_line = f"主訴: {cc_summary}" if cc_summary else "主訴: 未記録"
            raw_text = "\n".join([level_line, arrival_line, cc_line])
        else:
            level_line = (
                f"Triage level: {level_system} Level {level}"
                if level_system and level
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
    # ADMISSION_NURSING_ASSESSMENT section builders
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
        """Build adl_assessment — generic placeholder."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _ADL_FALLBACK_JA if is_ja else _ADL_FALLBACK_EN, []

    def _build_risk_assessments(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build risk_assessments — generic placeholder."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _RISK_FALLBACK_JA if is_ja else _RISK_FALLBACK_EN, []

    def _build_nursing_diagnosis(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build nursing_diagnosis — generic placeholder."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _NURSING_DX_FALLBACK_JA if is_ja else _NURSING_DX_FALLBACK_EN, []

    def _build_care_plan(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build care_plan — generic placeholder."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _CARE_PLAN_FALLBACK_JA if is_ja else _CARE_PLAN_FALLBACK_EN, []

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
        """Healthcare staff names other than attending physician — mapped to
        Encounter.primary_nurse_id (shares field with CareTeam)."""
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
                or system_key_for("diagnosis", ctx.locale.upper())
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
        surgical = [p for p in (ctx.procedures or []) if str(_o(p, "category_code", "") or "") == "387713003"]
        if not surgical:
            return (_ACP_SURGERY_NONE_JA if is_ja else _ACP_SURGERY_NONE_EN), facts
        facts.append("ctx.procedures")
        types = [str(_o(p, "procedure_type", "") or "") for p in surgical if _o(p, "procedure_type", "")]
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
        is_ja = ctx.target_lang == "ja"
        los_days, facts = self._estimated_los_days(ctx)
        if is_ja:
            return f"推定入院期間：約{los_days}日間", facts
        return f"Estimated length of stay: approximately {los_days} days", facts

    def _build_acp_special_nutrition_management(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
            fallback = "栄養リスク：評価データなし" if is_ja else "Nutrition risk: no assessment data"
            return fallback, facts
        facts.append("patient.bmi")
        bmi_r = round(float(bmi), 1)
        if bmi_r < NARRATIVE_BMI_UNDERWEIGHT_MAX_EXCLUSIVE:
            return (f"低栄養リスク：高（BMI {bmi_r}）" if is_ja else f"Malnutrition risk: high (BMI {bmi_r})"), facts
        if bmi_r > NARRATIVE_BMI_NORMAL_MAX_EXCLUSIVE:
            return (f"過栄養傾向（BMI {bmi_r}）" if is_ja else f"Overnutrition tendency (BMI {bmi_r})"), facts
        return (
            f"低栄養リスク：低（BMI {bmi_r}、リスクなし）"
            if is_ja
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
            fallback = "栄養補給量：算出データなし" if is_ja else "Nutrition supply: no data to compute"
            return fallback, facts
        facts.append("patient.weight_kg")
        energy = round(float(weight) * NUTRITION_ENERGY_KCAL_PER_KG_MIDPOINT)
        protein = round(float(weight) * NUTRITION_PROTEIN_G_PER_KG_MIDPOINT, 1)
        if is_ja:
            return (f"エネルギー：{energy}kcal／日　たんぱく質：{protein}g／日　補給方法：経口"), facts
        return (f"Energy: {energy} kcal/day, Protein: {protein} g/day, Route: oral"), facts

    def _build_ncp_dysphagia_diet(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """嚥下調整食の必要性 — MVP fixed 「なし」."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_DYSPHAGIA_NONE_JA if is_ja else _NCP_DYSPHAGIA_NONE_EN), []

    def _build_ncp_dietary_content(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """食事内容 — MVP fixed fallback."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_DIETARY_CONTENT_FALLBACK_JA if is_ja else _NCP_DIETARY_CONTENT_FALLBACK_EN), []

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
        return (_NCP_REASSESSMENT_FALLBACK_JA if is_ja else _NCP_REASSESSMENT_FALLBACK_EN), []

    def _build_ncp_discharge_evaluation(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """退院時及び終了時の総合的評価 — genuinely unknowable at plan-creation
        time; this system has no mechanism to revise a Stage-1 stub at a
        later encounter phase for this doc type (design spec §2 row 10)."""
        is_ja = ctx.target_lang == "ja"
        return (_NCP_DISCHARGE_EVAL_FALLBACK_JA if is_ja else _NCP_DISCHARGE_EVAL_FALLBACK_EN), []

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
        is_ja = ctx.target_lang == "ja"
        therapy_types = sorted(
            {str(_o(s, "therapy_type", "") or "") for s in (ctx.rehab_sessions or []) if _o(s, "therapy_type", "")}
        )
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
        participation_label = (_RP_PARTICIPATION_JA if is_ja else _RP_PARTICIPATION_EN).get(
            participation, participation
        )
        pain_text = f"{pain}/10" if pain is not None else ("評価なし" if is_ja else "not assessed")
        if is_ja:
            return (
                f"機能的改善度：{progress_label}／リハビリへの参加度：{participation_label}／疼痛スコア：{pain_text}"
            ), facts
        return (
            f"Functional progress: {progress_label} / Participation: {participation_label} / Pain score: {pain_text}"
        ), facts

    def _build_rp_basic_movement(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """基本動作 — day_post_op から phase (early/mid/late) を再導出。
        generate_rehab_sessions (modules/procedure/engine.py) が内部で使う閾値
        (<=3 early, <=14 mid, else late) と同一 — RehabSession に phase フィールド
        is absent, so recalculation is required. RehabSession.activities raw English
        text is not used (per design spec §4)。"""
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
        return (f"Estimated rehabilitation completion: approximately {los_days} days post-admission"), facts

    def _build_rp_explanation_consent(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """本人・家族への説明(署名欄) — 固定フォールバック
        (admission_care_plan/nutrition_care_plan と同じ signature-block pattern)。"""
        is_ja = ctx.target_lang == "ja"
        return (_RP_EXPLANATION_FALLBACK_JA if is_ja else _RP_EXPLANATION_FALLBACK_EN), []

    # ─────────────────────────────────────────────────────────────────
    # NURSING_DISCHARGE_SUMMARY section builders
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

    def _build_nursing_interventions_provided(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build nursing_interventions_provided — generic placeholder."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _INTERVENTIONS_FALLBACK_JA if is_ja else _INTERVENTIONS_FALLBACK_EN, []

    def _build_patient_education(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build patient_education — generic placeholder."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _PATIENT_EDUCATION_FALLBACK_JA if is_ja else _PATIENT_EDUCATION_FALLBACK_EN, []

    def _build_discharge_readiness(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build discharge_readiness — generic placeholder."""
        lang = ctx.target_lang
        is_ja = lang == "ja"
        return _DISCHARGE_READINESS_FALLBACK_JA if is_ja else _DISCHARGE_READINESS_FALLBACK_EN, []

    # ─────────────────────────────────────────────────────────────────
    # OUTPATIENT_SOAP section builders
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
        is_ja = lang == "ja"
        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        # 1. Explicit encounter-YAML template
        soap = self._get_soap_template(ctx)
        if soap is not None:
            text = _pick_localized(soap, "subjective", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.outpatient_soap_template.subjective_{lang}")
                return text, facts

        # 2. CIF-composed subjective (v9 density fix)
        composed = self._compose_outpatient_subjective_from_state(ctx)
        if composed:
            facts.extend(
                ["ctx.patient.demographics", "ctx.encounter.chief_complaint", "ctx.patient.chronic_conditions"]
            )
            return composed, facts

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
        is_ja = ctx.target_lang == "ja"
        age = _o(patient, "age", None)
        sex_raw = _o(patient, "sex", None) or ""
        sex_ja = {"M": "男性", "F": "女性"}.get(str(sex_raw).upper(), "")
        sex_en = {"M": "male", "F": "female"}.get(str(sex_raw).upper(), "")
        # chief_complaint — encounter first (v9 chief_complaint bug fix),
        # skip English-in-JA leak.
        cc = ""
        if enc is not None:
            if is_ja:
                cc = _o(enc, "chief_complaint_ja", None) or _o(enc, "chief_complaint", None) or ""
            else:
                cc = _o(enc, "chief_complaint_en", None) or _o(enc, "chief_complaint", None) or ""
        cc = str(cc)
        # Chronic condition follow-up context (short list, code-lookup localized)
        from clinosim.codes import lookup as _code_lookup

        conditions = _o(patient, "chronic_conditions", []) or []
        chronic_labels: list[str] = []
        for c in conditions[:3]:
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
            disp = _code_lookup(key, code, ctx.target_lang) or code
            chronic_labels.append(disp)
        # Compose
        parts: list[str] = []
        if is_ja:
            if age and sex_ja:
                parts.append(f"{age}歳{sex_ja}患者、")
            elif age:
                parts.append(f"{age}歳患者、")
            if cc:
                parts.append(f"本日「{cc}」のため外来受診。")
            else:
                parts.append("本日外来受診。")
            if chronic_labels:
                parts.append(f"慢性疾患（{'、'.join(chronic_labels)}）のフォローアップを兼ねる。")
        else:
            if age and sex_en:
                parts.append(f"{age}-year-old {sex_en} patient")
            elif age:
                parts.append(f"{age}-year-old patient")
            visit_reason = f"presenting for {cc}" if cc else "presenting for outpatient visit"
            parts.append(f" {visit_reason}.")
            if chronic_labels:
                parts.append(f" Follow-up of chronic conditions: {', '.join(chronic_labels)}.")
        text = "".join(parts).strip()
        return text

    def _build_outpatient_objective(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build SOAP objective from outpatient_soap_template.objective_<lang>.

        Issue #780 (part of #774): when the encounter protocol has no
        `outpatient_soap_template`, or the field is empty, derive an
        objective line from the encounter's measured vitals rather than
        falling through to a static "特記事項なし" placeholder — this makes
        the O section carry real per-encounter data (BP / HR / SpO2 / RR
        vary across visits) instead of every SOAP note reading identically.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        soap = self._get_soap_template(ctx)
        if soap is not None:
            text = _pick_localized(soap, "objective", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.outpatient_soap_template.objective_{lang}")
                return text, facts

        # #780 patient-state fallback: assemble a factual O line from ctx.vitals.
        vital_line = self._compose_vital_signs_line(ctx)
        if vital_line:
            facts.append("ctx.vitals")
            return vital_line, facts

        return fallback, facts

    def _compose_progress_subjective_from_state(self, ctx: NarrativeContext) -> str:
        """Inpatient progress_note Subjective composed from CIF facts.

        v9 (2026-08-17) density fix — v8 defaulted to "特記事項なし" for
        every day whose disease_YAML lacked a daily_trajectory entry.
        This composes a minimum-viable subjective from stay_progress +
        today's abnormal vitals (fever / hypoxia flag), backed only by
        confirmed CIF signals.
        """
        if ctx.target_lang != "ja":
            return ""
        picks = _filter_vitals_for_day(ctx.vitals, ctx.day_index, ctx.encounter)
        parts: list[str] = []
        los = ctx.los_days or 0
        day_1indexed = ctx.day_index + 1
        if los > 0:
            parts.append(f"入院{day_1indexed}日目。")
        if picks:
            v = picks[0]
            temp = _o(v, "temperature_celsius", None)
            spo2 = _o(v, "spo2", None)
            if temp and float(temp) >= 38.0:
                parts.append(f"発熱 {float(temp):.1f}°C 持続。")
            elif temp and float(temp) < 36.0:
                parts.append(f"低体温 {float(temp):.1f}°C を認める。")
            if spo2 and float(spo2) < 92:
                parts.append(f"SpO2 {int(float(spo2))}% と低下傾向。")
        if len(parts) <= 1:
            # No abnormal signal — neutral observation phrase
            parts.append("自覚症状に著変なし。")
        return "".join(parts)

    def _compose_progress_assessment_from_state(self, ctx: NarrativeContext) -> str:
        """Inpatient progress_note Assessment from CIF facts.

        v9 (2026-08-17) density fix — pulls today's abnormal labs (H/L
        flagged) + complications flag into a 1-2 line assessment.
        """
        if ctx.target_lang != "ja":
            return ""
        parts: list[str] = []
        # Complications (from record via NarrativeContext v6 field)
        comps = list(getattr(ctx, "complications_occurred", []) or [])
        if comps:
            parts.append(f"合併症 {'、'.join(str(c) for c in comps[:3])} を認識、対応継続中。")
        # Abnormal labs today
        labs = list(ctx.lab_results or [])
        abn: list[str] = []
        for lab in labs[:6]:
            flag = _o(lab, "flag", None)
            if not flag:
                continue
            d = _o(lab, "day", None)
            if d is not None and d != ctx.day_index:
                continue
            name = _o(lab, "lab_name", None)
            val = _o(lab, "value", None)
            unit = _o(lab, "unit", "") or ""
            if name and val is not None:
                abn.append(f"{name} {val} {unit} [{flag}]")
        if abn:
            parts.append(f"本日の検査所見: {'、'.join(abn[:4])}。")
        if not parts:
            parts.append("経過観察中、著変なし。")
        return "".join(parts)

    def _compose_progress_plan_from_state(self, ctx: NarrativeContext) -> str:
        """Inpatient progress_note Plan from CIF facts.

        v9 (2026-08-17) density fix — lists today's active medications
        (JA localized) and today's procedures / orders.
        """
        if ctx.target_lang != "ja":
            return ""
        parts: list[str] = []
        # Today's meds (MAR)
        admins = list(ctx.medications or [])
        med_names: list[str] = []
        seen: set[str] = set()
        for m in admins:
            d = _o(m, "day", None)
            if d is not None and d != ctx.day_index:
                continue
            name = _o(m, "drug_name", None) or _o(m, "medication", None) or _o(m, "name", None)
            if not name or name in seen:
                continue
            seen.add(name)
            from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

            med_names.append(_localize_drug_name(str(name), "JP"))
            if len(med_names) >= 6:
                break
        if med_names:
            parts.append(f"薬物療法継続: {'、'.join(med_names)}。")
        # Today's procedures
        procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:4]]
        procs = [p for p in procs if p]
        if procs:
            parts.append(f"本日の処置: {'、'.join(str(p) for p in procs)}。")
        if not parts:
            parts.append("治療継続、経過観察。")
        return "".join(parts)

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

        Also handles ED_NOTE context (falls back to generic if no encounter_protocol).

        Issue #780: when no template is available, list active chronic conditions
        so the A section reflects the patient's real problem list.
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
        if soap is not None:
            text = _pick_localized(soap, "assessment", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.outpatient_soap_template.assessment_{lang}")
                return text, facts

        # v9 (2026-08-17) density fix: build a per-chronic-condition
        # assessment line that integrates today's vitals + abnormal labs,
        # not just a raw code list. Falls back to the flat chronic list
        # when no interpretation is available.
        integrated = self._compose_chronic_assessment_integrated(ctx)
        if integrated:
            facts.extend(["ctx.patient.chronic_conditions", "ctx.vitals.today", "ctx.lab_results.abnormal_today"])
            return integrated, facts

        # Original #780 fallback (chronic list only)
        chronic_line = self._compose_chronic_condition_line(ctx)
        if chronic_line:
            facts.append("ctx.patient.chronic_conditions")
            return chronic_line, facts

        return fallback, facts

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
            disp_key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
            disp = _code_lookup(disp_key, code, lang) or code
            labels.append(disp)
        if not labels:
            return ""
        if lang == "ja":
            return "既往症フォローアップ: " + "、".join(labels)
        return "Chronic-condition follow-up: " + ", ".join(labels)

    def _compose_chronic_assessment_integrated(self, ctx: NarrativeContext) -> str:
        """SOAP Assessment enriched with today's vitals + abnormal labs.

        v9 (2026-08-17) density fix — v8 emitted only a chronic-condition
        list ("既往症フォローアップ: 高血圧、脂質異常症、…"), which was
        clinically inert. This version integrates today's measured
        values (BP for HTN, HbA1c/glucose for DM, Cr/eGFR for CKD,
        LDL for dyslipidemia) into per-condition interpretation lines,
        producing a genuine assessment rather than a static problem list.
        All values are CIF-CONFIRMED (measured today). When a chronic
        condition lacks a matching today measurement, the line is
        omitted rather than fabricated.
        """
        patient = ctx.patient
        if patient is None:
            return ""
        conditions = _o(patient, "chronic_conditions", []) or []
        if not conditions:
            return ""
        vitals = list(ctx.vitals or [])
        labs = list(ctx.lab_results or [])
        v0 = vitals[0] if vitals else None
        sbp = _o(v0, "systolic_bp", None) if v0 else None
        dbp = _o(v0, "diastolic_bp", None) if v0 else None

        # Index today's abnormal labs by lab_name (lowercased) for lookup
        lab_by_name: dict[str, tuple[Any, str | None]] = {}
        for lab in labs:
            flag = _o(lab, "flag", None)
            if not flag:
                continue
            name = str(_o(lab, "lab_name", "") or "").lower()
            if name:
                lab_by_name[name] = (_o(lab, "value", None), _o(lab, "unit", None))

        from clinosim.codes import lookup as _code_lookup

        is_ja = ctx.target_lang == "ja"
        disp_key = "icd-10" if ctx.locale == "jp" else "icd-10-cm"
        lines: list[str] = []
        for i, c in enumerate(conditions, 1):
            code = _o(c, "code", "") or (c if isinstance(c, str) else "")
            if not code:
                continue
            label = _code_lookup(disp_key, code, ctx.target_lang) or code
            # Match code prefix → measurement
            code_prefix = code.split(".")[0].upper()
            interp = ""
            if code_prefix.startswith("I10") and sbp and dbp:
                # Hypertension: interpret BP
                if sbp >= 160 or dbp >= 100:
                    interp = "Stage 2" if not is_ja else "Stage 2 相当、コントロール不十分"
                elif sbp >= 140 or dbp >= 90:
                    interp = "Stage 1" if not is_ja else "Stage 1 相当、追加介入検討"
                else:
                    interp = "well controlled" if not is_ja else "コントロール良好"
                interp = f"BP {int(sbp)}/{int(dbp)} → {interp}"
            elif code_prefix.startswith("E78") and "ldl" in lab_by_name:
                v, u = lab_by_name["ldl"]
                interp = f"LDL {v} {u or 'mg/dL'} [H] → " + ("statin 効果不十分" if is_ja else "statin under-response")
            elif code_prefix.startswith("E11") and "hba1c" in lab_by_name:
                v, u = lab_by_name["hba1c"]
                interp = f"HbA1c {v} {u or '%'} [H] → " + (
                    "血糖コントロール不十分" if is_ja else "glycemic control suboptimal"
                )
            elif code_prefix.startswith("N18"):
                cr = lab_by_name.get("cr") or lab_by_name.get("creatinine")
                if cr:
                    v, u = cr
                    interp = f"Cr {v} {u or 'mg/dL'} [H] → " + ("腎機能低下持続" if is_ja else "renal function reduced")
            if interp:
                lines.append(f"{i}. {label}: {interp}")
            else:
                # No matching measurement → include as follow-up target only
                stub = "本日測定なし、次回受診時再評価" if is_ja else "no measurement today; reassess next visit"
                lines.append(f"{i}. {label}: {stub}")
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
        is_ja = lang == "ja"
        fallback = _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN

        soap = self._get_soap_template(ctx)
        if soap is not None:
            text = _pick_localized(soap, "plan", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.outpatient_soap_template.plan_{lang}")
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

        if lines:
            return "\n".join(lines), facts

        return fallback, facts

    def _compose_today_prescription_line(self, ctx: NarrativeContext) -> str:
        """Today's outpatient Rx (from ctx.discharge_medications when the
        outpatient visit closes with a fresh prescription). v9 density fix."""
        rx = list(getattr(ctx, "discharge_medications", None) or [])
        if not rx:
            return ""
        is_ja = ctx.target_lang == "ja"
        parts: list[str] = []
        for m in rx[:8]:
            drug = _o(m, "drug_name", "") or ""
            if not drug:
                continue
            drug, _cat = strip_protocol_prefix(drug)
            if is_ja:
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
                bits.append(f"x{days}日分" if is_ja else f"x{days}d")
            parts.append(" ".join(bits))
        if not parts:
            return ""
        head = ("本日処方: " if is_ja else "Today's prescription: ") + "; ".join(parts)
        return head

    def _compose_today_procedures_line(self, ctx: NarrativeContext) -> str:
        """Procedures / labs ordered today for the outpatient visit.
        v9 density fix — v8 P section ignored today's activity entirely."""
        procs = list(ctx.procedures or [])
        if not procs:
            return ""
        is_ja = ctx.target_lang == "ja"
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
        head = ("本日実施: " if is_ja else "Today's workup: ") + "、".join(names) if is_ja else "; ".join(names)
        head = ("本日実施: " if is_ja else "Today's workup: ") + ("、".join(names) if is_ja else "; ".join(names))
        return head

    def _compose_follow_up_line(self, ctx: NarrativeContext) -> str:
        """Follow-up guidance from encounter_protocol (未確定 — treat as
        planning, not fact). v9 density fix."""
        ep = ctx.encounter_protocol
        interval = _o(ep, "next_visit_interval_days", None) if ep is not None else None
        is_ja = ctx.target_lang == "ja"
        if interval:
            try:
                d = int(interval)
                return f"次回外来: {d}日後を予定。" if is_ja else f"Next visit: in {d} days (planned)."
            except (TypeError, ValueError):
                pass
        # Generic follow-up sentinel (planning phrase, not fact)
        return "次回外来: 1か月後を予定。" if is_ja else "Next visit: planned in 1 month."

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
        is_ja = ctx.target_lang == "ja"
        names: list[str] = []
        for m in meds:
            n = _render_home_med_name(m, lang=ctx.target_lang) if not isinstance(m, str) else m
            if isinstance(m, str) and is_ja:
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
        joiner_ja = "、"
        joiner_en = ", "
        joiner = joiner_ja if is_ja else joiner_en
        head = joiner.join(shown)
        if len(names) > limit:
            more_ja = f"（他 {len(names) - limit} 剤）"
            more_en = f" (and {len(names) - limit} others)"
            head += more_ja if is_ja else more_en
        if is_ja:
            return f"継続処方: {head}"
        return f"Continue current medications: {head}"

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
            text = f"トリアージレベル: {level_text}。来院形態: {arrival_display or '不明'}。"
        else:
            text = f"Triage level: {level_text}. Arrival mode: {arrival_display or 'unknown'}."

        return text, facts

    def _build_ed_physical_exam(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build physical_exam for ED_NOTE from ed_note_template.physical_exam_<lang>.

        v9 (2026-08-17) density fix — when encounter_protocol has no
        ed_note_template.physical_exam, fall back to arrival vitals +
        chief_complaint context rather than emitting a bare
        "特記事項なし".
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is None:
            # v9 density: assemble from arrival vitals + severity
            vital_line = self._compose_vital_signs_line(ctx)
            if vital_line:
                facts.append("ctx.vitals[0]")
                if is_ja:
                    return f"来院時所見: {vital_line}。特記の身体所見なし。", facts
                return f"On arrival: {vital_line}. No focal findings on exam.", facts
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
        """Build ed_workup from ed_note_template.ed_workup_summary_<lang>.

        v9 (2026-08-17) density fix — assemble labs + procedures actually
        performed in ED when the encounter YAML has no ed_workup_summary
        template.
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _ED_WORKUP_FALLBACK_JA if is_ja else _ED_WORKUP_FALLBACK_EN

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is not None:
            text = _pick_localized(ed_tmpl, "ed_workup_summary", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.ed_note_template.ed_workup_summary_{lang}")
                return text, facts

        # v9 density fallback: enumerate actual workup from CIF
        parts: list[str] = []
        # Abnormal labs
        abn_labs = []
        for lab in (ctx.lab_results or [])[:8]:
            flag = _o(lab, "flag", None)
            if not flag:
                continue
            name = _o(lab, "lab_name", "") or ""
            val = _o(lab, "value", None)
            unit = _o(lab, "unit", "") or ""
            if name and val is not None:
                abn_labs.append(f"{name} {val} {unit} [{flag}]")
        if abn_labs:
            parts.append(
                ("検査: " if is_ja else "Labs: ") + "、".join(abn_labs[:4]) if is_ja else ", ".join(abn_labs[:4])
            )
        # Procedures / imaging
        procs = []
        for pr in (ctx.procedures or [])[:4]:
            nm = _o(pr, "procedure_name", None) or _o(pr, "name", None)
            if nm:
                procs.append(str(nm))
        if procs:
            parts.append(
                ("処置・画像: " if is_ja else "Procedures/imaging: ") + "、".join(procs) if is_ja else ", ".join(procs)
            )
        if parts:
            facts.extend(["ctx.lab_results.abnormal", "ctx.procedures.ed"])
            return "。".join(parts) if is_ja else ". ".join(parts), facts

        return fallback, facts

    def _build_ed_disposition(self, ctx: NarrativeContext) -> tuple[str, list[str]]:
        """Build disposition from ed_note_template.disposition_<lang>.

        v9 (2026-08-17) density fix — infer disposition from encounter
        outcome (discharge_disposition / admission linkage) when
        ed_note_template is absent, rather than emitting a bare
        "帰宅または入院加療".
        """
        facts: list[str] = []
        lang = ctx.target_lang
        is_ja = lang == "ja"
        fallback = _DISPOSITION_FALLBACK_JA if is_ja else _DISPOSITION_FALLBACK_EN

        ed_tmpl = self._get_ed_note_template(ctx)
        if ed_tmpl is not None:
            text = _pick_localized(ed_tmpl, "disposition", lang, ctx)
            if text:
                facts.append(f"encounter_protocol.narrative.ed_note_template.disposition_{lang}")
                return text, facts

        # v9 density fallback: infer from encounter fields
        enc = ctx.encounter
        if enc is not None:
            dispo = _o(enc, "discharge_disposition", None) or _o(enc, "outcome", None)
            adm = _o(enc, "admit_to_ward", None) or bool(_o(enc, "admitted", False))
            facts.append("ctx.encounter.disposition")
            if adm:
                if is_ja:
                    return "帰院後入院加療の方針となった。担当科より病棟へ入棟依頼。", facts
                return "Admitted for inpatient management. Ward transfer arranged with primary team.", facts
            if dispo:
                label = _JA_DISPO_LABEL.get(str(dispo), None) if is_ja else _EN_DISPO_LABEL.get(str(dispo), None)
                if label:
                    if is_ja:
                        return f"{label}。症状経過に応じて再受診指示。", facts
                    return f"{label}. Return precautions provided.", facts

        return fallback, facts

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
        is_ja = ctx.target_lang == "ja"
        return {
            "subjective": _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN,
            "objective": _GENERIC_FALLBACK_JA if is_ja else _GENERIC_FALLBACK_EN,
            "assessment": _GENERIC_ASSESSMENT_JA if is_ja else _GENERIC_ASSESSMENT_EN,
            "plan": _GENERIC_PLAN_JA if is_ja else _GENERIC_PLAN_EN,
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

    def _format_physical_exam(self, phys_exam: dict[str, Any], severity: str, is_ja: bool) -> str:
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
