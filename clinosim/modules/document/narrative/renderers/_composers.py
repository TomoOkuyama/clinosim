"""Shared composer cluster — stateful narrative composers that back
multiple section builders and the progress-note renderer.

Extracted from ``template_generator.TemplateNarrativeGenerator`` as step
C1q of the full-review Phase C renderer split (CRITICAL C1). Behavior is
byte-identical — the eight class methods are now thin delegators.

The composers depend only on ``ctx`` and module-level helpers from
``_narrative_utils`` / ``_template_helpers`` / ``locale``; no helper in
this cluster dispatches back to the class, so there is no ``generator``
threading here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clinosim.countries import has_authored_narrative
from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._as_of import recorded_by
from clinosim.modules.document.narrative._localization import (
    _localize_complication,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _cc_altered_consciousness_keywords,
    _cc_keyword_positively_present,
    _cc_severe_dyspnea_keywords,
    _filter_vitals_for_day,
    _pe_altered_consciousness_pool_ja,
    _pe_consciousness_pool_by_avpu_ja,
    _pe_severe_dyspnea_pool_ja,
    _pick_from_pool_by_encounter,
    _rewrite_pe_clause,
    encounter_died,
    is_neonate,
)
from clinosim.modules.document.narrative._progress_symptoms import respiratory_symptom_line
from clinosim.modules.document.narrative._vitals_line import (
    PHYSICAL_EXAM,
    PROGRESS_DAY,
    PROGRESS_OBJECTIVE,
    format_vitals_line,
    latest_vitals_set,
)
from clinosim.modules.document.narrative.renderers._shared_helpers import procedure_names
from clinosim.timeutil import parse_iso_datetime

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext


def compose_progress_subjective_from_state(ctx: NarrativeContext) -> str:
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
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import progress_vitals_rules

    lang = ctx.target_lang
    # Issue #3235: the readings of the note's period and of the previous
    # period, compared by their extremes (never by single readings).
    picks = _note_period_vitals(ctx)
    prev = _note_period_vitals(ctx, previous=True)
    parts: list[str] = []
    los = ctx.los_days or 0
    day_1indexed = ctx.day_index + 1
    if los > 0:
        parts.append(t("progress.hospital_day", lang, day=day_1indexed))

    trend = progress_vitals_rules().trend
    abnormal_added = False
    tmax, tmin = _extreme(picks, "temperature_celsius", max), _extreme(picks, "temperature_celsius", min)
    spo2_min = _extreme(picks, "spo2", min)
    prev_tmax, prev_spo2 = _extreme(prev, "temperature_celsius", max), _extreme(prev, "spo2", min)

    # Issue #3401: a trend word states the patient's present condition, so it
    # is written only when the latest reading of the period is itself beyond
    # the threshold, with that reading and the period's peak; a peak the latest
    # reading no longer shows is stated time-qualified.
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules
    from clinosim.modules.document.narrative._progress_exam import spo2_low_override

    when = (
        t("progress.period_recent", lang, hours=notable_lab_rules().window_hours)
        if getattr(ctx, "authored_datetime", None) is not None
        else t("progress.period_today", lang)
    )
    cur_t, cur_spo2 = _latest(picks, "temperature_celsius"), _latest(picks, "spo2")
    # Issue #3541: new / persistent is the finding's one state, the same the
    # Assessment's course line reads.
    from clinosim.modules.document.narrative._progress_state import finding_states

    states = finding_states(ctx, picks, prev) if picks else {}
    spo2_floor = spo2_low_override(ctx)
    spo2_below = trend.spo2_desaturation_below if spo2_floor is None else spo2_floor
    spo2_recovered = trend.spo2_recovered_at_least if spo2_floor is None else spo2_floor

    if tmax is not None and tmax >= trend.fever_c:
        now_t = tmax if cur_t is None else cur_t
        if now_t < trend.fever_c:
            parts.append(t("progress.fever_peak_resolved", lang, tmax=tmax, t=now_t, when=when))
        else:
            peak = t("progress.fever_peak", lang, tmax=tmax, when=when) if round(tmax, 1) != round(now_t, 1) else ""
            if states.get(("temperature_celsius", "high")) == "new":
                parts.append(t("progress.fever_new_onset", lang, t=now_t, peak=peak))
            elif prev_tmax is not None and now_t > prev_tmax + trend.fever_rise_c:
                parts.append(t("progress.fever_worsening", lang, t=now_t, peak=peak))
            else:
                parts.append(t("progress.fever_persistent", lang, t=now_t, peak=peak))
        abnormal_added = True
    elif tmin is not None and tmin < trend.hypothermia_below_c:
        # Issue #3453: the core-temperature definition, on the latest reading;
        # a lower minimum earlier in the period is time-qualified.
        now_t = tmin if cur_t is None else cur_t
        if now_t >= trend.hypothermia_below_c:
            parts.append(t("progress.hypothermia_transient_low", lang, tmin=tmin, t=now_t, when=when))
        else:
            peak = (
                t("progress.hypothermia_peak", lang, tmin=tmin, when=when) if round(tmin, 1) != round(now_t, 1) else ""
            )
            parts.append(t("progress.hypothermia", lang, t=now_t, peak=peak))
        abnormal_added = True
    elif (
        prev_tmax is not None
        and prev_tmax >= trend.fever_c
        and tmax is not None
        and tmax < trend.fever_resolved_below_c
    ):
        parts.append(t("progress.fever_resolving", lang, pt=prev_tmax, t=tmax))
        abnormal_added = True

    if spo2_min is not None and spo2_min < spo2_below:
        now_s = spo2_min if cur_spo2 is None else cur_spo2
        if now_s >= spo2_below:
            parts.append(t("progress.spo2_transient_low", lang, smin=spo2_min, s=now_s, when=when))
        else:
            peak = t("progress.spo2_peak", lang, smin=spo2_min, when=when) if round(now_s) != round(spo2_min) else ""
            key = (
                "progress.spo2_worsening"
                if prev_spo2 is not None and now_s < prev_spo2 - trend.spo2_drop
                else "progress.spo2_desaturating"
            )
            parts.append(t(key, lang, s=now_s, peak=peak))
        abnormal_added = True
    elif prev_spo2 is not None and prev_spo2 < spo2_below and spo2_min is not None and spo2_min >= spo2_recovered:
        parts.append(t("progress.spo2_recovering", lang, ps=prev_spo2, s=spo2_min))
        abnormal_added = True

    symptom_parts = _progress_symptom_phrases(ctx, picks, prev, lang, when, states)
    parts.extend(symptom_parts)
    abnormal_added = abnormal_added or bool(symptom_parts)

    if is_neonate(ctx):
        # Issue #3260: a newborn's day is described by feeding, voiding and
        # stooling and the jaundice of the bilirubin measured so far, not by
        # the adult stable-day pool.
        parts.extend(_newborn_subjective_parts(ctx))
    elif not abnormal_added:
        phrase = pick_stable_progress_phrase(ctx, lang=lang)
        parts.append(phrase)
    return t("list_sep.chunk", lang).join(parts)


def _newborn_subjective_parts(ctx: NarrativeContext) -> list[str]:
    """The newborn progress-note subjective sentences (Issue #3260): the day of
    life, the well-newborn feeding and elimination line, and the latest total
    bilirubin measured by the note's time. Feeding and elimination are not
    recorded in the simulation record; for a stay without complications they
    are the neutral well-newborn observation, as the adult stable-day pool is
    for an adult."""
    from clinosim.modules.document.narrative.renderers._resolvers import latest_bilirubin_at

    lang = ctx.target_lang
    parts = [t("neonate_progress.day_of_life", lang, day=ctx.day_index)]
    if not getattr(ctx, "complications_events", None):
        parts.append(t("neonate_progress.feeding_elimination", lang))
    latest = latest_bilirubin_at(ctx, ctx.day_index)
    if latest is not None:
        day, value = latest
        if day is None:
            key = "neonate_progress.bilirubin"
        elif day < ctx.day_index:
            # No measurement since: the earlier value is the last one, not today's (Issue #3564).
            key = "neonate_progress.bilirubin_last"
        else:
            key = "neonate_progress.bilirubin_dated"
        parts.append(t(key, lang, v=value, day=day))
    return parts


def _note_period_vitals(ctx: NarrativeContext, *, previous: bool = False) -> list:
    """The vital-sign readings of a daily note's period, oldest first
    (Issues #3235, #3247): with an authored time, those of the
    ``notable_labs.yaml`` ``window_hours`` up to it (the period since the
    previous day's note — the window the note's labs and drugs use); without
    one, those of the note's hospital day. ``previous``: the period before."""
    from datetime import timedelta

    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    as_of = getattr(ctx, "authored_datetime", None)
    vitals = getattr(ctx, "vitals", None) or []
    if as_of is None:
        day = ctx.day_index - 1 if previous else ctx.day_index
        return _filter_vitals_for_day(vitals, day, getattr(ctx, "encounter", None)) if day >= 0 else []
    window = timedelta(hours=notable_lab_rules().window_hours)
    end = as_of - window if previous else as_of
    timed = []
    for i, v in enumerate(vitals):
        when = parse_iso_datetime(_o(v, "timestamp", None), lenient=True)
        if when is not None and end - window < when <= end:
            timed.append((when, i, v))
    timed.sort(key=lambda x: (x[0], x[1]))
    return [v for _, _, v in timed]


def _latest(readings: list, attr: str) -> float | None:
    """The latest recorded value of ``attr`` over ``readings`` (oldest first);
    ``None`` when no reading records it."""
    for r in reversed(readings):
        x = _o(r, attr, None)
        if x is not None:
            return float(x)
    return None


def _extreme(readings: list, attr: str, pick: Any) -> float | None:
    """``pick`` (``max`` / ``min``) of ``attr`` over ``readings``; ``None``
    when no reading records it."""
    values = [float(x) for x in (_o(r, attr, None) for r in readings) if x is not None]
    return pick(values) if values else None


_AVPU_ORDER = {"A": 0, "V": 1, "P": 2, "U": 3}
_SUBJ_PAIN_NOTABLE = 4
_SUBJ_PAIN_CHANGE = 2
_SUBJ_WITHDRAWAL_HR = 100


def _progress_symptom_phrases(
    ctx: NarrativeContext,
    today: list,
    prev: list,
    lang: str,
    when: str,
    states: dict[tuple[str, str], str] | None = None,
) -> list[str]:
    """Pain trend, consciousness change and withdrawal symptoms from the
    recorded vitals of today vs the previous day (Issue #2095). Consciousness
    is stated on the latest AVPU of each period, the one the Assessment's
    course line judges, with a worse level earlier in the period
    time-qualified (Issue #3455); new vs persistent is the finding's state
    shared with the Assessment (Issue #3541), and the pain score quoted is the
    latest charted one, the reading the nursing record of the period carries."""
    out: list[str] = []

    def _max(rows: list, key: str) -> int | None:
        vals = [int(x) for x in (_o(r, key, None) for r in rows) if x is not None]
        return max(vals) if vals else None

    def _latest_avpu(rows: list) -> str:
        for r in reversed(rows):
            level = str(_o(r, "consciousness_level", "") or "")
            if level in _AVPU_ORDER:
                return level
        return ""

    def _worst_avpu(rows: list) -> str:
        levels = [str(_o(r, "consciousness_level", "") or "") for r in rows]
        levels = [lv for lv in levels if lv in _AVPU_ORDER]
        return max(levels, key=_AVPU_ORDER.__getitem__) if levels else ""

    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import progress_vitals_rules

    rules = progress_vitals_rules()
    # Issue #3454: how breathing is going, for a respiratory admission, leads
    # the symptoms.
    resp = respiratory_symptom_line(ctx, today, prev)
    if resp:
        out.append(resp)
    avpu, prev_avpu = _latest_avpu(today), _latest_avpu(prev)
    worst = _worst_avpu(today)
    # Issue #3235: a self-reported score only while the patient can give one
    # (no behavioural pain scale is recorded), named by the disease's pain.
    cur_pain, before_pain = _latest(today, "pain_score"), _latest(prev, "pain_score")
    pain = None if cur_pain is None else int(cur_pain)
    prev_pain = None if before_pain is None else int(before_pain)
    # Issue #3454: a pain score is stated only for a pain with a source (the
    # disease's pain site, a site the chief complaint names, or an operation /
    # procedure done by the note's time), never as a bare "pain".
    label = _pain_label(ctx, rules, lang) if pain is not None else ""
    if pain is not None and label:
        if not avpu or avpu in rules.self_report_avpu:
            if prev_pain is not None and prev_pain >= _SUBJ_PAIN_NOTABLE and pain < _SUBJ_PAIN_NOTABLE:
                out.append(t("progress.pain_controlled", lang, pain=label, p=prev_pain, q=pain))
            elif pain >= _SUBJ_PAIN_NOTABLE:
                if prev_pain is not None and pain <= prev_pain - _SUBJ_PAIN_CHANGE:
                    out.append(t("progress.pain_improving", lang, pain=label, p=prev_pain, q=pain))
                elif prev_pain is not None and pain >= prev_pain + _SUBJ_PAIN_CHANGE:
                    out.append(t("progress.pain_worsening", lang, pain=label, p=prev_pain, q=pain))
                else:
                    out.append(t("progress.pain_persistent", lang, pain=label, q=pain))
        elif pain >= _SUBJ_PAIN_NOTABLE:
            # Issue #3235: the patient cannot self-report; no scale score is
            # recorded, so none is stated.
            out.append(t("progress.pain_not_self_reportable", lang, pain=label))

    if avpu and avpu != "A":
        state = (states or {}).get(("consciousness", "high"))
        persistent = state == "persisting" if state else bool(prev_avpu and prev_avpu != "A")
        key = "progress.confusion_persistent" if persistent else "progress.confusion_new"
        peak = t("progress.consciousness_peak", lang, w=worst, when=when) if worst != avpu else ""
        out.append(t(key, lang, a=avpu, peak=peak))
    elif avpu == "A" and prev_avpu and prev_avpu != "A":
        out.append(t("progress.consciousness_improved", lang, a=prev_avpu))
    elif avpu == "A" and worst != "A":
        out.append(t("progress.consciousness_transient_low", lang, w=worst, when=when))

    disease_id = getattr(getattr(ctx, "disease_protocol", None), "disease_id", "") or ""
    if disease_id == "alcohol_withdrawal":
        hr, prev_hr = _max(today, "heart_rate"), _max(prev, "heart_rate")
        if hr is not None and hr > _SUBJ_WITHDRAWAL_HR:
            out.append(t("progress.withdrawal_active", lang, hr=hr))
        elif hr is not None and prev_hr is not None and prev_hr > _SUBJ_WITHDRAWAL_HR:
            out.append(t("progress.withdrawal_settling", lang, hr=hr))
    return out


def _pain_label(ctx: NarrativeContext, rules: Any, lang: str) -> str:
    """The pain a progress note names (Issue #3235): the disease's pain site,
    else the site the admission chief complaint names, else "pain" after an
    operation or procedure (Issue #3454); ``""`` for a pain with no source."""
    from clinosim.locale.loader import resolve_localized_display
    from clinosim.locale.localized import normalize_lang

    disease_id = getattr(getattr(ctx, "disease_protocol", None), "disease_id", "") or ""
    site = rules.pain_sites.get(disease_id)
    if site:
        label = resolve_localized_display(site, lang, fallback="")
        if label:
            return label
    code = normalize_lang(lang)
    enc = getattr(ctx, "encounter", None)
    complaints = {
        "ja": str(_o(enc, "chief_complaint_ja", "") or ""),
        "en": str(_o(enc, "chief_complaint", "") or ""),
    }
    complaint = complaints.get(code) or complaints["en"]
    for entry in rules.complaint_pain_sites:
        terms = entry.terms.get(code) or entry.terms["en"]
        if any(term.lower() in complaint.lower() for term in terms):
            return entry.site.get(code) or entry.site["en"]
    from clinosim.modules.document.narrative._progress_course import post_procedure_line

    return t("progress.pain_generic", lang) if post_procedure_line(ctx, getattr(ctx, "authored_datetime", None)) else ""


def pick_stable_progress_phrase(ctx: NarrativeContext, *, lang: str) -> str:
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
    if phase in ("late", "eve") and encounter_died(ctx.encounter):
        # Issue #2875: no discharge preparation in the last days of a stay
        # that ended in death.
        phase = "terminal"

    pool_data = load_inpatient_subjective_pool()
    pool = pool_data.get(phase) or pool_data.get("mid") or []
    if not pool:
        return ""
    idx = (ctx.day_index or 0) % len(pool)
    return resolve_localized_display(pool[idx], lang, fallback="")


def _complications_known_on_day(
    ctx: NarrativeContext, as_of: Any
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    """The stay's complications a note of hospital day ``ctx.day_index``
    knows (Issue #3229), as (new, ongoing) lists of ``(name, onset_day)`` in
    onset order (Issue #3247: the note names the day of onset). A
    complication counts from its ``onset_day``, and only once its
    ``onset_datetime`` is at or before ``as_of`` (the authored time). It is
    new when it began since the previous day's note (within the notes'
    ``window_hours`` before ``as_of``; without both times, on its onset
    day), ongoing afterwards. An entry without an onset day cannot be placed
    on the note's clock and is left out (``NarrativeContext.complications_events``)."""
    from datetime import timedelta

    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules

    new: list[tuple[str, int]] = []
    ongoing: list[tuple[str, int]] = []
    seen: set[str] = set()
    for event in list(getattr(ctx, "complications_events", []) or []):
        name = str(_o(event, "name", "") or "")
        onset_day = _o(event, "onset_day", None)
        if not name or onset_day is None or int(onset_day) > ctx.day_index or name in seen:
            continue
        onset_at = parse_iso_datetime(_o(event, "onset_datetime", None), lenient=True)
        if as_of is not None and onset_at is not None:
            if onset_at > as_of:
                continue
            is_new = onset_at > as_of - timedelta(hours=notable_lab_rules().window_hours)
        else:
            is_new = int(onset_day) == ctx.day_index
        seen.add(name)
        (new if is_new else ongoing).append((name, int(onset_day)))
    return new, ongoing


def compose_progress_assessment_from_state(ctx: NarrativeContext) -> str:
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
    sep = t("list_sep.serial", lang)
    parts: list[str] = []
    as_of = getattr(ctx, "authored_datetime", None)
    # Issue #3247: the post-operative day, the complications with their day of
    # onset, and how the course changed from the previous period.
    from clinosim.modules.document.narrative._progress_course import lab_course_lines, post_procedure_line

    post_op = post_procedure_line(ctx, as_of)
    if post_op:
        parts.append(post_op)
    new_comps, ongoing_comps = _complications_known_on_day(ctx, as_of)

    def with_onset(comps: list[tuple[str, int]]) -> list[str]:
        return [
            t("progress.complication_with_onset", lang, name=_localize_complication(name, lang), day=onset_day + 1)
            for name, onset_day in comps[:3]
        ]

    if new_comps:
        # Issue #3542: "management started" only with an order for it.
        from clinosim.modules.document.narrative._progress_course import complication_order_exists

        onsets = {
            str(_o(e, "name", "") or ""): parse_iso_datetime(_o(e, "onset_datetime", None), lenient=True)
            for e in list(getattr(ctx, "complications_events", []) or [])
        }
        managed = [c for c in new_comps if complication_order_exists(ctx, c[1], onsets.get(c[0]), as_of)]
        unmanaged = [c for c in new_comps if c not in managed]
        if managed:
            parts.append(t("progress.complication_new", lang, list=sep.join(with_onset(managed))))
        if unmanaged:
            parts.append(t("progress.complication_new_unmanaged", lang, list=sep.join(with_onset(unmanaged))))
    if ongoing_comps:
        parts.append(t("progress.complications_noted", lang, list=sep.join(with_onset(ongoing_comps))))
    from clinosim.modules.document.narrative._progress_exam import course_line

    course = course_line(ctx, _note_period_vitals(ctx), _note_period_vitals(ctx, previous=True), lang)
    if course:
        parts.append(course)
    # Issue #3471: a level of consciousness that stays below Alert is named
    # as a problem with its cause work-up (delirium as a differential).
    from clinosim.modules.document.narrative._progress_exam import consciousness_assessment_line

    encounter = getattr(ctx, "encounter", None)
    all_vitals = getattr(ctx, "vitals", None) or []
    daily = [_note_period_vitals(ctx)] + [
        _filter_vitals_for_day(all_vitals, d, encounter) for d in range(ctx.day_index - 1, -1, -1)
    ]
    consciousness = consciousness_assessment_line(daily, [n for n, _ in new_comps + ongoing_comps], lang)
    if consciousness:
        parts.append(consciousness)
    parts.extend(lab_course_lines(ctx, as_of))
    # Issues #3230 / #3241: the day's flagged results known at the note's
    # authored time, ranked and one per analyte (lab_timeseries.select_notable_labs).
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import notable_lab_rules
    from clinosim.modules.document.narrative._notable_labs import notable_lab_entries

    rules = notable_lab_rules()
    _lab_enc = getattr(ctx, "encounter", None)
    labs = notable_lab_entries(
        list(ctx.lab_results or []),
        _o(_lab_enc, "admission_datetime", None) if _lab_enc is not None else None,
        ctx.day_index,
        lang,
        limit=rules.max_items.note,
        as_of=as_of,
    )
    if labs and as_of is not None:
        parts.append(t("progress.notable_labs_recent", lang, list=sep.join(labs), hours=rules.window_hours))
    elif labs:
        parts.append(t("progress.notable_labs", lang, list=sep.join(labs)))
    screening = newborn_screening_to_date(ctx)
    if screening:
        parts.append(t("progress.newborn_screening", lang, list=screening))
    if not parts:
        parts.append(t("progress.stable_course_assessment", ctx.target_lang))
    return t("list_sep.chunk", lang).join(parts)


def newborn_screening_to_date(ctx: NarrativeContext, *, with_bilirubin: bool = False) -> str:
    """The newborn screening results, measurements and prophylaxis recorded by
    the note's authored time (Issue #3245; the H&P cites none of them),
    ``""`` for a patient who is not a newborn or has none yet. The bilirubin is
    left out unless ``with_bilirubin`` (a progress note states it in its own
    sentence; the discharge summary states the last measurement here)."""
    from clinosim.modules.document.narrative._replacement_renderers import _render_newborn_workup_summary
    from clinosim.modules.document.narrative.context import newborn_workup_known_at

    workup = getattr(ctx, "newborn_workup", None) or {}
    if not workup.get("is_neonate"):
        return ""
    known = newborn_workup_known_at(workup, getattr(ctx, "authored_datetime", None))
    return _render_newborn_workup_summary(known, lang=ctx.target_lang, screening_only=True, bilirubin=with_bilirubin)


def compose_progress_held_line(ctx: NarrativeContext) -> str:
    """The plan line naming today's held drugs ("Held: ..."), or ``""`` — for
    an authored daily-trajectory plan, which lists no drugs (Issue #2981)."""
    from clinosim.modules.document.narrative._medication_plan import cap_names, note_medications

    held = note_medications(ctx).held
    return t("progress.meds_held", ctx.target_lang, list=cap_names(held, ctx.target_lang)) if held else ""


def compose_progress_plan_from_state(ctx: NarrativeContext) -> str:
    """Inpatient progress_note Plan from CIF facts: the drugs of the note's
    period — started, continued, given once, held and stopped, each ranked
    by clinical priority (Issue #3247, ``_medication_plan.note_medications``)
    — and today's procedures."""
    from clinosim.modules.document.narrative._medication_plan import cap_names, note_medications

    lang = ctx.target_lang
    parts: list[str] = []
    meds = note_medications(ctx)
    for key, names in (
        ("progress.meds_started", meds.started),
        ("progress.meds_continue", meds.continued),
        ("progress.meds_given_once", meds.given_once),
        ("progress.meds_held", meds.held),
        ("progress.meds_resumed", meds.resumed),
        ("progress.meds_stopped", meds.stopped),
    ):
        if names:
            parts.append(t(key, lang, list=cap_names(names, lang)))
    # Today's procedures only, named from their codes (Issue #3246).
    # Done by the authored time; a later one the same day is planned (Issue #3468).
    _proc_kw: dict[str, Any] = {
        "admission": _o(getattr(ctx, "encounter", None), "admission_datetime", None),
        "day": ctx.day_index,
        "as_of": getattr(ctx, "authored_datetime", None),
    }
    procs = procedure_names(ctx.procedures, lang, **_proc_kw)[:4]
    if procs:
        sep = t("list_sep.serial", lang)
        parts.append(t("progress.procs_today", lang, list=sep.join(procs)))
    planned_procs = procedure_names(ctx.procedures, lang, later=True, **_proc_kw)[:4]
    if planned_procs:
        sep = t("list_sep.serial", lang)
        parts.append(t("progress.procs_planned_later", lang, list=sep.join(planned_procs)))
    # Issue #3247: diet, rehabilitation and the discharge arrangement.
    from clinosim.modules.document.narrative._progress_course import (
        diet_line,
        discharge_planning_line,
        rehab_line,
    )

    as_of = getattr(ctx, "authored_datetime", None)
    for line in (diet_line(ctx, as_of), rehab_line(ctx, as_of), discharge_planning_line(ctx)):
        if line:
            parts.append(line)
    if not parts:
        parts.append(t("progress.observation_fallback", lang))
    return t("list_sep.chunk", lang).join(parts)


def compose_today_vitals_line(ctx: NarrativeContext) -> str:
    """The vital signs of an inpatient progress note's Objective (Issues
    #3235, #3247), from all readings of the note's period
    (:func:`_note_period_vitals`): the latest recorded value of each vital,
    SpO2 with its oxygen therapy (device and flow) or room air, "weaned off
    O2" when an earlier reading of the period was on oxygen, then the
    period's extreme values beyond the ``progress_vitals.yaml`` limits that
    differ from the latest value ("Tmax 38.8°C"). A period without a reading
    says so (never another period's reading)."""
    from clinosim.modules.document.narrative._narrative_interpretation_thresholds import (
        notable_lab_rules,
        progress_vitals_rules,
    )

    lang = ctx.target_lang
    readings = _note_period_vitals(ctx)
    timed = getattr(ctx, "authored_datetime", None) is not None
    hours = notable_lab_rules().window_hours
    if not readings:
        return t("progress.vitals_none_recent" if timed else "progress.vitals_none_today", lang, hours=hours)
    latest = latest_vitals_set(readings)
    bits = [format_vitals_line(latest, PROGRESS_DAY, lang)]
    if not latest.get("on_supplemental_oxygen") and any(_o(r, "on_supplemental_oxygen", False) for r in readings):
        bits.append(t("progress.vitals_o2_weaned", lang))
    line = PROGRESS_DAY.separator.join(b for b in bits if b)

    shown: list[str] = []
    for rule in progress_vitals_rules().extremes:
        value = _extreme(readings, rule.vital, max if rule.side == "max" else min)
        if value is None or value == latest.get(rule.vital):
            continue
        limit = _vital_limit(ctx, rule.vital, rule.side, rule.limit, rule.child_low)
        beyond = value > limit if rule.side == "max" else value < limit
        if beyond or (rule.inclusive and value == limit):
            shown.append(t(f"progress.vital_extreme.{rule.vital}_{rule.side}", lang, v=value))
    if shown:
        key = "progress.vitals_extremes_recent" if timed else "progress.vitals_extremes_today"
        extremes = t(key, lang, hours=hours, list=t("list_sep.serial", lang).join(shown))
        line = f"{line} {extremes}" if line else extremes
    return line


def _vital_limit(ctx: NarrativeContext, vital: str, side: str, adult: float, child_low: str = "low") -> float:
    """The limit of ``vital`` on ``side`` for the patient: the age-banded
    pediatric range where it lists the vital, else the adult ``limit``. The
    temperature limit (fever) is the same at any age."""
    from clinosim.modules.observation.pediatric_ranges import age_in_completed_months, pediatric_vital_range

    if vital == "temperature_celsius":
        return adult
    as_of = getattr(ctx, "authored_datetime", None) or _o(getattr(ctx, "encounter", None), "admission_datetime", None)
    months = age_in_completed_months(_o(getattr(ctx, "patient", None), "date_of_birth", None), as_of)
    child = pediatric_vital_range(vital, months)
    if child is None:
        return adult
    if side == "max":
        return child.high
    from clinosim.modules.document.narrative._progress_exam import child_low_bound

    return child_low_bound(child, child_low)


def pe_vitals_reading(ctx: NarrativeContext) -> Any | None:
    """The vital-sign record the physical-examination vitals line quotes: the
    first reading of the note's day taken by its authored time (Issue #3241),
    else the earliest reading taken by then; ``None`` when there is none."""
    vitals = recorded_by(list(ctx.vitals or []), getattr(ctx, "authored_datetime", None))
    if not vitals:
        return None
    picks = _filter_vitals_for_day(vitals, ctx.day_index, ctx.encounter)
    if not picks:
        picks = [vitals[0]]
    return picks[0]


def compose_pe_vitals_line(ctx: NarrativeContext) -> str:
    """Compose a JA vital-signs prose line for the physical_examination
    section (Issue #979).

    Picks the day using ``ctx.day_index`` (set per-stub by
    ``passes.NarrativePass._stub_day_index``, so admission_hp → day 0,
    discharge_summary → LOS-1, progress_note → per-day) and resolves
    vitals via ``_filter_vitals_for_day`` (which handles the CIF
    ``timestamp`` vs ``day`` divergence — see helper docstring).

    Only readings taken by the note's authored time count (Issue #3241); if
    the target day has none of them, the encounter's earliest reading taken
    by then is quoted. Returns "" when no reading existed at the authored time.

    Format matches real JP acute-care admission notes:
        "BP 130/80 mmHg, HR 88/min, T 37.5°C, SpO2 96% (RA), RR 20/min"
    """
    reading = pe_vitals_reading(ctx)
    if reading is None:
        return ""
    return format_vitals_line(reading, PHYSICAL_EXAM, ctx.target_lang)


def apply_cc_pe_consistency(
    text: str, ctx: NarrativeContext, *, use_chief_complaint: bool = True
) -> tuple[str, list[str]]:
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
    rewrite fires, ``text`` is returned unchanged. ``use_chief_complaint=False``
    applies the AVPU rewrite only (a daily note's exam follows the day's
    readings, not the admission complaint; Issue #3235).
    """
    facts: list[str] = []
    if not text or not has_authored_narrative(ctx.target_lang):
        return text, facts

    enc = ctx.encounter
    if enc is None:
        return text, facts
    enc_id = _o(enc, "encounter_id", "") or ""

    # Issue #2086: the consciousness clause must agree with the day's recorded
    # AVPU (worst of the day), independent of the chief complaint.
    day_avpu = {
        str(_o(v, "consciousness_level", "") or "")
        for v in _filter_vitals_for_day(list(getattr(ctx, "vitals", None) or []), ctx.day_index, enc)
    }
    worst = next((lvl for lvl in ("U", "P", "V") if lvl in day_avpu), "")
    if worst:
        pool = _pe_consciousness_pool_by_avpu_ja(worst)
        if pool:
            new_text = _rewrite_pe_clause(text, ("意識清明",), _pick_from_pool_by_encounter(pool, enc_id, "pe_avpu"))
            if new_text != text:
                facts.append("ctx.vitals.consciousness_level:pe_consciousness")
                text = new_text

    cc = _o(enc, "chief_complaint_ja", None) or _o(enc, "chief_complaint", None) or ""
    cc = str(cc)
    if not cc or not use_chief_complaint:
        return text, facts

    if _cc_keyword_positively_present(cc, _cc_altered_consciousness_keywords()):
        replacement = _pick_from_pool_by_encounter(_pe_altered_consciousness_pool_ja(), enc_id, "pe_consciousness")
        new_text = _rewrite_pe_clause(text, ("意識清明",), replacement)
        if new_text != text:
            facts.append("encounter.chief_complaint:pe_consciousness")
            text = new_text

    if _cc_keyword_positively_present(cc, _cc_severe_dyspnea_keywords()):
        replacement = _pick_from_pool_by_encounter(_pe_severe_dyspnea_pool_ja(), enc_id, "pe_respiratory")
        new_text = _rewrite_pe_clause(text, ("呼吸音清明",), replacement)
        if new_text != text:
            facts.append("encounter.chief_complaint:pe_respiratory")
            text = new_text

    return text, facts


def compose_vital_signs_line(ctx: NarrativeContext) -> str:
    """Compose a single-line JA/EN vital-signs summary from ctx.vitals[0]
    (encounter has 1 outpatient vitals record per visit — see outpatient.py
    line 162+). Returns "" when no vitals are recorded.
    """
    vitals = list(ctx.vitals or [])
    if not vitals:
        return ""
    return format_vitals_line(vitals[0], PROGRESS_OBJECTIVE, ctx.target_lang)
