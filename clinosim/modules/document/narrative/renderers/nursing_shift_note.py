"""Nursing shift note (NURSING_SHIFT_NOTE) narrative renderer.

Extracted verbatim from
``template_generator.TemplateNarrativeGenerator._render_nursing_shift_note_text``
as the second step (C1a) of the full-review Phase C renderer split
(CRITICAL C1). Behavior is byte-identical — the class method is now a
thin delegator to this free-standing function.

Uses only module-level helpers (``_label``, ``_resolve_staff_name``,
``_filter_vitals_for_day``, ``t``, ``_o``); no attribute access on the
generator instance.
"""

from __future__ import annotations

from typing import Any

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.document.narrative._narrative_utils import _filter_vitals_for_day
from clinosim.modules.document.narrative._template_helpers import _label, _resolve_staff_name
from clinosim.modules.document.narrative.registry import DocumentTypeSpec
from clinosim.types.document import NarrativeContext, NarrativeOutput


def render_nursing_shift_note(ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
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

    day_num = ctx.day_index + 1  # 1-based display
    los = ctx.los_days or 1

    shift_key = ctx.shift or ""
    shift_label = ""
    if shift_key:
        facts.append("ctx.shift")
        # Unknown key → render the neutral key itself (never drop silently).
        shift_label = _label("shift_labels", shift_key, lang, fallback=shift_key)

    nurse_id = _o(ctx.encounter, "primary_nurse_id", "") or ""
    nurse_line = ""
    if nurse_id:
        facts.append("encounter.primary_nurse_id")
        nurse_disp = _resolve_staff_name(nurse_id, ctx.roster_map)
        nurse_line = t("nursing_shift.nurse_line", lang, name=nurse_disp)

    # v9 (2026-08-17) density fix: replace 「バイタルサイン安定 / 特記事項なし」
    # boilerplate with CIF-sourced per-shift narrative (today's vitals,
    # supplemental O2 flag, active meds, ADL trend, risk flags).
    picks = _filter_vitals_for_day(ctx.vitals, ctx.day_index, ctx.encounter)
    v = picks[0] if picks else None

    status_bits: list[str] = []
    if v is not None:
        temp = _o(v, "temperature_celsius", None)
        spo2 = _o(v, "spo2", None)
        sbp = _o(v, "systolic_bp", None)
        dbp = _o(v, "diastolic_bp", None)
        hr = _o(v, "heart_rate", None)
        on_o2 = _o(v, "on_supplemental_oxygen", False)
        device = _o(v, "oxygen_delivery_device", None)
        flow = _o(v, "oxygen_flow_rate_lpm", None)
        vital_line_parts: list[str] = []
        if sbp and dbp:
            vital_line_parts.append(f"BP {int(sbp)}/{int(dbp)}")
        if hr:
            vital_line_parts.append(f"HR {int(hr)}")
        if spo2:
            vital_line_parts.append(f"SpO2 {float(spo2):.0f}%")
        if temp:
            vital_line_parts.append(f"T {float(temp):.1f}°C")
        if vital_line_parts:
            status_bits.append(", ".join(vital_line_parts))
        if on_o2:
            # Device-name katakana lookup is a JA-locale data
            # pipeline via `localize_oxygen_device(x, lang)` — a
            # no-op for any lang without a lookup table.
            from clinosim.modules.document.narrative.replacement_strategy import (
                localize_oxygen_device,
            )

            device_disp = localize_oxygen_device(str(device or ""), lang)
            if device and flow is not None:
                try:
                    flow_str = f"{float(flow):g}"
                    status_bits.append(t("nursing_shift.o2_device_with_flow", lang, device=device_disp, flow=flow_str))
                except (TypeError, ValueError):
                    status_bits.append(t("oxygen.device_line", lang, device=device_disp))
            else:
                status_bits.append(t("nursing.supplemental_o2", lang))
        facts.append("ctx.vitals.today")

    # Today's meds (limit 3 for shift-note brevity)
    med_names: list[str] = []
    seen: set[str] = set()
    for m in (ctx.medications or [])[:12]:
        d = _o(m, "day", None)
        if d is not None and d != ctx.day_index:
            continue
        n = _o(m, "drug_name", None) or _o(m, "medication", None)
        if not n or n in seen:
            continue
        seen.add(n)
        # Drug-name katakana lookup via lang-aware wrapper —
        # no-op for lang without a lookup table.
        from clinosim.modules.output.fhir_r4.lib.localization import localize_drug_name

        med_names.append(localize_drug_name(str(n), lang))
        if len(med_names) >= 3:
            break

    # Risk flag today
    risks = list(getattr(ctx, "nursing_risk_assessments", None) or [])
    risk_bit = ""
    if risks:
        latest = risks[-1]
        fall = _o(latest, "fall_risk_level", None)
        if fall and str(fall).lower() in ("high", "moderate"):
            # Localize the risk-level enum via the shared morse_band
            # phrase catalog (low/moderate/high → 低リスク/中等度リスク/
            # 高リスク on JA output). Unknown values fall back to the
            # raw token so novel risk levels still surface.
            fall_disp = t(f"morse_band.{str(fall).lower()}", lang)
            if fall_disp == f"morse_band.{str(fall).lower()}":
                fall_disp = str(fall)
            risk_bit = t("nursing_shift.fall_risk_line", lang, level=fall_disp)
            facts.append("ctx.nursing_risk_assessments[-1]")

    title = (
        t("nursing_shift.title_with_shift", lang, shift=shift_label)
        if shift_label
        else t("nursing_shift.title_no_shift", lang)
    )
    header = t("nursing_shift.header_line", lang, title=title, day=day_num, los=los)
    # status_bits separator differs by locale: JA uses 「、」, EN uses
    # "; " — matched by list_sep.semicolon. Trailing period picked
    # via list_sep.period (「。」 / ".").
    if status_bits:
        status_body = t("list_sep.semicolon", lang).join(status_bits) + t("list_sep.period", lang)
    else:
        status_body = t("nursing_shift.no_vital_record", lang)
    status = t("nursing_shift.patient_status_head", lang) + status_body
    if med_names:
        meds_line = (
            t("nursing_shift.meds_head", lang) + t("list_sep.serial", lang).join(med_names) + t("list_sep.period", lang)
        )
    else:
        meds_line = ""
    observations = risk_bit or t("nursing_shift.observations_default", lang)

    lines = [header]
    if nurse_line:
        lines.append(nurse_line)
    lines.append(status)
    if meds_line:
        lines.append(meds_line)
        facts.append("ctx.medications.today")
    lines.append(observations)
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
