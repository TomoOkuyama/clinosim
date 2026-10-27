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

from typing import TYPE_CHECKING

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._localization import (
    _format_lab_unit_for_prose,
    _localize_complication,
    _localize_lab_flag,
    _localize_lab_name,
)
from clinosim.modules.document.narrative._narrative_utils import (
    _cc_altered_consciousness_keywords,
    _cc_keyword_positively_present,
    _cc_severe_dyspnea_keywords,
    _filter_vitals_for_day,
    _parse_iso_datetime,
    _pe_altered_consciousness_pool_ja,
    _pe_consciousness_pool_by_avpu_ja,
    _pe_severe_dyspnea_pool_ja,
    _pick_from_pool_by_encounter,
    _rewrite_pe_clause,
)

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

        prev_temp = float(_o(prev[0], "temperature_celsius", None) or 0.0) if prev else 0.0
        prev_spo2 = float(_o(prev[0], "spo2", None) or 0.0) if prev else 0.0

        if temp_f is not None and temp_f >= 38.0:
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
        phrase = pick_stable_progress_phrase(ctx, lang=lang)
        parts.append(phrase)
    return t("list_sep.chunk", lang).join(parts)


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

    pool_data = load_inpatient_subjective_pool()
    pool = pool_data.get(phase) or pool_data.get("mid") or []
    if not pool:
        return ""
    idx = (ctx.day_index or 0) % len(pool)
    return resolve_localized_display(pool[idx], lang, fallback="")


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
    parts: list[str] = []
    comps = list(getattr(ctx, "complications_occurred", []) or [])
    if comps:
        localised = [_localize_complication(str(c), ctx.target_lang) for c in comps[:3]]
        sep = t("list_sep.serial", lang)
        parts.append(t("progress.complications_noted", ctx.target_lang, list=sep.join(localised)))
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
                d = (_rdt.date() - _lab_adm_dt.date()).days
        if d is not None and d != ctx.day_index:
            continue
        name = _o(lab, "lab_name", None)
        val = _o(lab, "value", None)
        unit = _o(lab, "unit", "") or ""
        if name and val is not None:
            disp_name = _localize_lab_name(name, ctx.target_lang)
            disp_flag = _localize_lab_flag(flag, ctx.target_lang)
            unit_disp = _format_lab_unit_for_prose(unit)
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


def compose_progress_plan_from_state(ctx: NarrativeContext) -> str:
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
    admins = list(ctx.medications or [])
    _p_enc = getattr(ctx, "encounter", None)
    _adm_raw = _o(_p_enc, "admission_datetime", None) if _p_enc is not None else None
    _adm_dt = _parse_iso_datetime(_adm_raw) if _adm_raw is not None else None
    med_names: list[str] = []
    seen: set[str] = set()
    for m in admins:
        d = _o(m, "day", None)
        if d is None and _adm_dt is not None:
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
        from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

        med_names.append(localize_drug_name(str(name), lang))
        if len(med_names) >= 6:
            break
    if med_names:
        sep = t("list_sep.serial", lang)
        parts.append(t("progress.meds_continue", lang, list=sep.join(med_names)))
    procs = [_o(pr, "procedure_name", None) or _o(pr, "name", None) for pr in (ctx.procedures or [])[:4]]
    procs = [p for p in procs if p]
    if procs:
        sep = t("list_sep.serial", lang)
        parts.append(t("progress.procs_today", lang, list=sep.join(str(p) for p in procs)))
    if not parts:
        parts.append(t("progress.observation_fallback", lang))
    return t("list_sep.chunk", lang).join(parts)


def compose_today_vitals_line(ctx: NarrativeContext) -> str:
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


def compose_pe_vitals_line(ctx: NarrativeContext) -> str:
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
        on_o2 = bool(_o(v, "on_supplemental_oxygen", False))
        suffix = "" if on_o2 else " (RA)"
        parts.append(f"SpO2 {_spo2:.0f}%{suffix}")
    _rr = _o(v, "respiratory_rate", None)
    if _rr:
        parts.append(f"RR {int(_rr)}/min")

    return ", ".join(parts)


def apply_cc_pe_consistency(text: str, ctx: NarrativeContext) -> tuple[str, list[str]]:
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
                facts.append("avpu_pe_consistency:consciousness")
                text = new_text

    cc = _o(enc, "chief_complaint_ja", None) or _o(enc, "chief_complaint", None) or ""
    cc = str(cc)
    if not cc:
        return text, facts

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


def compose_vital_signs_line(ctx: NarrativeContext) -> str:
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
