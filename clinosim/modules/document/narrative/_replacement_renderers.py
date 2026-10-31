"""Per-section narrative renderers for the replacement-strategy
pipeline.

Second mechanical slice of the META #1633 P6 ``replacement_strategy``
decomposition (first was ``_replacement_localization.py``). Thirteen
pure helper functions that render per-concern narrative fragments
(chronic condition lists, newborn workup summaries, vitals-for-day,
supplemental oxygen status, medication lists, abnormal-lab digests,
lab trend / carry-forward tables, procedure summaries, stay-phase
labels) move from ``replacement_strategy.py`` to this sibling.

Zero behaviour change: ``replacement_strategy.py`` re-exports every
moved name via explicit ``from … import X as X`` aliases so (a)
external callers (``template_generator.py``'s
``_render_newborn_workup_summary`` import, tests, etc.) keep their
import path, and (b) mypy treats them as deliberately re-exported.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import display as registry_display
from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._replacement_localization import (
    _localize_severity_ja,
    localize_lab_name,
    localize_oxygen_device,
)
from clinosim.modules.document.narrative.template_generator import _filter_vitals_for_day


def _load_drug_localizer():  # pragma: no cover — trivial thunk
    """Lazy import of the lang-aware `localize_drug_name` wrapper.
    Returned callable takes `(drug_name, lang)` — a no-op for any
    lang without a lookup table."""
    from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name as _f

    return _f


def _get(obj, key, default=None):
    """Safe getattr-or-dict-get for either a Pydantic / dataclass
    instance or a plain dict shape (CIF JSON re-read)."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _render_chronic_list(chronic: list, lang: str = "en") -> str:
    """chronic_conditions [{'code','system','severity','stage','onset_date'}, ...]
    → short comma-separated string of the form
    ``"<display> (<code>) (<stage>, <severity>)"``.

    session-88j Phase B: when ``lang == "ja"`` translates the severity
    token (mild/moderate/severe → 軽度/中等度/重度) inline so downstream
    LLM verbatim-copy behaviour lands natural Japanese instead of raw
    English tokens. Stage codes ("Stage 1", "G3b", "NYHA II") are
    intentionally kept as-is since those are the JA medical standard.

    Issue #1445: when the entry carries an explicit ``system`` field the
    display is resolved via :func:`clinosim.codes.lookup` and prepended
    to the code so the LLM does not have to guess the label from
    parametric memory (observed hallucination: G20 → "glaucoma", where
    G20 is Parkinson's disease and glaucoma is H40). Entries without a
    ``system`` field (legacy CIFs that stored resolved labels directly
    in ``code``) pass through unchanged for backward compatibility.
    """

    parts = []
    for c in (chronic or [])[:15]:
        if isinstance(c, str):
            parts.append(c)
            continue
        code = _get(c, "code", "") or ""
        system = _get(c, "system", "") or ""
        stage = _get(c, "stage", "") or ""
        sev = _get(c, "severity", "") or ""
        if sev and lang == "ja":
            sev = _localize_severity_ja(sev)
        detail = ""
        if stage and sev:
            detail = f" ({stage}, {sev})"
        elif stage:
            detail = f" ({stage})"
        elif sev:
            detail = f" ({sev})"
        # Issue #1445: resolve display when system is present. code_lookup
        # echoes the code back on miss (unmapped / fictional codes), so
        # guard against emitting a redundant "CODE (CODE)" string.
        display = ""
        if code and system:
            resolved = registry_display(system, code, lang) or ""
            if resolved and resolved != code:
                display = resolved
        if display and code:
            parts.append(f"{display} ({code}){detail}")
        elif code:
            parts.append(f"{code}{detail}")
    return "; ".join(parts) if parts else ""


def _render_newborn_workup_summary(workup: dict, lang: str = "en") -> str:
    """Issue #1404: one-line neonatal workup anchor for admission_hp
    narrative. Reads the projection built by
    ``context._build_newborn_workup`` and composes a JA/EN sentence
    citing the elements the LLM MUST weave into the HPI (Apgar) and
    A&P (Vitamin K / AABR / metabolic screen / bilirubin / CCHD /
    ophthalmic prophylaxis) sections.

    Missing elements drop silently — the summary always reflects what
    the CIF actually carries. Never fabricates a screening not run.
    """
    if not workup:
        return ""
    parts: list[str] = []

    a1 = workup.get("apgar_1min")
    a5 = workup.get("apgar_5min")
    if a1 is not None or a5 is not None:
        a1_str = str(a1) if a1 is not None else "-"
        a5_str = str(a5) if a5 is not None else "-"
        parts.append(t("newborn.apgar_line", lang, a1=a1_str, a5=a5_str))

    if workup.get("has_aabr"):
        parts.append(t("newborn.aabr_completed", lang))

    if workup.get("has_metabolic"):
        parts.append(t("newborn.tandem_ms_submitted", lang))

    bili = workup.get("bilirubin_peak")
    if bili is not None:
        try:
            bili_f = float(bili)
            parts.append(t("newborn.bilirubin_peak", lang, v=bili_f))
        except (TypeError, ValueError):
            pass

    ru = workup.get("cchd_ru_spo2")
    le = workup.get("cchd_le_spo2")
    if ru is not None or le is not None:
        ru_str = f"{ru}%" if ru is not None else "-"
        le_str = f"{le}%" if le is not None else "-"
        parts.append(t("newborn.cchd_spo2_line", lang, ru=ru_str, le=le_str))

    if workup.get("has_vitamin_k"):
        parts.append(t("newborn.vitamin_k_admin", lang))

    if workup.get("has_ophthalmic"):
        parts.append(t("newborn.ophthalmic_prophylaxis", lang))

    if not parts:
        return ""
    sep = t("list_sep.semicolon", lang)
    return sep.join(parts)


def _render_vitals_for_day(vitals: list, day_index: int, encounter: object | None = None) -> str:
    """Filter vitals to today and pick a summary of key numeric fields.

    v6 (2026-08-16): Uses the shared ``_filter_vitals_for_day`` helper,
    which honours the explicit ``day`` field when present and falls
    back to a timestamp-derived day offset otherwise. The v5 filter
    (day-field only) let admission-day vitals leak into every day's
    context because current CIF vitals leave ``day = None``.
    """
    filtered = _filter_vitals_for_day(vitals, day_index, encounter)
    picks: list[str] = []
    max_pick = 3
    for v in filtered:
        systolic = _get(v, "systolic_bp")
        diastolic = _get(v, "diastolic_bp")
        hr = _get(v, "heart_rate")
        temp = _get(v, "temperature_celsius")
        rr = _get(v, "respiratory_rate")
        spo2 = _get(v, "spo2")
        bits = []
        if temp:
            bits.append(f"T {temp}°C")
        if hr:
            bits.append(f"HR {hr}")
        if systolic and diastolic:
            bits.append(f"BP {systolic}/{diastolic}")
        if rr:
            bits.append(f"RR {rr}")
        if spo2:
            bits.append(f"SpO2 {spo2}%")
        if bits:
            ts = _get(v, "timestamp", "")
            picks.append((str(ts)[:19] + " " if ts else "") + " / ".join(bits))
        if len(picks) >= max_pick:
            break
    return "; ".join(picks) if picks else ""


def _render_supplemental_oxygen_today(vitals: list, day_index: int, encounter: object | None, lang: str = "en") -> str:
    """If any vital today records supplemental oxygen, return a short
    descriptor for the LLM prompt (device + flow rate).

    v6 (2026-08-16): v5 context omitted this flag entirely — the LLM
    wrote "SpO2 89% だが酸素投与なしで安定" (POP-000075 doc-06)
    contradicting the on_supplemental_oxygen=True field on that day's
    vitals. Feeding the flag lets the prompt's Hard Rules keep the
    narrative consistent with the recorded therapy.

    session-88j Phase B: when ``lang == "ja"`` localizes the device
    label (nasal_cannula → 経鼻カニューレ, oxygen_mask → 酸素マスク,
    etc.) so JA narratives no longer leak raw snake_case tokens
    (v14 review: 155 mentions).
    """
    filtered = _filter_vitals_for_day(vitals, day_index, encounter)
    for v in filtered:
        if not _get(v, "on_supplemental_oxygen"):
            continue
        device = _get(v, "oxygen_delivery_device") or "supplemental O2"
        device_str = localize_oxygen_device(str(device), lang)
        flow = _get(v, "oxygen_flow_rate_lpm")
        if flow is not None:
            try:
                flow_val = float(flow)
                return f"{device_str} {flow_val:g} L/min"
            except (TypeError, ValueError):
                pass
        return device_str
    return ""


def _render_first_vitals(vitals: list) -> str:
    """First-recorded vitals (arrival vitals for ED)."""
    for v in vitals or []:
        systolic = _get(v, "systolic_bp")
        hr = _get(v, "heart_rate")
        temp = _get(v, "temperature_celsius")
        spo2 = _get(v, "spo2")
        bits = []
        if temp:
            bits.append(f"T {temp}°C")
        if hr:
            bits.append(f"HR {hr}")
        if systolic:
            diastolic = _get(v, "diastolic_bp")
            bits.append(f"BP {systolic}/{diastolic}" if diastolic else f"BP {systolic}")
        if spo2:
            bits.append(f"SpO2 {spo2}%")
        if bits:
            return " / ".join(bits)
    return ""


def _render_med_names(meds: list, lang: str = "en") -> str:
    """List of medication display names, deduplicated, comma-joined.

    v7 (2026-08-17): when ``lang == "ja"``, resolves each drug name
    against the shared `load_narrative_display_dict` catalog (same source
    the FHIR emit uses). v6 fed raw English drug names into the JA
    prompt, so the LLM invented katakana approximations (アトロバスタチン
    ← Atorvastatin, エンラプリル ← Enalapril, カルベドロール ←
    Carvedilol, アモロジピン ← Amlodipine, ウァルファリン ← Warfarin —
    36 doc affected in v9 review). Feeding the canonical katakana
    upfront eliminates the transliteration guess.
    """
    names: list[str] = []
    seen: set[str] = set()
    for m in meds or []:
        name = _get(m, "name") or _get(m, "display_name") or _get(m, "drug_name") or _get(m, "medication")
        if isinstance(m, str):
            name = m
        if not name:
            continue
        localized = _load_drug_localizer()(str(name), lang)
        if localized and localized not in seen:
            names.append(localized[:60])
            seen.add(localized)
        if len(names) >= 12:
            break
    return "; ".join(names) if names else ""


def _render_active_meds(admins: list, day_index: int, lang: str = "en") -> str:
    """MedicationAdministration records active on the given day. Short list
    of unique drug names given today (progress_note context). v7: same
    JA localization as ``_render_med_names``."""
    names: list[str] = []
    seen: set[str] = set()
    for m in admins or []:
        d = _get(m, "day")
        if d is not None and d != day_index:
            continue
        name = _get(m, "drug_name") or _get(m, "medication") or _get(m, "name")
        if not name:
            continue
        localized = _load_drug_localizer()(str(name), lang)
        if localized and localized not in seen:
            names.append(localized[:60])
            seen.add(localized)
        if len(names) >= 12:
            break
    return "; ".join(names) if names else ""


def _render_abnormal_labs(
    lab_results: list,
    day_index: int | None,
    lang: str = "en",
    admission_datetime: Any = None,
) -> str:
    """H / L / critical flagged labs, formatted for LLM injection.

    v6 blocker fix: v5 context omitted lab flags entirely so LLM
    assessments ignored AST H, PT_INR H, Cr H etc. Session-90 fix:
    the day-filter used to compare ``lab["day"]`` — but CIF
    ``lab_results`` do not carry a ``day`` field (only
    ``result_datetime``), so the filter never fired and progress notes
    for every hospital day cited the day-0 admission labs verbatim
    (POP-000021 DKA case, 12/12 daily notes all quoting Glucose 518,
    pH 7.18, HCO3 10.1). Now delegates to
    :mod:`clinosim.modules.document.narrative.lab_timeseries` which
    computes day from ``result_datetime`` − ``admission_datetime``.

    * ``day_index=None`` (discharge_summary): all abnormal labs.
    * ``day_index=N`` (progress_note / soap): only labs measured on day N.
      Requires ``admission_datetime``; if missing, degrades gracefully
      by returning all abnormal labs (preserves session-88j behaviour
      for callers that have not yet been migrated).

    session-88j Phase B: when ``lang == "ja"`` translates full-English
    lab names (Creatinine, Glucose, Lactate, Albumin, Sodium/Potassium,
    …) to natural Japanese (クレアチニン, 血糖, 乳酸, アルブミン, ナトリウム,
    …). Standard abbreviations (BUN, CRP, BNP, WBC, HbA1c, eGFR, Cr,
    Na, K, PT-INR, …) are kept as-is since those are Japanese medical
    convention.
    """
    from clinosim.modules.document.narrative.lab_timeseries import labs_measured_on_day

    if day_index is not None and admission_datetime is not None:
        source = labs_measured_on_day(lab_results, admission_datetime, day_index)
    else:
        source = list(lab_results or [])

    picks: list[str] = []
    max_pick = 8
    for lab in source:
        flag = _get(lab, "flag")
        if not flag:
            continue
        name = _get(lab, "lab_name") or _get(lab, "name") or ""
        val = _get(lab, "value")
        unit = _get(lab, "unit") or ""
        if not name or val is None:
            continue
        name = localize_lab_name(str(name), lang)
        val_str = f"{val}"
        parts = f"{name} {val_str}"
        if unit:
            # Phase 1d-79: strip UCUM bracket / annotation from unit before
            # injecting into LLM context — the LLM's Rule 3 verbatim-copy
            # otherwise carries `mm[Hg]` / `{INR}` / `[pH]` into narrative
            # prose. Mirrors the template-side fix in Phase 1d-65/1d-69.
            from clinosim.modules.document.narrative.template_generator import (
                _format_lab_unit_for_prose,
            )

            unit_disp = _format_lab_unit_for_prose(unit)
            # Phase 1d-80: skip the unit when it equals the lab_name after
            # bracket stripping. Real case: name="pH" + UCUM unit="[pH]" →
            # unit_disp="pH" → visible duplicate "pH 7.11 pH [L]". This
            # is unitless-scale idiom (pH is dimensionless) — drop unit.
            if unit_disp and unit_disp.lower() != str(name).lower():
                parts += f" {unit_disp}"
        parts += f" [{flag}]"
        picks.append(parts)
        if len(picks) >= max_pick:
            break
    return "; ".join(picks) if picks else ""


# _TREND_LABEL_JA / _TREND_LABEL_EN moved to
# `narrative_labels.yaml/lab_trend_direction:` (Phase 1d-62).
# Resolved via `resolve_localized_display` at emit time so adding a
# new locale is a data-only change.


def _render_lab_trend_today(
    lab_results: list,
    day_index: int,
    admission_datetime: Any,
    lang: str = "en",
) -> str:
    """For each lab measured today, one-line trend vs the closest earlier
    measurement of the same test. Session-90 addition — enables
    accurate 改善 / 悪化 / 不変 commentary in progress notes.

    Format (JA)::

        血糖 300 mg/dL [H] (前値 518 [critical] → 改善);
        HCO3 14.0 mmol/L [L] (前値 10.1 [L] → 改善)

    Format (EN)::

        Glucose 300 mg/dL [H] (prior 518 [critical] → improving);
        HCO3 14.0 mmol/L [L] (prior 10.1 [L] → improving)

    Skips ``initial`` entries (no prior to trend against; already
    covered by ``abnormal_labs_today``).
    """
    from clinosim.modules.document.narrative.lab_timeseries import lab_trend

    trend_rows = lab_trend(lab_results, admission_datetime, day_index)
    if not trend_rows:
        return ""
    from clinosim.locale.loader import load_narrative_labels, resolve_localized_display

    _direction_map = load_narrative_labels().get("lab_trend_direction", {})
    prior_word = t("list_sep.prior_word", lang)
    parts: list[str] = []
    for row in trend_rows:
        if row["direction"] == "initial":
            continue
        name = localize_lab_name(str(row["name"]), lang)
        cur_flag_part = f" [{row['current_flag']}]" if row["current_flag"] else ""
        prior_flag_part = f" [{row['prior_flag']}]" if row["prior_flag"] else ""
        direction_label = resolve_localized_display(
            _direction_map.get(row["direction"]), lang, fallback=row["direction"]
        )
        parts.append(
            f"{name} {row['current_value']}{cur_flag_part} "
            f"({prior_word} {row['prior_value']}{prior_flag_part} → {direction_label})"
        )
        if len(parts) >= 8:
            break
    return "; ".join(parts)


def _render_lab_carry_forward(
    lab_results: list,
    day_index: int,
    admission_datetime: Any,
    lang: str = "en",
) -> str:
    """Latest known abnormal value per lab_name at day ``day_index``,
    including tests NOT measured today. Session-90 addition —
    represents the current known state so a progress note can reference
    yesterday's CRP if CRP was not redrawn today (real-EHR pattern).

    Skips tests measured today (already covered by
    ``abnormal_labs_today``) and tests without an H / L / critical flag
    on their latest measurement (LLM does not need to enumerate
    normalized tests).

    Format (JA)::

        HCO3 14.0 mmol/L [L] (day 5); K 5.5 mmol/L [H] (day 4)
    """
    from clinosim.modules.document.narrative.lab_timeseries import (
        day_of_lab,
        latest_by_lab_name,
    )

    latest = latest_by_lab_name(lab_results, admission_datetime, up_to_day=day_index)
    day_word_prefix = "day " if lang != "ja" else ""
    day_word_suffix = "" if lang != "ja" else "日目"
    parts: list[str] = []
    for name, lab in latest.items():
        d = day_of_lab(lab, admission_datetime)
        if d == day_index:
            continue  # measured today — handled by abnormal_labs_today
        flag = _get(lab, "flag")
        if not flag:
            continue
        val = _get(lab, "value")
        unit = _get(lab, "unit") or ""
        if val is None:
            continue
        display_name = localize_lab_name(str(name), lang)
        # Day is 0-indexed; caller-facing convention is 1-indexed hospital day.
        display_day = (d + 1) if d is not None else "?"
        val_str = f"{val}"
        piece = f"{display_name} {val_str}"
        if unit:
            # Phase 1d-79: strip UCUM brackets / annotations for LLM context
            # (see _render_abnormal_labs comment).
            from clinosim.modules.document.narrative.template_generator import (
                _format_lab_unit_for_prose,
            )

            unit_disp = _format_lab_unit_for_prose(unit)
            # Phase 1d-80: dedupe when unit collapses to the same string as
            # the localized name (see _render_abnormal_labs — pH case).
            if unit_disp and unit_disp.lower() != str(display_name).lower():
                piece += f" {unit_disp}"
        piece += f" [{flag}] ({day_word_prefix}{display_day}{day_word_suffix})"
        parts.append(piece)
        if len(parts) >= 8:
            break
    return "; ".join(parts)


def _render_key_procedures(procedures: list) -> str:
    """List procedures performed during the stay for discharge_summary
    hospital_course context (v6 fix: LLM had no procedure facts to
    reference, producing generic "経過良好" summaries)."""
    names: list[str] = []
    seen: set[str] = set()
    for pr in procedures or []:
        name = _get(pr, "procedure_name") or _get(pr, "name") or _get(pr, "display_name")
        if not name:
            code = _get(pr, "code") or _get(pr, "procedure_code")
            name = str(code) if code else None
        if not name or name in seen:
            continue
        seen.add(name)
        d = _get(pr, "day")
        if d is not None:
            names.append(f"{name} (day {d})")
        else:
            names.append(str(name))
        if len(names) >= 8:
            break
    return "; ".join(names) if names else ""


def _render_vitals_range(vitals: list) -> str:
    """Min/max range of key vitals across the whole stay (BP, HR, T, SpO2).
    Feeds discharge_summary hospital_course so the LLM can say "T peaked
    at 39.1 on D3" instead of generic "経過良好"."""
    if not vitals:
        return ""
    fields = ("systolic_bp", "heart_rate", "temperature_celsius", "spo2")
    minmax: dict[str, tuple[float, float]] = {}
    for v in vitals:
        for f in fields:
            val = _get(v, f)
            if val is None:
                continue
            try:
                num = float(val)
            except (TypeError, ValueError):
                continue
            lo, hi = minmax.get(f, (num, num))
            minmax[f] = (min(lo, num), max(hi, num))
    if not minmax:
        return ""
    labels = {"systolic_bp": "sBP", "heart_rate": "HR", "temperature_celsius": "T", "spo2": "SpO2"}
    parts = []
    for f, (lo, hi) in minmax.items():
        parts.append(f"{labels[f]} {lo:g}-{hi:g}")
    return " / ".join(parts)


def _stay_phase(day_index: int, los_days: int, lang: str = "en") -> str:
    """Bucket day-of-stay into phase label the LLM can key off in prose.

    Phase 1d-79: JA output pre-localizes the label so the LLM's Rule 3
    verbatim-copy behavior surfaces natural JA prose (「急性期」等) rather
    than the raw English tokens (`middle / stabilisation phase`) leaking
    into JA narratives.
    """
    is_ja = str(lang).lower().startswith("ja")
    if los_days <= 1:
        return "単日受診" if is_ja else "single-day encounter"
    frac = (day_index + 1) / max(los_days, 1)
    if frac <= 0.34:
        return "急性期" if is_ja else "early / acute phase"
    if frac <= 0.66:
        return "安定期" if is_ja else "middle / stabilisation phase"
    if frac < 1.0:
        return "退院準備期" if is_ja else "late / pre-discharge phase"
    return "退院日" if is_ja else "discharge day"
