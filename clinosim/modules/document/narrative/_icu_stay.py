"""What the notes say about an ICU stay (Issue #3555).

The record flags a stay as transferred to the ICU on a hospital day
(``icu_transferred`` / ``icu_transferred_day``); the FHIR Encounter's
``classHistory`` puts the ICU segment from that day (the admission's clock time
plus the day) to the step-down (``icu_discharge_day``, the same clock-time
convention) or, when none is recorded, to discharge. Until the step-down the
notes say the patient is in the ICU since the transfer; the note and the
nursing shift of the step-down say the patient returned to the ward, notes
after it name no unit, and the discharge summary gives the ICU dates. Without
a recorded step-down they never state a return to the ward.

The reason for the transfer is not recorded as such; the note names the
complications that began on the transfer day ("in the setting of ...") and
states no reason when there are none. Phrases: the ``icu_stay`` block of
``locale/shared/narrative_phrases.yaml``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from clinosim.locale.i18n import t
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = [
    "icu_course_sentence",
    "icu_hospital_day",
    "icu_progress_line",
    "icu_step_down_at",
    "icu_step_down_hospital_day",
    "icu_transfer_at",
    "icu_transfer_reason",
]

MAX_REASONS = 3


def icu_hospital_day(ctx: NarrativeContext) -> int | None:
    """The 1-based hospital day of the ICU transfer, ``None`` without a transfer."""
    day = getattr(ctx, "icu_transferred_day", -1)
    if not getattr(ctx, "icu_transferred", False) or not isinstance(day, int) or day < 0:
        return None
    return day + 1


def icu_transfer_at(ctx: NarrativeContext) -> datetime | None:
    """The transfer's time as the FHIR ``classHistory`` gives it: the admission
    time plus the transfer day. ``None`` without a transfer or an admission time."""
    if icu_hospital_day(ctx) is None:
        return None
    admitted = parse_iso_datetime(_o(getattr(ctx, "encounter", None), "admission_datetime", None), lenient=True)
    if admitted is None:
        return None
    return admitted + timedelta(days=ctx.icu_transferred_day)


def icu_step_down_hospital_day(ctx: NarrativeContext) -> int | None:
    """The 1-based hospital day of the step-down to the ward, ``None`` when the
    record has none (still in the ICU at discharge, or no transfer)."""
    start = icu_hospital_day(ctx)
    day = getattr(ctx, "icu_discharge_day", -1)
    if start is None or not isinstance(day, int) or day + 1 <= start:
        return None
    return day + 1


def icu_step_down_at(ctx: NarrativeContext) -> datetime | None:
    """The step-down's time: the admission time plus the step-down day, as the
    FHIR ``classHistory`` gives it; ``None`` without a step-down."""
    if icu_step_down_hospital_day(ctx) is None:
        return None
    admitted = parse_iso_datetime(_o(getattr(ctx, "encounter", None), "admission_datetime", None), lenient=True)
    if admitted is None:
        return None
    return admitted + timedelta(days=ctx.icu_discharge_day)


def icu_transfer_reason(ctx: NarrativeContext, as_of: Any = None) -> str:
    """The complications that began on the transfer day (and by ``as_of``),
    localized and joined; ``""`` without one."""
    from clinosim.modules.document.narrative._localization import _localize_complication

    lang = ctx.target_lang
    day = getattr(ctx, "icu_transferred_day", -1)
    names: list[str] = []
    for event in getattr(ctx, "complications_events", None) or []:
        name = str(_o(event, "name", "") or "")
        if not name or _o(event, "onset_day", None) != day:
            continue
        onset = parse_iso_datetime(_o(event, "onset_datetime", None), lenient=True)
        if as_of is not None and onset is not None and onset > as_of:
            continue
        label = _localize_complication(name, lang)
        if label not in names:
            names.append(label)
    return t("list_sep.serial", lang).join(names[:MAX_REASONS])


def _state(ctx: NarrativeContext, as_of: Any) -> str | None:
    """``"transfer_day"`` on the day of the transfer (once it happened), ``"in_icu"``
    after it, ``"step_down"`` on the day of the step-down (once it happened),
    ``None`` before the transfer, after the step-down day or without a transfer."""
    day = icu_hospital_day(ctx)
    if day is None:
        return None
    at = icu_transfer_at(ctx)
    out_day = icu_step_down_hospital_day(ctx)
    out_at = icu_step_down_at(ctx)
    if as_of is not None and at is not None:
        if as_of < at:
            return None
        if out_at is not None and as_of >= out_at:
            return "step_down" if as_of.date() == out_at.date() else None
        return "transfer_day" if as_of.date() == at.date() else "in_icu"
    index = getattr(ctx, "day_index", 0)
    if index < day - 1:
        return None
    if out_day is not None and index >= out_day - 1:
        return "step_down" if index == out_day - 1 else None
    return "transfer_day" if index == day - 1 else "in_icu"


def icu_progress_line(ctx: NarrativeContext, as_of: Any) -> str:
    """The Assessment statement of a progress note: the transfer with the
    complications of that day on the transfer day, "in the ICU since hospital
    day N" afterwards, the return to the ward on the step-down day; ``""``
    before the transfer, after the step-down day or for a stay without one."""
    state = _state(ctx, as_of)
    if state is None:
        return ""
    lang = ctx.target_lang
    day = icu_hospital_day(ctx)
    if state == "step_down":
        return t("icu_stay.progress_step_down", lang, day=icu_step_down_hospital_day(ctx))
    if state == "in_icu":
        return t("icu_stay.progress_in_icu", lang, day=day)
    reason = icu_transfer_reason(ctx, as_of)
    if reason:
        return t("icu_stay.progress_transfer_with_reason", lang, day=day, reason=reason)
    return t("icu_stay.progress_transfer", lang, day=day)


def icu_course_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """The discharge summary's ICU clause: the transfer with its day and date,
    and the complications of that day; with a recorded step-down, the ICU dates
    ("from <date> (hospital day N) to <date> (hospital day M)") and the return to
    the ward."""
    day = icu_hospital_day(ctx)
    if day is None:
        return "", ""
    at = icu_transfer_at(ctx)
    as_of = getattr(ctx, "authored_datetime", None)
    if as_of is not None and at is not None and at > as_of:
        return "", ""
    lang = ctx.target_lang
    date = at.date().isoformat() if at is not None else ""
    reason = icu_transfer_reason(ctx, as_of)
    out_at = icu_step_down_at(ctx)
    if out_at is not None and date and (as_of is None or out_at <= as_of):
        key = "icu_stay.course_range" + ("_with_reason" if reason else "")
        text = t(
            key,
            lang,
            day=day,
            date=date,
            end_day=icu_step_down_hospital_day(ctx),
            end_date=out_at.date().isoformat(),
            reason=reason,
        )
        return text, "ctx.icu_discharge_day"
    key = "icu_stay.course" + ("_dated" if date else "") + ("_with_reason" if reason else "")
    return t(key, lang, day=day, date=date, reason=reason), "ctx.icu_transferred_day"
