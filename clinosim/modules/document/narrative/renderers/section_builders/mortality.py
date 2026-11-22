"""DEATH_CERTIFICATE (LOINC 64297-5) + DEATH_DISCHARGE_SUMMARY
(LOINC 18842-5 死亡退院サマリー) section builders.

Extracted verbatim from ``template_generator.TemplateNarrativeGenerator``
as step C1f of the full-review Phase C renderer split (CRITICAL C1).
Behavior is byte-identical.

All helpers scoped exclusively to the DC/DDS cluster
(``_dc_cause_chain``, ``_dc_disease_pattern``,
``_dc_admission_to_discharge_hours``, ``_dc_duration_phrase``,
``_dds_severity``) are moved alongside the builders as module-level
private functions — no caller outside this cluster uses them.

Each builder is a free-standing ``(generator, ctx) -> (text, facts)``
function. The class methods of the same name become thin delegators so
``renderers/composition_sections.py`` (which looks up
``generator._build_<section>`` by name) stays unchanged.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from clinosim.codes import display as registry_display
from clinosim.codes.drugs import drug_classes, drug_display
from clinosim.countries import country_code
from clinosim.locale.free_text import localize_drug_name
from clinosim.locale.i18n import t
from clinosim.locale.loader import narrative_label as _label
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.disease.protocol import working_diagnosis_code
from clinosim.modules.document.narrative._localization import _localize_complication
from clinosim.modules.document.narrative._narrative_utils import _autopsy_performed_sha256
from clinosim.modules.document.narrative.renderers._shared_helpers import (
    diagnosis_coded,
    procedure_names,
    procedure_prose_name,
    secondary_diagnosis_codes,
)
from clinosim.modules.document.narrative.renderers.section_builders._registry import section
from clinosim.modules.document.reference_data_loaders import (
    load_bedside_procedure_codes,
    load_death_cause_chain,
    load_death_course,
)
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


def _terminal_mechanism(chain: _CauseChain | None, lang: str) -> tuple[str | None, str]:
    """The terminal-course phrase key and the "attributed to ..." part of the
    certificate's cause chain: the mechanism of the immediate cause (``None``
    when its code names none) and the causes in certificate order, each as the
    certificate prints it."""
    if chain is None:
        return None, ""
    name = load_death_cause_chain().terminal_phrase(chain.immediate.internal)
    key = f"dds_terminal_course.phrase_{name}" if name else None
    causes = [chain.immediate]
    for cause in (chain.due_to, chain.underlying):
        if cause is not None and cause.internal != causes[-1].internal:
            causes.append(cause)
    text = _cause_text(causes[0], lang) + "".join(
        t("dds_terminal_course.chain_due_to", lang, cause=_cause_text(c, lang)) for c in causes[1:]
    )
    return key, t("dds_terminal_course.dx_part", lang, display=text)


def _terminal_phrase_key(last: object) -> str | None:
    """The terminal-course phrase the last recorded vitals show, or ``None``.
    Used only when the record has no cause chain (Issue #3470)."""
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
    contributing: tuple[_Cause, ...] = ()
    """The stay's secondary diagnoses that sit on no cause line (Issue #3537)."""


def _complication_key(name: object) -> str:
    """A complication token as ``death_cause_chain.yaml`` keys it."""
    return "_".join(str(name or "").strip().lower().split())


def _coded_cause(code: str, ctx: NarrativeContext, fact: str, onset: datetime | None = None) -> _Cause:
    emit, display = diagnosis_coded(code, country_code(ctx.locale), ctx.target_lang, _sex(ctx))
    return _Cause(emit, display, code, onset, fact)


def _creatinine_rows(labs: Iterable[Any] | None, analyte: str) -> list[tuple[datetime, float, str]]:
    """``(result time, value, unit)`` of the creatinine results in ``labs``, by time."""
    from clinosim.modules.observation.engine import canonical_lab_name

    rows: list[tuple[datetime, float, str]] = []
    for lab in labs or []:
        if canonical_lab_name(str(_o(lab, "lab_name", "") or "")) != analyte:
            continue
        at = _as_datetime(_o(lab, "result_datetime", None))
        value = _o(lab, "value", None)
        if at is None or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        rows.append((at.replace(tzinfo=None), float(value), str(_o(lab, "unit", "") or "")))
    return sorted(rows)


def _first_abnormal_onset(ctx: NarrativeContext, event_onset: datetime | None) -> datetime | None:
    """The onset of a lab-defined complication (``onset_from_lab_complications``:
    KDIGO AKI): the first creatinine of the stay that rises by the absolute
    amount within its window, or to the relative multiple of the baseline
    (``notable_labs.yaml`` ``aki``), when that is earlier than the logged
    event. The baseline is the lowest of the patient's latest earlier result
    (another encounter) and the stay's own earlier results within the relative
    window. A first stay result that already meets the criterion against an
    earlier result dates the onset to the admission. ``event_onset`` when no
    result meets the criterion earlier."""
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    rule = notable_lab_rules().aki
    stay = _creatinine_rows(ctx.lab_results, rule.analyte)
    if not stay:
        return event_onset
    admission = _as_datetime(_o(ctx.encounter, "admission_datetime", None))
    prior = [r for r in _creatinine_rows(ctx.prior_lab_results, rule.analyte) if admission is None or r[0] < admission]
    prior_row = prior[-1] if prior else None
    for index, (at, value, unit) in enumerate(stay):
        if event_onset is not None and at >= event_onset:
            break
        refs = [v for t_, v, u in stay[:index] if u == unit and t_ >= at - timedelta(days=rule.relative_window_days)]
        if prior_row is not None and prior_row[2] == unit:
            refs.append(prior_row[1])
        if not refs:
            continue
        relative = value >= rule.relative_rise * min(refs)
        near = [v for t_, v, u in stay[:index] if u == unit and t_ >= at - timedelta(hours=rule.absolute_window_hours)]
        if prior_row is not None and prior_row[2] == unit:
            near.append(prior_row[1])
        absolute = unit == rule.absolute_rise_unit and bool(near) and round(value - min(near), 6) >= rule.absolute_rise
        if relative or absolute:
            return admission if index == 0 and admission is not None else at
    return event_onset


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
    if key in load_death_cause_chain().onset_from_lab_complications:
        onset = _first_abnormal_onset(ctx, onset)
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
      death, else the sequel, else the stay's first secondary acute diagnosis
      (pneumonia after a cerebral infarction; Issue #3537), else the
      underlying cause itself (a single condition is the whole sequence). A
      secondary acute diagnosis under a complication or a sequel is the
      "due to" line when that is free; every other secondary diagnosis is a
      contributing condition (``_CauseChain.contributing``).

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
    placed = [underlying, sequel, found[0] if found is not None else None]
    categories = {c.code[:3] for c in placed if c is not None and c.code}
    secondary = [
        _coded_cause(code, ctx, "ctx.diagnoses[0].secondary_diagnosis_codes")
        for code in secondary_diagnosis_codes(diagnoses)
        if code[:3] not in categories
    ]
    acute = next((c for c in secondary if _dc_disease_pattern(c.internal) == "acute"), None)
    if found is None:
        if sequel is None and acute is not None:
            rest = tuple(c for c in secondary if c is not acute)
            return _CauseChain(acute, None, underlying, frozenset(), rest)
        return _CauseChain(sequel or underlying, None, underlying, frozenset(), tuple(secondary))
    terminal, key = found
    table = chain.immediate_cause_complications
    # Every token naming the same condition (``aki`` / ``acute_kidney_injury``).
    used = frozenset(k for k in table if k == key or (table[key] and table[k] == table[key]))
    if sequel is None and acute is not None:
        return _CauseChain(terminal, acute, underlying, used, tuple(c for c in secondary if c is not acute))
    return _CauseChain(terminal, sequel, underlying, used, tuple(secondary))


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


def _hours_in_window(ctx: NarrativeContext) -> int | None:
    """The whole hours from admission to death when that stay is shorter than
    the hours window of ``death_course.yaml`` (Issue #3537), else ``None``.
    The one rule of the certificate's time to death and the summary's length
    of stay: a 23 h stay is "23 hours", never "1 days"."""
    hours = _dc_admission_to_discharge_hours(ctx)
    if hours is None or not 0 < hours < load_death_course().duration.hours_below:
        return None
    return max(1, round(hours))


def _onset_is_known(ctx: NarrativeContext, pattern: str) -> bool:
    """Whether the presentation gives the onset: the disease's
    ``hpi_template.onset_type`` is one of ``onset_known_types``
    (``death_course.yaml``), or, without a disease protocol, the cause is an
    acute disease (``_dc_disease_pattern``)."""
    from clinosim.modules.document.narrative.renderers.section_builders.chief_complaint import _visit_onset_type

    onset_type = _visit_onset_type(ctx)
    if onset_type is None:
        return pattern == "acute"
    return onset_type in load_death_course().duration.onset_known_types


def _dc_duration_phrase(
    bucket: str,
    los: int,
    hours: int,
    pattern: str,
    disease_label: str,
    lang: str,
    onset_known: bool = False,
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
        body = t(
            "dc_duration.body_hours_one" if hours == 1 else "dc_duration.body_hours", lang, hours=hours, suffix=suffix
        )
    elif bucket == "same_day":
        body = t("dc_duration.body_same_day", lang, suffix=suffix)
    elif bucket == "days":
        body = t("dc_duration.body_days_one" if los == 1 else "dc_duration.body_days", lang, los=los, suffix=suffix)
    else:  # "long"
        weeks = max(4, round(los / 7))
        body = t("dc_duration.body_long", lang, weeks=weeks, suffix=suffix)
    # An acute onset is not "unknown" (Issue #3537).
    tail = t("dc_duration.onset_tail" if onset_known else "dc_duration.tail", lang)
    return f"{prefix}{chronic_lead}{body}{tail}"


def _dc_duration_bucket(days: int, hours: float | None) -> str:
    """The granularity of a time-to-death phrase: ``hours`` below the hours
    window of ``death_course.yaml`` (Issue #3537; ``hours`` is the whole
    interval, when known), ``same_day``, ``days`` below the week boundary
    (Issue #3256: "11 days", not "2 week(s) (11 d)"), then ``long`` (weeks)."""
    if hours is not None and 0 < hours < load_death_course().duration.hours_below:
        return "hours"
    if days <= 0:
        return "same_day"
    if days < load_death_course().duration.days_below_weeks:
        return "days"
    return "long"


def _dc_onset_duration(cause: _Cause, onset: datetime, death: datetime, lang: str) -> str:
    """The 直接死因までの期間 phrase for an immediate cause with a recorded
    onset: the onset-to-death interval with the buckets of
    ``_dc_duration_bucket``."""
    seconds = max(0.0, (death - onset).total_seconds())
    bucket = _dc_duration_bucket(int(seconds // 86400.0), seconds / 3600.0)
    days = max(1, round(seconds / 86400.0))
    if bucket in ("hours", "same_day"):
        body = t("dc_duration.onset_body_hours", lang, hours=max(1, round(seconds / 3600.0)), disease=cause.display)
    elif bucket == "days":
        body = t(
            "dc_duration.onset_body_days_one" if days == 1 else "dc_duration.onset_body_days",
            lang,
            days=days,
            disease=cause.display,
        )
    else:
        body = t("dc_duration.onset_body_long", lang, weeks=round(days / 7), disease=cause.display)
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

    hours = _dc_admission_to_discharge_hours(ctx)
    bucket = _dc_duration_bucket(los, hours)
    bucket_hours = _hours_in_window(ctx) or 0 if bucket == "hours" else 0
    onset_known = _onset_is_known(ctx, pattern)

    return _dc_duration_phrase(bucket, los, bucket_hours, pattern, display or "", lang, onset_known), facts


@section("underlying_cause_of_death")
def build_dc_underlying_cause(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """原死因 / Underlying cause of death (the lowest line of Part I).

    The disease that started the sequence (``_dc_cause_chain``), with its
    full code. When the record shows a single condition it is the immediate
    cause too, and this line points back to line (a) (Issue #3405).
    """
    lang = ctx.target_lang
    chain = _dc_cause_chain(ctx)
    if chain is None:
        return t("death_cert.underlying_cause_not_documented", lang), []
    if chain.due_to is None and chain.immediate.internal == chain.underlying.internal:
        # One condition is the whole sequence: line (a) names it and this
        # line points back to it rather than repeating the disease.
        return t("death_cert_line.underlying_same_as_immediate", lang), [chain.underlying.fact]
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
    # Issue #3537: the stay's secondary diagnoses that sit on no cause line.
    secondary = chain.contributing if chain is not None else ()
    for cause in secondary:
        parts.append(
            t("list_item.inline_dx_with_code", lang, display=cause.display, code=cause.code)
            if cause.code
            else cause.display
        )
        cause_categories.add(cause.code[:3])
    if parts:
        facts.append("ctx.diagnoses[0].secondary_diagnosis_codes")
    chronic_start = len(parts)
    for c in list(conds):
        code_val = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code_val or not relevance.is_contributing(code_val):
            continue
        # Issue #2994: the code the output emits and its display (US
        # dementia F03.90, not the internal F00 category).
        emit, display = diagnosis_coded(code_val, country_code(ctx.locale), lang, _sex(ctx))
        if emit[:3] in cause_categories:
            continue
        parts.append(t("list_item.inline_dx_with_code", lang, display=display, code=emit))
    if len(parts) > chronic_start:
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


@section("surgery_performed")
def build_dc_surgery_performed(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """手術 / Surgery (Issue #3537): the operative procedures of the stay
    (the codes of ``operative_note_codes``, bedside_procedure_codes.yaml,
    the set that gets an operative note) with their names and dates, in
    start order; none performed reads as no surgery. Template-only, a
    structured field of the legal form."""
    lang = ctx.target_lang
    operative = load_bedside_procedure_codes()["operative_note"]
    rows: list[tuple[datetime, str]] = []
    for proc in ctx.procedures or []:
        if str(_o(proc, "procedure_code", "") or "").strip() not in operative:
            continue
        start = _as_datetime(_o(proc, "start_datetime", None))
        name = procedure_prose_name(proc, lang)
        if start is not None and name:
            rows.append((start, name))
    if not rows:
        return t("death_cert_surgery.not_performed", lang), ["ctx.procedures"]
    items = [
        t(
            "death_cert_surgery.item",
            lang,
            name=name,
            year=at.year,
            month=at.month,
            day=at.day,
            date=at.date().isoformat(),
        )
        for at, name in sorted(rows)
    ]
    return t("death_cert_surgery.performed", lang, items=t("list_sep.semicolon", lang).join(items)), ["ctx.procedures"]


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


@section("time_of_death")
def build_dc_time_of_death(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """死亡年月日時刻 / Date and time of death (Issue #3405).

    The death datetime of the record: the terminating encounter's discharge
    datetime, else the patient's death datetime. Never fabricated: a record
    without one says so.
    """
    lang = ctx.target_lang
    for value, fact in (
        (_o(ctx.encounter, "discharge_datetime", None), "ctx.encounter.discharge_datetime"),
        (_o(ctx.patient, "death_datetime", None) if ctx.patient else None, "ctx.patient.death_datetime"),
    ):
        when = _as_datetime(value)
        if when is not None:
            text = t(
                "death_cert_line.time_of_death",
                lang,
                year=when.year,
                month=when.month,
                day=when.day,
                hour=when.hour,
                minute=when.minute,
            )
            return text, [fact]
    return t("death_cert.time_of_death_not_documented", lang), []


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
# DDS course helpers (Issue #3256): what the record shows about the stay and
# the death, read by the rules of ``death_course.yaml``.
# ─────────────────────────────────────────────────────────────────────


def _given_doses(ctx: NarrativeContext) -> list[tuple[datetime, str]]:
    """``(time, drug reference)`` of every MAR dose given, in time order. The
    reference is the catalog drug id, else the recorded drug name."""
    doses: list[tuple[datetime, str]] = []
    for m in ctx.medications or []:
        if str(_o(m, "status", "given") or "given") != "given":
            continue
        at = _as_datetime(_o(m, "actual_datetime", None)) or _as_datetime(_o(m, "scheduled_datetime", None))
        ref = str(_o(m, "drug_id", "") or "") or str(_o(m, "drug_name", "") or "")
        if at is not None and ref:
            doses.append((at, ref))
    return sorted(doses, key=lambda dose: dose[0])


def _drug_name(ref: str, lang: str) -> str:
    return drug_display(ref, lang) or localize_drug_name(ref, lang)


def _drugs_given(ctx: NarrativeContext, lang: str) -> list[str]:
    """Distinct names of the drugs given during the stay: the drugs of the
    priority classes of ``death_course.yaml`` first, in class order, then the
    others; first given first within each."""
    priority = load_death_course().treatment_course.drug_class_priority
    refs: list[str] = []
    for _, ref in _given_doses(ctx):
        if ref not in refs:
            refs.append(ref)

    def rank(ref: str) -> int:
        classes = drug_classes(ref)
        return next((i for i, cls in enumerate(priority) if cls in classes), len(priority))

    names: list[str] = []
    for ref in sorted(refs, key=rank):  # stable: first given first within a rank
        name = _drug_name(ref, lang)
        if name and name not in names:
            names.append(name)
    return names


def _new_diagnoses(ctx: NarrativeContext, lang: str) -> list[str]:
    """The diagnoses that arose during the stay (``working_diagnoses``), named
    by their coded display with the hospital day of onset when recorded."""
    country = country_code(ctx.locale)
    items: list[str] = []
    for wd in ctx.working_diagnoses or []:
        code = working_diagnosis_code(str(_o(wd, "disease_id", "") or ""))
        if not code:
            continue
        _, display = diagnosis_coded(code, country, lang, _sex(ctx))
        onset_day = _o(wd, "onset_day", None)
        item = (
            t("dds_treatment_course.wk_item", lang, display=display, day=int(onset_day) + 1)
            if isinstance(onset_day, int)
            else display
        )
        if item not in items:
            items.append(item)
    return items


def _capped_list(names: list[str], cap: int, lang: str) -> str:
    """``names`` joined as a list; past ``cap`` names, "and N others"."""
    sep = t("list_sep.serial", lang)
    if len(names) <= cap:
        return sep.join(names)
    return t("dds_treatment_course.list_with_more", lang, list=sep.join(names[:cap]), count=len(names) - cap)


def _life_support_at_death(ctx: NarrativeContext) -> tuple[dict[str, list[str]], bool]:
    """The life support running in the final hours (``death_course.yaml``):
    the drugs given then per life-support class (first given first) and
    whether the patient was ventilated. Nothing without a death time."""
    death = _as_datetime(_o(ctx.encounter, "discharge_datetime", None))
    if death is None:
        return {}, False
    rules = load_death_course().life_support
    start = death - timedelta(hours=rules.window_hours)
    drugs: dict[str, list[str]] = {}
    for at, ref in _given_doses(ctx):
        if not start <= at <= death:
            continue
        classes = drug_classes(ref)
        if set(rules.excluded_drug_classes) & set(classes):
            continue
        cls = next((c for c in rules.drug_classes if c in classes), None)
        if cls is not None and ref not in drugs.setdefault(cls, []):
            drugs[cls].append(ref)

    def in_window(value: object) -> bool:
        at = _as_datetime(value)
        return at is not None and start <= at <= death

    ventilated = any(
        str(_o(v, "oxygen_delivery_device", "") or "") in rules.ventilation_devices
        and in_window(_o(v, "timestamp", None))
        for v in ctx.vitals or []
    ) or any(
        str(_o(p, "procedure_type", "") or "") in rules.ventilation_procedure_types
        and in_window(_o(p, "start_datetime", None))
        for p in ctx.procedures or []
    )
    return {cls: refs for cls, refs in drugs.items() if refs}, ventilated


def _life_support_phrases(ctx: NarrativeContext, lang: str) -> list[str]:
    """The life support at death in words ("vasopressor support
    (Norepinephrine)", "mechanical ventilation")."""
    drugs, ventilated = _life_support_at_death(ctx)
    sep = t("list_sep.serial", lang)
    phrases = [
        t(f"dds_circumstances_of_death.support_{cls}", lang, drugs=sep.join(_drug_name(r, lang) for r in refs))
        for cls, refs in drugs.items()
    ]
    if ventilated:
        phrases.append(t("dds_circumstances_of_death.support_ventilation", lang))
    return phrases


def _recorded_cpr(ctx: NarrativeContext) -> bool:
    """Whether a cardiopulmonary resuscitation is recorded: CIF procedures
    carry ``procedure_type`` and codes only (AD-30; Issue #3246), matched
    against ``death_course.yaml``."""
    rules = load_death_course().resuscitation
    for p in ctx.procedures or []:
        ptype = str(_o(p, "procedure_type", "") or "").lower()
        codes = {str(_o(p, key, "") or "") for key in ("procedure_code", "procedure_code_us", "procedure_code_jp")}
        if any(k in ptype for k in rules.procedure_type_keywords) or codes & set(rules.procedure_codes):
            return True
    return False


def _in_icu(ctx: NarrativeContext) -> bool:
    """Whether the record shows an ICU stay: an ICU transfer with its day, the
    same fields the FHIR Encounter ``classHistory`` ICU segment is written from
    (``encounter.py::_set_inpatient_histories``)."""
    return bool(ctx.icu_transferred) and ctx.icu_transferred_day >= 0


def _not_for_resuscitation(ctx: NarrativeContext) -> bool:
    return ctx.code_status in load_death_course().not_for_resuscitation_codes


def _palliative_death(ctx: NarrativeContext) -> bool:
    """A not-for-resuscitation death with no CPR and no life support in the
    final hours — the only death described as palliative bedside care."""
    if not _not_for_resuscitation(ctx) or _recorded_cpr(ctx):
        return False
    drugs, ventilated = _life_support_at_death(ctx)
    return not drugs and not ventilated


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
    adm_disp = ""
    if adm_code:
        # Issue #3259: the emitted code and its prose name.
        adm_code, adm_disp = diagnosis_coded(adm_code, country_code(ctx.locale), lang, _sex(ctx))
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

    Names what the record shows for the stay (Issue #3256): the drugs given
    (first given first), the procedures, the ICU transfer with its hospital
    day and the diagnoses that arose during the stay with theirs — names,
    not counts, each list capped by ``death_course.yaml`` with "and N
    others". A palliative death (``_palliative_death``) closes with the
    condition progressing, not with treatment continued.
    """
    lang = ctx.target_lang
    facts: list[str] = ["ctx.los_days"]
    caps = load_death_course().treatment_course
    los = ctx.los_days or 0
    hours = _hours_in_window(ctx)
    if hours is not None:
        # Issue #3537: a stay under the hours window is told in hours.
        facts.append("ctx.encounter.admission_datetime")
        parts = [
            t(
                "dds_treatment_course.los_part_hours_one" if hours == 1 else "dds_treatment_course.los_part_hours",
                lang,
                hours=hours,
            )
        ]
    elif los > 0:
        parts = [
            t(
                "dds_treatment_course.los_part_with_days_one"
                if los == 1
                else "dds_treatment_course.los_part_with_days",
                lang,
                los=los,
            )
        ]
    else:
        parts = [t("dds_treatment_course.los_part_admission", lang)]
    drugs = _drugs_given(ctx, lang)
    if drugs:
        facts.append("ctx.medications")
        parts.append(t("dds_treatment_course.med_part", lang, list=_capped_list(drugs, caps.max_named_drugs, lang)))
    procedures = procedure_names(ctx.procedures, lang)
    if procedures:
        facts.append("ctx.procedures")
        parts.append(
            t("dds_treatment_course.proc_part", lang, list=_capped_list(procedures, caps.max_named_procedures, lang))
        )
    if _in_icu(ctx):
        facts.append("ctx.icu_transferred_day")
        parts.append(t("dds_treatment_course.icu_part", lang, day=ctx.icu_transferred_day + 1))
    new_dx = _new_diagnoses(ctx, lang)
    if new_dx:
        facts.append("ctx.working_diagnoses")
        parts.append(t("dds_treatment_course.wk_part", lang, list=_capped_list(new_dx, caps.max_named_diagnoses, lang)))
    tail = "dds_treatment_course.tail_palliative" if _palliative_death(ctx) else "dds_treatment_course.tail"
    parts.append(t(tail, lang))
    return "".join(parts), facts


@section("terminal_course")
def build_dds_terminal_course(generator: TemplateNarrativeGenerator, ctx: NarrativeContext) -> tuple[str, list[str]]:
    """終末期経過 / Terminal course (final ~24-72 h).

    Anchors on the discharge (= death) datetime and describes the
    final hours with the mechanism of the certificate's immediate cause
    (Issue #3470; ``death_cause_chain.yaml`` ``terminal_mechanisms``) and
    the chain itself (immediate, due to, underlying), then the last full set
    of vitals recorded before death (Issue #2985) quoted as observations. A
    cause with no mechanism entry is keyed on disease pattern (chronic
    decompensation vs acute event); a record with no diagnosis falls back to
    the mechanism the last vitals show (Issue #2985). Without such vitals no
    values are quoted.
    """
    lang = ctx.target_lang
    facts: list[str] = []
    dis_dt = _o(ctx.encounter, "discharge_datetime", None)
    dis_str = str(dis_dt)[:16].replace("T", " ") if dis_dt else ""
    if dis_dt:
        facts.append("ctx.encounter.discharge_datetime")
    # Issue #3470: the mechanism and the cause named come from the cause
    # chain the certificate prints (one walk, ``_dc_cause_chain``); the last
    # vitals are quoted, and choose the mechanism only without a chain.
    chain = _dc_cause_chain(ctx)
    phrase_key, dx_part = _terminal_mechanism(chain, lang)
    if chain is not None:
        facts.extend(_chain_facts(chain))
    last = _last_recorded_vitals(ctx)
    if chain is None and last is not None:
        # No diagnosis on record: nothing to take the mechanism from.
        phrase_key = _terminal_phrase_key(last)
    if phrase_key is None:
        pattern = _dc_disease_pattern(chain.underlying.internal) if chain is not None else "unknown"
        phrase_key = {
            "acute": "dds_terminal_course.phrase_acute",
            "chronic": "dds_terminal_course.phrase_chronic",
        }.get(pattern, "dds_terminal_course.phrase_unknown")
    phrase = t(phrase_key, lang)
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

    From the record (Issue #3256): the code status when one is recorded,
    then the place of death (the ICU after an ICU transfer, else the ward)
    and the event — CPR when a resuscitation procedure is recorded; for a
    not-for-resuscitation patient, CPR withheld while the life support of
    the final hours ran, or palliative bedside care (看取り) without it;
    otherwise (full code, or no code status, and no CPR record) that death
    was confirmed, naming the life support, and for a full-code patient that
    no resuscitation is documented — the record holds no code event, so no
    arrest is asserted (Issue #3470). The rules are in ``death_course.yaml``.
    """
    lang = ctx.target_lang
    facts: list[str] = []
    if ctx.procedures:
        facts.append("ctx.procedures")
    place = t(
        "dds_circumstances_of_death.place_icu" if _in_icu(ctx) else "dds_circumstances_of_death.place_ward",
        lang,
    )
    facts.append("ctx.icu_transferred_day")
    support = _life_support_phrases(ctx, lang)
    if support:
        facts.append("ctx.medications")
    support_text = t("dds_circumstances_of_death.support_and", lang).join(support)
    if _recorded_cpr(ctx):
        key = "dds_circumstances_of_death.resuscitation"
    elif _not_for_resuscitation(ctx):
        key = "dds_circumstances_of_death.support_cpr_withheld" if support else "dds_circumstances_of_death.palliative"
    elif ctx.code_status:
        # Full code with no CPR record: the record holds no code event, so no
        # arrest or resuscitation is asserted (Issue #3470).
        key = (
            "dds_circumstances_of_death.support_full_code_no_cpr"
            if support
            else "dds_circumstances_of_death.full_code_no_cpr"
        )
    else:
        key = (
            "dds_circumstances_of_death.support_death_confirmed"
            if support
            else "dds_circumstances_of_death.death_confirmed"
        )
    event = t(key, lang, place=place, support=support_text)
    status = registry_display("snomed-ct", ctx.code_status, lang) if ctx.code_status else ""
    if not status:
        return event, facts
    facts.append("ctx.code_status")
    return t("dds_circumstances_of_death.code_status", lang, status=status) + event, facts


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
    cap = load_death_course().treatment_course.max_named_comorbidities
    country = country_code(ctx.locale)
    conds = _o(ctx.patient, "chronic_conditions", []) or [] if ctx.patient else []
    cond_labels: list[str] = []
    for c in conds:
        code_val = _o(c, "code", "") or (c if isinstance(c, str) else "")
        if not code_val:
            continue
        emit, disp = diagnosis_coded(code_val, country, lang, _sex(ctx))
        cond_labels.append(t("list_item.inline_dx_with_code", lang, display=disp, code=emit))
    if cond_labels:
        facts.append("ctx.patient.chronic_conditions")

    # Issue #3537: the secondary diagnoses recorded for the stay.
    secondary_labels: list[str] = []
    for code in secondary_diagnosis_codes(ctx.diagnoses):
        emit, disp = diagnosis_coded(code, country, lang, _sex(ctx))
        secondary_labels.append(t("list_item.inline_dx_with_code", lang, display=disp, code=emit))
    if secondary_labels:
        facts.append("ctx.diagnoses[0].secondary_diagnosis_codes")

    comp_tokens = list(getattr(ctx, "complications_occurred", []) or [])
    if comp_tokens:
        facts.append("ctx.complications_occurred")

    if not cond_labels and not comp_tokens and not secondary_labels:
        return t("death_cert.comorbidities_none", lang), facts

    parts: list[str] = []
    if cond_labels:
        parts.append(
            t("dds_complications_and_comorbidities.chronic_part", lang, list=_capped_list(cond_labels, cap, lang))
        )
    if secondary_labels:
        parts.append(
            t(
                "dds_complications_and_comorbidities.secondary_part",
                lang,
                list=_capped_list(secondary_labels, cap, lang),
            )
        )
    if comp_tokens:
        # Phase 1d-72: route through _localize_complication so JA
        # resolves ``hypokalemia`` → 低カリウム血症 etc. and EN keeps
        # canonical casing. Sibling fix to build_dc_contributing_conditions.
        comp_labels = [_localize_complication(str(tok), lang) for tok in comp_tokens]
        parts.append(
            t("dds_complications_and_comorbidities.in_hospital_part", lang, list=_capped_list(comp_labels, cap, lang))
        )
    # JA joins parts with "。" (list_sep.period) + trailing period;
    # EN joins with ". " (list_sep.period_space) + trailing period.
    body = t("list_sep.period_space", lang).join(parts) + t("list_sep.period", lang)
    return t("dds_complications_and_comorbidities.head", lang, body=body), facts


@section("family_communication")
def build_dds_family_communication(
    generator: TemplateNarrativeGenerator, ctx: NarrativeContext
) -> tuple[str, list[str]]:
    """家族への説明経過 / Family communication timeline.

    clinosim's CIF does not model family-communication events (no dedicated
    Encounter subtype or Communication resource), so the template states only
    what the length of stay supports — how the family was kept informed
    (short admission = explained from admission / long admission = at each
    deterioration) — and not who was present at the death (Issue #3470: no
    record shows it).
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
    The summary is written at the time of death and clinosim does not model
    pathological findings, so an autopsy is stated as planned with the
    findings to follow (Issue #3405), never as a result.
    """
    lang = ctx.target_lang
    facts: list[str] = ["encounter.id::autopsy_sample"]
    performed = _autopsy_performed_sha256(ctx)
    if performed:
        return t("autopsy.findings_yes", lang), facts
    return t("autopsy.findings_no", lang), facts
