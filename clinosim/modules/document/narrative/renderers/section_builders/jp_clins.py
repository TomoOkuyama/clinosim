"""JP-CLINS section builders — eDischargeSummary (入院理由/入院時詳細/
退院時詳細/入院時診断/現病歴), eReferral (紹介元/紹介先/紹介目的/
傷病名・主訴/現病歴), eCheckup (事業者健診検査結果/問診結果).

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1g of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.

Generator-threaded helpers used:
  - ``section_builder("chief_complaint")`` (admission_reason, diagnoses_and_complaint)
  - ``section_builder("hpi")`` (present_illness, present_illness_ref)
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.countries import country_code, has_authored_narrative
from clinosim.locale.i18n import t
from clinosim.locale.loader import narrative_label as _label
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
    NARRATIVE_HBA1C_BORDERLINE_THRESHOLD,
    NARRATIVE_HBA1C_DIABETES_THRESHOLD,
    NARRATIVE_LDL_BORDERLINE_THRESHOLD,
    NARRATIVE_LDL_ELEVATED_THRESHOLD,
    NARRATIVE_LDL_HIGH_THRESHOLD,
    bmi_band,
    bp_band,
)
from clinosim.modules.document.narrative._template_helpers import (
    _render_home_med_name,
)
from clinosim.modules.document.narrative.renderers._shared_helpers import chronic_condition_coded
from clinosim.modules.document.narrative.renderers.section_builders._registry import section, section_builder
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


# ─────────────────────────────────────────────────────────────────────
# JP-CLINS eDischargeSummary (退院時サマリー) section builders.
# ─────────────────────────────────────────────────────────────────────


@section("admission_reason")
def build_admission_reason(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """312 入院理由セクション:入院理由の一言記述。

    Resolve primary admission diagnosis display via clinosim.codes.lookup.
    Falls back to chief complaint if code cannot be resolved.
    """
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
        cc_text, cc_facts = section_builder("chief_complaint")(generator, ctx)
        facts.extend(cc_facts)
        subject = cc_text
    text = t("admission_reason.admitted_for", lang, subject=subject)
    return text, facts


@section("admission_details")
def build_admission_details(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


@section("discharge_details")
def build_discharge_details(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """324 退院時詳細セクション:退院日・退院病棟・退院時転帰(JP-only)。

    One of the 5 discharge-side mandatory sections in the eDS spec.
    An earlier state emitted only the slice code, leaving the
    narrative content unset — that violated `text.div SHALL have
    non-whitespace content` (FHIR R4 `txt-2`) on 130+ resources per
    fullset. This template mirrors `build_admission_details`
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

    if has_authored_narrative(lang):
        parts: list[str] = []
        if dis_date:
            parts.append(dis_date)
        if ward:
            parts.append(t("discharge_details.ward_slot", lang, ward=ward))
        parts.append(t("narrative_text.discharge_details.disposition_sentence", lang, disposition=dispo_label))
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


@section("admission_diagnoses")
def build_admission_diagnoses(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """342 入院時診断セクション:入院時診断名の番号付きリスト。

    build_discharge_diagnoses と同じ code-lookup pattern を再利用するが
    ``admission_diagnosis_code`` を最優先で拾い、無ければ
    ``discharge_diagnosis_code`` に fallback。
    """
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
            # Issue #1777: when the display lookup misses, bracket the
            # code so it reads as a code reference rather than
            # free-text ("1. [G47.30]" instead of "1. G47.30"). The
            # admission-diagnosis list cannot be silently dropped —
            # the diagnosis WAS admitted so the entry must stay —
            # but the brackets stop downstream readers (and LLMs)
            # from parsing it as a word.
            lines.append(f"{idx}. [{code}]")
    if not lines:
        return t("section_none.admission_diagnoses", lang), facts
    return "\n".join(lines), facts


@section("present_illness")
def build_present_illness(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """360 現病歴セクション:現病歴の短文記述。

    退院時サマリー用は ADMISSION_HP と同じ disease_protocol の HPI
    reuses this template. Tense variation (narrative tone) will be
    LLM 差替時に調整予定。
    """
    hpi_text, facts = section_builder("hpi")(generator, ctx)
    lang = ctx.target_lang
    # HPI is already structured as a chronological onset narrative, so
    # no structural changes are needed. Text style harmonization will be
    # deferred to the LLM narrative pass when applicable.
    if not hpi_text:
        # #1266 empty-severity guard (see `build_hpi`). The severity
        # token is localized in the document language (localize_token);
        # a language without a label keeps the raw token.
        sev = str(ctx.severity or "").strip()
        from clinosim.modules.document.narrative._replacement_localization import localize_token

        sev = localize_token(sev, "severity", lang)
        if sev:
            hpi_text = t("hpi.admission_with_severity", lang, sev=sev)
        else:
            hpi_text = t("hpi.admission_no_severity", lang)
    return hpi_text, facts


# ─────────────────────────────────────────────────────────────────────
# JP-CLINS eReferral (診療情報提供書) section builders. JP-only.
# ─────────────────────────────────────────────────────────────────────


@section("referring_institution")
def build_referring_institution(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """920 紹介元情報セクション:紹介元(送信元)医療機関の記載。

    clinosim は単一病院を simulate するため、紹介元は常に当院固定。
    Dynamic facility name retrieval from hospital_config is deferred
    to the LLM narrative pass for future enhancement.
    """
    facts: list[str] = []
    lang = ctx.target_lang
    return t("referral.referring_institution_line", lang), facts


@section("referral_destination")
def build_referral_destination(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """910 紹介先情報セクション:紹介先医療機関の記載。

    clinosim は機関間連携 workflow を simulate しないため、紹介先は
    汎用 "他院" placeholder。将来:受け入れ想定医療機関の小さな pool
    から sample する余地あり。
    """
    facts: list[str] = []
    lang = ctx.target_lang
    return t("referral.referral_destination_line", lang), facts


# Ordered key tuple for build_referral_purpose SHA256 index sampling
# (Phase 1d-28). Key order is load-bearing: it defines which YAML slot
# maps to which hash-index, so cohort determinism depends on preserving it.
_REFERRAL_PURPOSE_KEYS: tuple[str, ...] = (
    "option_1",
    "option_2",
    "option_3",
    "option_4",
)


@section("referral_purpose")
def build_referral_purpose(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """950 紹介目的セクション:標準セットから決定的に一つ選択。

    encounter_id の hash で 4 選択肢から index 決定。cohort 全体で
    分布は stable、encounter 個別ではばらつき保持。
    """
    facts: list[str] = []
    lang = ctx.target_lang
    enc = ctx.encounter
    enc_id = _o(enc, "encounter_id", "") or "ENC-UNKNOWN"
    digest = hashlib.sha256(enc_id.encode("utf-8")).digest()
    idx = digest[0] % len(_REFERRAL_PURPOSE_KEYS)
    picked = _label("referral_purpose_options", _REFERRAL_PURPOSE_KEYS[idx], lang)
    facts.append(f"ctx.encounter.encounter_id[hash-idx={idx}]")
    return t("referral.referral_purpose_line", lang, purpose=picked), facts


@section("diagnoses_and_complaint")
def build_diagnoses_and_complaint(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """340 傷病名・主訴セクション:傷病名リスト + 主訴の複合セクション。"""
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
            # Issue #1777: bracket the code so it reads as a code
            # reference rather than free-text. The discharge-diagnosis
            # list cannot be silently dropped (diagnosis was discharged
            # with the encounter) but the brackets prevent LLM / NLP
            # tooling from treating "G47.30" as a word.
            dx_lines.append(f"{idx}. [{code}]")
    if dx_lines:
        facts.append("ctx.diagnoses")

    # Chief complaint
    cc_text, cc_facts = section_builder("chief_complaint")(generator, ctx)
    facts.extend(cc_facts)

    dx_body = "\n".join(dx_lines) if dx_lines else t("diagnoses_and_complaint.no_diagnoses", lang)
    text = t("diagnoses_and_complaint.section", lang, dx_lines=dx_body, cc_text=cc_text)
    return text, facts


@section("present_illness_ref")
def build_present_illness_ref(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """360 現病歴セクション(診療情報提供書用):HPI builder を再利用。"""
    hpi_text, facts = section_builder("hpi")(generator, ctx)
    lang = ctx.target_lang
    if not hpi_text:
        # #1266 empty-severity guard (see `build_hpi`).
        sev = str(ctx.severity or "").strip()
        from clinosim.modules.document.narrative._replacement_localization import localize_token

        sev = localize_token(sev, "severity", lang)
        if sev:
            hpi_text = t("hpi.ref_with_severity", lang, sev=sev)
        else:
            hpi_text = t("hpi.ref_no_severity", lang)
    return hpi_text, facts


# ─────────────────────────────────────────────────────────────────────
# JP-CLINS eCheckup (事業者健診) section builders. JP-only, opt-in.
# Covers the 2 mandatory sections of the 事業者健診 (statutory
# occupational-health checkup).
# ─────────────────────────────────────────────────────────────────────


@section("checkup_lab_results")
def build_checkup_lab_results(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """01031 事業者健診検査結果セクション:法定健診項目の判定文。

    sub-PR-B: ctx.lab_results から健診 5 項目の実測値を拾い、法定健診の
    基準に基づき A/B/C/D 判定を組み立てる。lab_results が空(または一部
    欠損)の場合は該当項目を「未測定」と記す。総合判定は各項目の最悪判定
    を返す。将来:HDL / TC / TG や AST / ALT を追加する sub-PR で拡張
    余地あり。
    """
    facts: list[str] = []
    lang = ctx.target_lang

    # The 5 measured values, keyed by canonical lab name (the Checkup panel
    # components are the one definition of the item set, Issue #2300).
    from clinosim.modules.health_checkup.engine import checkup_lab_names

    items = set(checkup_lab_names())
    results: dict[str, float | None] = {}
    for r in ctx.lab_results or []:
        name = _o(r, "lab_name", "")
        val = _o(r, "value", None)
        if name in items:
            results[name] = val
            facts.append(f"ctx.lab_results[{name}]")

    # Helpers return (catalog_key, format_kwargs, grade) —
    # grade ∈ {A, B, C, D} (A=normal, B=borderline, C=guidance
    # needed, D=detailed testing needed). The catalog_key is
    # resolved by ``t()`` at compose time so the prose is a
    # data-only concern.
    def _judge_bmi(v: float | None) -> tuple[str, dict, str]:
        if v is None:
            return ("checkup_lab_results.bmi_unmeasured", {}, "A")
        key, grade = {
            "underweight": ("bmi_underweight", "B"),
            "normal": ("bmi_normal", "A"),
            "overweight": ("bmi_obesity_1", "B"),
            "obese": ("bmi_obesity_2plus", "C"),
        }[bmi_band(v)]
        return (f"checkup_lab_results.{key}", {"v": v}, grade)

    def _judge_bp(sys_v: float | None, dia_v: float | None) -> tuple[str, dict, str]:
        if sys_v is None or dia_v is None:
            return ("checkup_lab_results.bp_unmeasured", {}, "A")
        kw = {"sbp": sys_v, "dbp": dia_v}
        key, grade = {
            "hypertension": ("bp_hypertension", "D"),
            "high_normal": ("bp_high_normal", "B"),
            "normal": ("bp_reference", "A"),
        }[bp_band(sys_v, dia_v, "JP")]
        return (f"checkup_lab_results.{key}", kw, grade)

    def _judge_hba1c(v: float | None) -> tuple[str, dict, str]:
        if v is None:
            return ("checkup_lab_results.hba1c_unmeasured", {}, "A")
        if v >= NARRATIVE_HBA1C_DIABETES_THRESHOLD:
            return ("checkup_lab_results.hba1c_diabetic", {"v": v}, "D")
        if v >= NARRATIVE_HBA1C_BORDERLINE_THRESHOLD:
            return ("checkup_lab_results.hba1c_borderline", {"v": v}, "B")
        return ("checkup_lab_results.hba1c_reference", {"v": v}, "A")

    def _judge_ldl(v: float | None) -> tuple[str, dict, str]:
        if v is None:
            return ("checkup_lab_results.ldl_unmeasured", {}, "A")
        if v >= NARRATIVE_LDL_HIGH_THRESHOLD:
            return ("checkup_lab_results.ldl_high", {"v": v}, "D")
        if v >= NARRATIVE_LDL_BORDERLINE_THRESHOLD:
            return ("checkup_lab_results.ldl_borderline", {"v": v}, "C")
        if v >= NARRATIVE_LDL_ELEVATED_THRESHOLD:
            return ("checkup_lab_results.ldl_elevated", {"v": v}, "B")
        return ("checkup_lab_results.ldl_reference", {"v": v}, "A")

    bmi_key, bmi_kw, bmi_grade = _judge_bmi(results.get("BMI"))
    bp_key, bp_kw, bp_grade = _judge_bp(results.get("SBP"), results.get("DBP"))
    hba1c_key, hba1c_kw, hba1c_grade = _judge_hba1c(results.get("HbA1c"))
    ldl_key, ldl_kw, ldl_grade = _judge_ldl(results.get("LDL"))

    bmi_desc = t(bmi_key, lang, **bmi_kw)
    bp_desc = t(bp_key, lang, **bp_kw)
    hba1c_desc = t(hba1c_key, lang, **hba1c_kw)
    ldl_desc = t(ldl_key, lang, **ldl_kw)

    # Overall assessment = worst grade across all items (A<B<C<D)
    grades = [bmi_grade, bp_grade, hba1c_grade, ldl_grade]
    overall = max(grades, key=lambda g: "ABCD".index(g))
    overall_note = t(f"checkup_lab_results.overall_{overall}", lang)

    text = "\n".join(
        [
            t("checkup_lab_results.body_measurements_line", lang, bmi=bmi_desc),
            t("checkup_lab_results.blood_pressure_line", lang, bp=bp_desc),
            t("checkup_lab_results.hba1c_line", lang, hba1c=hba1c_desc),
            t("checkup_lab_results.ldl_line", lang, ldl=ldl_desc),
            t("checkup_lab_results.overall_line", lang, overall=overall, overall_note=overall_note),
        ]
    )
    return text, facts


@section("checkup_questionnaire")
def build_checkup_questionnaire(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """01032 事業者健診問診結果セクション:PatientProfile 依存の個別問診記録。

    sub-PR-B: ctx.patient から以下を反映:
      - 既往歴:chronic_conditions(code → 日本語 display)
      - 服薬:current_medications
      - 生活習慣:smoking_status / alcohol_use
    判定は慢性疾患を持つ患者は「経過観察を要す」、それ以外は「経過
    観察不要」を返す MVP ロジック。将来 sub-PR で身体活動量・食習慣
    などの詳細問診を追加可能。
    """
    facts: list[str] = []
    lang = ctx.target_lang
    patient = ctx.patient

    # Convert past medical history (chronic_conditions) codes to the
    # display of the code the output emits, in the country's ICD-10
    # system (JP: MHLW ICD-10; Issue #2994).
    chronic = _o(patient, "chronic_conditions", []) or []
    history_lines: list[str] = []
    for cond in chronic:
        code = _o(cond, "code", "")
        if not code:
            continue
        # Issue #2994: the code the output emits for the condition and its
        # display in the country's ICD-10 system (JP: MHLW ICD-10).
        code, display = chronic_condition_coded(code, country_code(ctx.locale), lang)
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
        fallback = t("fallback.checkup_lifestyle_unmapped", lang, key=key)
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
