"""DEATH_CERTIFICATE (LOINC 64297-5) + DEATH_DISCHARGE_SUMMARY
(LOINC 18842-5 死亡退院サマリー) section builders.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1f of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

All helpers scoped exclusively to the DC/DDS cluster
(``_dc_resolve_primary_cause``, ``_dc_disease_pattern``,
``_dc_admission_to_discharge_hours``, ``_dc_duration_phrase``,
``_dds_severity``) are moved alongside the builders as module-level
private functions — no caller outside this cluster uses them.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from clinosim.codes import display as registry_display
from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._narrative_utils import _autopsy_performed_sha256
from clinosim.modules.document.narrative._template_helpers import _label
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


# ─────────────────────────────────────────────────────────────────────
# DC/DDS-local helpers (private to this module).
# ─────────────────────────────────────────────────────────────────────


def _dc_resolve_primary_cause(ctx: NarrativeContext) -> tuple[str, str, list[str]]:
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


def _dc_disease_pattern(icd_code: str) -> str:
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


def _dc_admission_to_discharge_hours(ctx: NarrativeContext) -> float | None:
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


def _dds_severity(severity: str, lang: str) -> str:
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


# ─────────────────────────────────────────────────────────────────────
# DEATH_CERTIFICATE (LOINC 64297-5) section builders.
# ─────────────────────────────────────────────────────────────────────


def build_dc_immediate_cause(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """直接死因 / Immediate cause of death.

    Sourced from the encounter's final ICD-10 diagnosis. When missing
    (no clinical_diagnosis on record), emits a never-fabricate marker.
    """
    lang = ctx.target_lang
    code, display, facts = _dc_resolve_primary_cause(ctx)
    if not code:
        return t("death_cert.immediate_cause_not_documented", lang), facts
    return t("death_cert_line.immediate_cause", lang, display=display, code=code), facts


def build_dc_duration_of_immediate_cause(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
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
    code, display, _ = _dc_resolve_primary_cause(ctx)
    pattern = _dc_disease_pattern(code)
    if code:
        facts.append("ctx.diagnoses[0].discharge_diagnosis_code")

    if los <= 0:
        hours = _dc_admission_to_discharge_hours(ctx)
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

    return _dc_duration_phrase(bucket, los, bucket_hours, pattern, display or "", lang), facts


def build_dc_underlying_cause(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """原死因 / Underlying cause of death.

    Same code as the immediate cause when the encounter has only a
    single diagnosis (mirrors how a simple death certificate lists the
    same ICD-10 on both lines). Uses the ICD-10 chapter root (letter +
    first two digits) as the underlying-cause bucket when the discharge
    dx has a decimal specifier.
    """
    lang = ctx.target_lang
    code, display, facts = _dc_resolve_primary_cause(ctx)
    if not code:
        return t("death_cert.underlying_cause_not_documented", lang), facts
    chapter = code.split(".")[0] if "." in code else code
    return t("death_cert_line.underlying_cause", lang, display=display, chapter=chapter), facts


def build_dc_contributing_conditions(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
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
        display = registry_display(system, code_val, lang) or code_val
        parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=code_val))
    if parts:
        facts.append("ctx.patient.chronic_conditions")

    # In-hospital complications add concrete detail beyond baseline
    # comorbidities (the daily loop records these on the record).
    comp_tokens = list(getattr(ctx, "complications_occurred", []) or [])[:3]
    if comp_tokens:
        facts.append("ctx.complications_occurred")

    primary_code, _display, _ = _dc_resolve_primary_cause(ctx)
    pattern = _dc_disease_pattern(primary_code)

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
        # Phase 1d-72: route through _localize_complication so the
        # JA output resolves ``hydrocephalus`` → 水頭症, ``urosepsis``
        # → 尿路性敗血症 etc. (see narrative_complications.yaml), and
        # the EN output picks up canonical casing (``requiring NIV``
        # not the lowercase slug fallback ``requiring niv``). Pre-
        # 1d-72 the composer just did ``.replace("_", " ")`` on the
        # raw complication key.
        comp_labels = comp_sep.join(_localize_complication(str(tok), lang) for tok in comp_tokens)
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


def build_dc_manner_of_death(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_dc_autopsy_status(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


# ─────────────────────────────────────────────────────────────────────
# DEATH_DISCHARGE_SUMMARY (LOINC 18842-5, 死亡退院サマリー) section builders.
# ─────────────────────────────────────────────────────────────────────


def build_dds_admission_state(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
            registry_display(adm_sys or system_key_for("diagnosis", ctx.locale.upper()), adm_code, lang) or adm_code
        )
        facts.append("ctx.diagnoses[0].admission_diagnosis_code")
    if adm_dt:
        facts.append("ctx.encounter.admission_datetime")
    severity = ctx.severity or "moderate"
    sev = _dds_severity(severity, lang)
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


def build_dds_treatment_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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


def build_dds_terminal_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
    code, display, _ = _dc_resolve_primary_cause(ctx)
    pattern = _dc_disease_pattern(code)
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


def build_dds_circumstances_of_death(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
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


def build_dds_cause_of_death(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """死因 / Cause of death (structured mirror of DC immediate cause).

    Uses the same _dc_resolve_primary_cause helper so this DDS
    section and the DC 直接死因 section are guaranteed to agree per
    encounter (single-source-of-truth per
    feedback_dr_conclusion_code_single_walk).
    """
    lang = ctx.target_lang
    code, display, facts = _dc_resolve_primary_cause(ctx)
    if not code:
        return t("death_cert.cause_of_death_not_documented", lang), facts
    return t("death_cert_line.cause_of_death", lang, display=display, code=code), facts


def build_dds_complications_and_comorbidities(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
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
        disp = registry_display(system, code_val, lang) or code_val
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
        # Phase 1d-72: route through _localize_complication so JA
        # resolves ``hypokalemia`` → 低カリウム血症 etc. and EN keeps
        # canonical casing. Sibling fix to _build_dc_contributing_conditions.
        comp_labels_str = cond_sep.join(_localize_complication(str(tok), lang) for tok in comp_tokens)
        parts.append(t("dds_complications_and_comorbidities.in_hospital_part", lang, list=comp_labels_str))
    # JA joins parts with "。" (list_sep.period) + trailing period;
    # EN joins with ". " (list_sep.period_space) + trailing period.
    body = t("list_sep.period_space", lang).join(parts) + t("list_sep.period", lang)
    return t("dds_complications_and_comorbidities.head", lang, body=body), facts


def build_dds_family_communication(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
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


def build_dds_autopsy_status_and_findings(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
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
