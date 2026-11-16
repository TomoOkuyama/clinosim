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

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from clinosim.codes import display as registry_display
from clinosim.codes import lookup as code_lookup
from clinosim.codes import system_key_for
from clinosim.countries import country_code
from clinosim.locale.i18n import t
from clinosim.locale.loader import narrative_label as _label
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._narrative_utils import _autopsy_performed_sha256
from clinosim.modules.document.narrative.renderers._shared_helpers import chronic_condition_coded
from clinosim.modules.document.narrative.renderers.section_builders._registry import section
from clinosim.modules.document.reference_data_loaders import load_death_cause_chain
from clinosim.types.document import NarrativeContext

if TYPE_CHECKING:
    from clinosim.modules.document.narrative.template_generator import (
        TemplateNarrativeGenerator,
    )


# ─────────────────────────────────────────────────────────────────────
# DC/DDS-local helpers (private to this module).
# ─────────────────────────────────────────────────────────────────────

TERMINAL_HYPOTENSION_SBP_MAX = 90
"""Last recorded SBP (mmHg) below which the terminal course reads as
circulatory failure (Issue #2985; the NEWS2 3-point band starts at 90)."""

TERMINAL_HYPOXAEMIA_SPO2_MAX = 90.0
"""Last recorded SpO2 (%) below which it reads as respiratory failure."""

_UNRESPONSIVE_AVPU = frozenset({"P", "U"})


def _as_datetime(value: object) -> datetime | None:
    """``value`` as a datetime (CIF dicts carry ISO strings), else ``None``."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _last_recorded_vitals(ctx: NarrativeContext) -> object | None:
    """The last full set of vitals (HR, BP and SpO2 charted; not a monitor
    HR / SpO2 pair) at or before the death, or ``None``."""
    death = _as_datetime(_o(ctx.encounter, "discharge_datetime", None))
    best, best_at = None, None
    for v in ctx.vitals or []:
        at = _as_datetime(_o(v, "timestamp", None))
        if at is None or any(_o(v, k, None) is None for k in ("heart_rate", "systolic_bp", "spo2")):
            continue
        if death is not None and at > death:
            continue
        if best_at is None or at > best_at:
            best, best_at = v, at
    return best


def _terminal_phrase_key(last: object) -> str | None:
    """The terminal-course phrase the last recorded vitals show, or ``None``."""
    sbp = _o(last, "systolic_bp", None)
    if sbp is not None and sbp < TERMINAL_HYPOTENSION_SBP_MAX:
        return "dds_terminal_course.phrase_acute"
    if _o(last, "spo2", 100.0) < TERMINAL_HYPOXAEMIA_SPO2_MAX:
        return "dds_terminal_course.phrase_respiratory"
    if str(_o(last, "consciousness_level", "") or "") in _UNRESPONSIVE_AVPU:
        return "dds_terminal_course.phrase_consciousness"
    return None


def _last_vitals_line(last: object, lang: str) -> str:
    """ "The last recorded observations (ts) were HR .., BP .., ..." from the record."""
    parts = [t("dds_terminal_course.hr", lang, hr=_o(last, "heart_rate"))]
    if _o(last, "systolic_bp", None) is not None and _o(last, "diastolic_bp", None) is not None:
        parts.append(t("dds_terminal_course.bp", lang, sbp=_o(last, "systolic_bp"), dbp=_o(last, "diastolic_bp")))
    if _o(last, "respiratory_rate", None) is not None:
        parts.append(t("dds_terminal_course.rr", lang, rr=_o(last, "respiratory_rate")))
    o2 = t("dds_terminal_course.on_oxygen", lang) if _o(last, "on_supplemental_oxygen", False) else ""
    parts.append(t("dds_terminal_course.spo2", lang, spo2=f"{float(_o(last, 'spo2')):.0f}", o2=o2))
    avpu = str(_o(last, "consciousness_level", "") or "")
    if avpu in ("A", "V", "P", "U"):
        parts.append(t(f"fhir_obs_text.avpu_{avpu}", lang))
    ts = str(_as_datetime(_o(last, "timestamp")))[:16]
    return t("dds_terminal_course.last_vitals", lang, ts=ts, values=t("list_sep.serial", lang).join(parts))


def _sex(ctx: NarrativeContext) -> str:
    return str(_o(ctx.patient, "sex", "") or "") if ctx.patient else ""


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


@dataclass(frozen=True)
class _Cause:
    """One condition on the certificate: its emitted code ("" when it has
    none), its display, the internal code it came from, its onset (in-hospital
    complications) and the record field it was read from."""

    code: str
    display: str
    internal: str
    onset: datetime | None
    fact: str


@dataclass(frozen=True)
class _CauseChain:
    """The certificate's causal sequence (Issue #3255): the immediate cause,
    the condition between it and the underlying cause (``None`` when there is
    none) and the underlying cause, plus the complication tokens used."""

    immediate: _Cause
    due_to: _Cause | None
    underlying: _Cause
    used_complications: frozenset[str]


def _complication_key(name: object) -> str:
    """A complication token as ``death_cause_chain.yaml`` keys it."""
    return "_".join(str(name or "").strip().lower().split())


def _coded_cause(code: str, ctx: NarrativeContext, fact: str, onset: datetime | None = None) -> _Cause:
    emit, display = chronic_condition_coded(code, country_code(ctx.locale), ctx.target_lang, _sex(ctx))
    return _Cause(emit, display, code, onset, fact)


def _terminal_complication(ctx: NarrativeContext, death: datetime | None) -> tuple[_Cause, str] | None:
    """The latest-onset in-hospital complication that can be the immediate
    cause of death (``death_cause_chain.yaml``) and its token, or ``None``.
    Onsets after the death are not considered; a complication without an
    onset ranks before every dated one."""
    table = load_death_cause_chain().immediate_cause_complications
    best: tuple[datetime, int, str] | None = None
    for index, event in enumerate(ctx.complications_events or []):
        key = _complication_key(_o(event, "name", ""))
        if key not in table:
            continue
        onset = _as_datetime(_o(event, "onset_datetime", None))
        if onset is not None and death is not None and onset > death:
            continue
        rank = (onset or datetime.min, index, key)
        if best is None or rank[:2] > best[:2]:
            best = rank
    if best is None:
        return None
    onset = best[0] if best[0] != datetime.min else None
    key = best[2]
    code = table[key]
    if code:
        return _coded_cause(code, ctx, "ctx.complications_events", onset), key
    return _Cause("", _localize_complication(key, ctx.target_lang), "", onset, "ctx.complications_events"), key


def _dc_cause_chain(ctx: NarrativeContext) -> _CauseChain | None:
    """The causal sequence of the death certificate, from one walk of the
    record (NCHS Physicians' Handbook 2003 Part I; MHLW 死亡診断書記入
    マニュアル Ⅰ欄):

    - underlying cause: the encounter's final diagnosis (discharge, else
      admission code) with its full code; a sequel code (severe sepsis /
      septic shock, ``death_cause_chain.yaml``) is not an underlying cause,
      so the admission diagnosis (the infection) is, and the sequel sits
      between them;
    - immediate cause: the latest in-hospital complication that can cause
      death, else the sequel, else the underlying cause itself (a single
      condition is the whole sequence).

    ``None`` when the record has no diagnosis code."""
    diagnoses = ctx.diagnoses or []
    primary = diagnoses[0] if diagnoses else None
    if primary is None:
        return None
    discharge = str(_o(primary, "discharge_diagnosis_code", "") or "")
    admission = str(_o(primary, "admission_diagnosis_code", "") or "")
    final = discharge or admission
    if not final:
        return None
    chain = load_death_cause_chain()
    final_fact = (
        "ctx.diagnoses[0].discharge_diagnosis_code" if discharge else "ctx.diagnoses[0].admission_diagnosis_code"
    )
    sequel: _Cause | None = None
    if final in chain.sequel_codes and admission and admission not in chain.sequel_codes:
        sequel = _coded_cause(final, ctx, final_fact)
        underlying = _coded_cause(admission, ctx, "ctx.diagnoses[0].admission_diagnosis_code")
    else:
        underlying = _coded_cause(final, ctx, final_fact)
    death = _as_datetime(_o(ctx.encounter, "discharge_datetime", None))
    found = _terminal_complication(ctx, death)
    if found is not None and found[0].code and found[0].code in {underlying.code, sequel.code if sequel else ""}:
        found = None
    if found is None:
        immediate = sequel or underlying
        return _CauseChain(immediate, None, underlying, frozenset())
    terminal, key = found
    table = chain.immediate_cause_complications
    # Every token naming the same condition (``aki`` / ``acute_kidney_injury``).
    used = frozenset(k for k in table if k == key or (table[key] and table[k] == table[key]))
    return _CauseChain(terminal, sequel, underlying, used)


def _cause_text(cause: _Cause, lang: str) -> str:
    """A cause as the certificate prints it: display with code, or the name
    alone when the condition has no code."""
    if not cause.code:
        return cause.display
    return t("death_cert_line.coded_cause", lang, display=cause.display, code=cause.code)


def _chain_facts(chain: _CauseChain) -> list[str]:
    facts: list[str] = []
    for cause in (chain.immediate, chain.due_to, chain.underlying):
        if cause is not None and cause.fact not in facts:
            facts.append(cause.fact)
    return facts


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


def _dc_duration_bucket(days: int, hours: float | None) -> str:
    """The granularity of a time-to-death phrase: ``hours`` below a day (when
    the hours are known), ``same_day``, ``days`` up to a week, ``weeks`` up to
    four weeks, then ``long``."""
    if days <= 0:
        return "hours" if hours is not None and 0 < hours < 24 else "same_day"
    if days <= 7:
        return "days"
    if days <= 28:
        return "weeks"
    return "long"


def _dc_onset_duration(cause: _Cause, onset: datetime, death: datetime, lang: str) -> str:
    """The 直接死因までの期間 phrase for an immediate cause with a recorded
    onset: the onset-to-death interval with the buckets of
    ``_dc_duration_bucket``."""
    seconds = max(0.0, (death - onset).total_seconds())
    whole_days, rest = divmod(seconds, 86400.0)
    bucket = _dc_duration_bucket(int(whole_days), rest / 3600.0)
    days = max(1, round(seconds / 86400.0))
    if bucket in ("hours", "same_day"):
        body = t("dc_duration.onset_body_hours", lang, hours=max(1, round(rest / 3600.0)), disease=cause.display)
    elif bucket == "days":
        body = t("dc_duration.onset_body_days", lang, days=days, disease=cause.display)
    else:
        weeks = max(1, round(days / 7))
        body = t("dc_duration.onset_body_weeks", lang, weeks=weeks, days=days, disease=cause.display)
    return f"{t('dc_duration.prefix', lang)}{body}{t('dc_duration.onset_tail', lang)}"


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
    # Missing label: English (spec §6), never a fixed Japanese word.
    return _label("dds_severity", key, lang, fallback=key.capitalize())


# ─────────────────────────────────────────────────────────────────────
# DEATH_CERTIFICATE (LOINC 64297-5) section builders.
# ─────────────────────────────────────────────────────────────────────


@section("immediate_cause_of_death")
def build_dc_immediate_cause(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """直接死因 / Immediate cause of death (Part I line (a)).

    The immediate cause of ``_dc_cause_chain``; when a condition lies
    between it and the underlying cause (septic shock under an organ
    failure), that condition follows as the "due to" line. Without a
    diagnosis on record, a never-fabricate marker.
    """
    lang = ctx.target_lang
    chain = _dc_cause_chain(ctx)
    if chain is None:
        return t("death_cert.immediate_cause_not_documented", lang), []
    text = t("death_cert_line.immediate_cause", lang, cause=_cause_text(chain.immediate, lang))
    if chain.due_to is not None:
        text += t("death_cert_line.due_to", lang, cause=_cause_text(chain.due_to, lang))
    return text, _chain_facts(chain)


@section("duration_of_immediate_cause")
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
    so explicitly. An immediate cause that began during the stay (an
    in-hospital complication, Issue #3255) is timed from its onset.
    """
    lang = ctx.target_lang
    chain = _dc_cause_chain(ctx)
    death = _as_datetime(_o(ctx.encounter, "discharge_datetime", None))
    onset = chain.immediate.onset if chain is not None else None
    if chain is not None and onset is not None and death is not None:
        facts_onset = [chain.immediate.fact, "ctx.encounter.discharge_datetime"]
        return _dc_onset_duration(chain.immediate, onset, death, lang), facts_onset
    facts: list[str] = ["ctx.los_days"]
    los = ctx.los_days or 0
    display = chain.immediate.display if chain is not None else ""
    pattern = _dc_disease_pattern(chain.underlying.internal) if chain is not None else "unknown"
    if chain is not None:
        facts.extend(_chain_facts(chain))

    hours = _dc_admission_to_discharge_hours(ctx) if los <= 0 else None
    bucket = _dc_duration_bucket(los, hours)
    bucket_hours = max(1, int(round(hours))) if bucket == "hours" and hours is not None else 0

    return _dc_duration_phrase(bucket, los, bucket_hours, pattern, display or "", lang), facts


@section("underlying_cause_of_death")
def build_dc_underlying_cause(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """原死因 / Underlying cause of death (the lowest line of Part I).

    The disease that started the sequence (``_dc_cause_chain``), with its
    full code. It is the immediate cause too when the record shows a
    single condition.
    """
    lang = ctx.target_lang
    chain = _dc_cause_chain(ctx)
    if chain is None:
        return t("death_cert.underlying_cause_not_documented", lang), []
    return t("death_cert_line.underlying_cause", lang, cause=_cause_text(chain.underlying, lang)), [
        chain.underlying.fact
    ]


@section("contributing_conditions")
def build_dc_contributing_conditions(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """影響を及ぼした傷病名 / Contributing conditions.

    Real 死亡診断書 physicians write this field as a short prose
    paragraph explaining WHICH chronic comorbidities plausibly
    contributed to the terminal event — a bare list is undersells
    the clinical linkage. Template enriches with:
      - Lead-in phrase naming the count (単発の / 複数の)
      - The comorbidity list with codes: the conditions that can
        contribute to death (``death_cause_chain.yaml``), up to 5
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
    chain = _dc_cause_chain(ctx)
    relevance = load_death_cause_chain()
    # Categories already on a cause line (Part I) are not repeated here.
    cause_categories = (
        {c.code[:3] for c in (chain.immediate, chain.due_to, chain.underlying) if c is not None and c.code}
        if chain is not None
        else set()
    )
    conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
    parts: list[str] = []
    for c in list(conds):
        code_val = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code_val or not relevance.is_contributing(code_val):
            continue
        # Issue #2994: the code the output emits and its display (US
        # dementia F03.90, not the internal F00 category).
        emit, display = chronic_condition_coded(code_val, country_code(ctx.locale), lang, _sex(ctx))
        if emit[:3] in cause_categories:
            continue
        parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=emit))
    parts = parts[:5]
    if parts:
        facts.append("ctx.patient.chronic_conditions")

    # In-hospital complications add concrete detail beyond baseline
    # comorbidities (the daily loop records these on the record); the one
    # stated as the immediate cause is not repeated.
    used = chain.used_complications if chain is not None else frozenset()
    comp_tokens = [
        tok for tok in getattr(ctx, "complications_occurred", []) or [] if _complication_key(tok) not in used
    ][:3]
    if comp_tokens:
        facts.append("ctx.complications_occurred")

    pattern = _dc_disease_pattern(chain.underlying.internal) if chain is not None else "unknown"

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
        comp_key = "dc_contributing.comp_part_after_list" if list_part else "dc_contributing.comp_part"
        comp_part = t(comp_key, lang, comp_labels=comp_labels)
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
    # No list_part → prefix + comp_part only, without the comp_part's own
    # leading separator (the English phrase starts with a space).
    return f"{prefix}{comp_part.strip()}", facts


@section("manner_of_death")
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


@section("autopsy_status")
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


@section("admission_state")
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


@section("treatment_course")
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


@section("terminal_course")
def build_dds_terminal_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """終末期経過 / Terminal course (final ~24-72 h).

    Anchors on the discharge (= death) datetime and describes the
    final hours from the last full set of vitals recorded before death
    (Issue #2985): circulatory failure, respiratory failure or falling
    consciousness as those vitals show, followed by the values
    themselves. Without such vitals (or when they show none of these)
    the phrase is keyed on disease pattern (chronic decompensation vs
    acute event) and no vital values are quoted.
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

    # Issue #2985: the course the last recorded vitals show, quoted; the
    # disease-pattern phrase only when they show none.
    last = _last_recorded_vitals(ctx)
    phrase_key = _terminal_phrase_key(last) if last is not None else None
    if phrase_key is None:
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
    line = t("dds_terminal_course.full_line", lang, phrase=phrase, dx_part=dx_part, when=when)
    if last is not None:
        facts.append("ctx.vitals")
        line = line + t("list_sep.sentence_gap", lang) + _last_vitals_line(last, lang)
    return line, facts


@section("circumstances_of_death")
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
        # CIF procedures carry ``procedure_type`` and codes only (AD-30;
        # Issue #3246) — no ``name`` / ``code`` key. The type is matched by
        # keyword and the codes against the CPR codes. Displays are not
        # matched: the K-code J044 reads "intubation for resuscitation",
        # which is not CPR.
        ptype = str(_o(p, "procedure_type", "") or "").lower()
        codes = {str(_o(p, key, "") or "") for key in ("procedure_code", "procedure_code_us", "procedure_code_jp")}
        if any(k in ptype for k in ("cpr", "cardiopulmonary", "resuscit", "defibrill")):
            resuscitation = True
            break
        if codes & {"5A12012", "92950", "99288"}:  # PCS / CPT CPR codes
            resuscitation = True
            break
    if procedures:
        facts.append("ctx.procedures")

    key = "dds_circumstances_of_death.resuscitation" if resuscitation else "dds_circumstances_of_death.natural"
    return t(key, lang), facts


@section("cause_of_death")
def build_dds_cause_of_death(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """死因 / Cause of death (structured mirror of DC immediate cause).

    Uses the same ``_dc_cause_chain`` walk as the DC 直接死因 section so
    the two documents agree per encounter.
    """
    lang = ctx.target_lang
    chain = _dc_cause_chain(ctx)
    if chain is None:
        return t("death_cert.cause_of_death_not_documented", lang), []
    return t("death_cert_line.cause_of_death", lang, cause=_cause_text(chain.immediate, lang)), [chain.immediate.fact]


@section("complications_and_comorbidities")
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
        emit, disp = chronic_condition_coded(code_val, country_code(ctx.locale), lang, _sex(ctx))
        cond_labels.append(t("list_item.inline_dx_with_code", lang, display=disp, code=emit))
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
        # canonical casing. Sibling fix to build_dc_contributing_conditions.
        comp_labels_str = cond_sep.join(_localize_complication(str(tok), lang) for tok in comp_tokens)
        parts.append(t("dds_complications_and_comorbidities.in_hospital_part", lang, list=comp_labels_str))
    # JA joins parts with "。" (list_sep.period) + trailing period;
    # EN joins with ". " (list_sep.period_space) + trailing period.
    body = t("list_sep.period_space", lang).join(parts) + t("list_sep.period", lang)
    return t("dds_complications_and_comorbidities.head", lang, body=body), facts


@section("family_communication")
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


@section("autopsy_status_and_findings")
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
