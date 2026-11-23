"""What the notes say about an ICU stay (Issue #3555).

The record flags a stay as transferred to the ICU on a hospital day
(``icu_transferred`` / ``icu_transferred_day``); the FHIR Encounter's
``classHistory`` puts the ICU segment from that day (the admission's clock time
plus the day) to discharge. The record holds no step-down day, so the notes
state the transfer and that the patient is in the ICU since then, never a
return to the ward.

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
    after it, ``None`` before it or without a transfer."""
    day = icu_hospital_day(ctx)
    if day is None:
        return None
    at = icu_transfer_at(ctx)
    if as_of is not None and at is not None:
        if as_of < at:
            return None
        return "transfer_day" if as_of.date() == at.date() else "in_icu"
    index = getattr(ctx, "day_index", 0)
    if index < day - 1:
        return None
    return "transfer_day" if index == day - 1 else "in_icu"


def icu_progress_line(ctx: NarrativeContext, as_of: Any) -> str:
    """The Assessment statement of a progress note: the transfer with the
    complications of that day on the transfer day, "in the ICU since hospital
    day N" afterwards; ``""`` before the transfer or for a stay without one."""
    state = _state(ctx, as_of)
    if state is None:
        return ""
    lang = ctx.target_lang
    day = icu_hospital_day(ctx)
    if state == "in_icu":
        return t("icu_stay.progress_in_icu", lang, day=day)
    reason = icu_transfer_reason(ctx, as_of)
    if reason:
        return t("icu_stay.progress_transfer_with_reason", lang, day=day, reason=reason)
    return t("icu_stay.progress_transfer", lang, day=day)


def icu_course_sentence(ctx: NarrativeContext) -> tuple[str, str]:
    """The discharge summary's ICU clause: the transfer with its day and date,
    and the complications of that day. No step-down is stated (none is recorded)."""
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
    key = "icu_stay.course" + ("_dated" if date else "") + ("_with_reason" if reason else "")
    return t(key, lang, day=day, date=date, reason=reason), "ctx.icu_transferred_day"
