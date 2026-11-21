"""The next visit of the series a visit belongs to (Issue #3465).

A note's "next visit" line states the visit the patient is actually scheduled
for: the next outpatient visit of the same series in
``NarrativeContext.interval_encounters`` (the patient's other encounters,
:func:`~clinosim.modules.document.narrative._interval_events.other_encounters`).
A vaccination visit's series is the vaccination visits; any other visit's is
the visits of its simulator ``visit_type`` and ``visit_condition_id`` (a
chronic follow-up of one condition, a post-discharge visit, a screening).
Emergency, inpatient and unplanned visits of other series are not the next
visit. The encounters are all within the simulated period, so the line never
reads beyond it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime


def _when(value: Any) -> datetime | None:
    parsed = parse_iso_datetime(value, lenient=True)
    return parsed.replace(tzinfo=None) if parsed is not None else None


def _is_vaccination_visit(ctx: Any) -> bool:
    return bool(getattr(ctx, "immunizations", None))


def next_visit_days(ctx: Any) -> int | None:
    """Whole days from this visit to the next outpatient visit of its series,
    ``None`` when the patient has none (or this visit has no series)."""
    enc = ctx.encounter
    others = list(getattr(ctx, "interval_encounters", None) or [])
    this_end = _when(_o(enc, "discharge_datetime", None)) or _when(_o(enc, "admission_datetime", None))
    if this_end is None or not others:
        return None
    this_id = str(_o(enc, "encounter_id", "") or "")
    vaccination = _is_vaccination_visit(ctx)
    visit_type = str(getattr(ctx, "visit_type", "") or "")
    condition = str(getattr(ctx, "visit_condition_id", "") or "")
    if not vaccination and not visit_type:
        return None
    # A visit kind with no scheduled return (an acute illness) has no next visit.
    from clinosim.modules.document.narrative._visit_reason import next_visit_line, visit_kind

    kind = visit_kind(ctx)
    if kind and next_visit_line(ctx, kind) == "":
        return None
    starts: list[datetime] = []
    for o in others:
        if o.get("encounter_type") != "outpatient" or o.get("encounter_id") == this_id:
            continue
        if vaccination:
            same = bool(o.get("vaccination"))
        else:
            same = (
                not o.get("vaccination")
                and o.get("visit_type") == visit_type
                and o.get("visit_condition_id") == condition
            )
        start = _when(o.get("start"))
        if same and start is not None and start.date() > this_end.date():
            starts.append(start)
    if not starts:
        return None
    return (min(starts).date() - this_end.date()).days
