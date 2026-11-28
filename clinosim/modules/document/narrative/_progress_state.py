"""One state per vital finding of a progress note (Issue #3541).

The Subjective sentences (fever, consciousness) and the Assessment's course
line of a daily note are written from the table :func:`finding_states`
returns, so one note never says a finding both resolved and persists, or new
and persistent. The table is judged only on the readings up to the note's
authored time.

States of an ``progress_exam.yaml`` course item:

``new``            present at the latest reading, absent and clear of the limit over the
                   previous period
``persisting``     present at the latest reading and over the previous period (or
                   the previous period only borderline, Issue #3964)
``improving``      absent at the latest reading, present in the previous period,
                   but not yet absent over the sustained window (``course_state``)
``resolved``       absent over the sustained window, with enough readings
``borderline``     absent at the latest reading but within the vital's ``exit_margin``
                   of the limit, present in the previous period: no course is stated
                   (Issue #3964)
``absent``         absent now and in the previous period (a brief abnormal reading
                   earlier in the period is stated time-qualified by the
                   Subjective, not as a course)
``unobserved_before`` present now, the previous period did not record the vital
``unknown``        the period did not record the vital
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.timeutil import parse_iso_datetime

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext

__all__ = ["finding_states"]

_AVPU = frozenset({"A", "V", "P", "U"})


def _measured(reading: Any, vital: str) -> bool:
    """Whether ``reading`` recorded ``vital`` (a blank AVPU is not a value; the
    oxygen state comes with the SpO2 reading)."""
    if vital == "consciousness":
        return str(_o(reading, "consciousness_level", "") or "") in _AVPU
    if vital == "on_oxygen":
        return _o(reading, "spo2", None) is not None
    return _o(reading, vital, None) is not None


def _series(
    ctx: NarrativeContext, readings: list, before: list | tuple = (), after: list | tuple = ()
) -> list[dict[str, set[str]]]:
    """The state of each reading; a newborn's low counts only when sustained
    over its neighbours, those of ``before`` / ``after`` (the readings preceding
    / following ``readings``) included (Issue #3563)."""
    from clinosim.modules.document.narrative._progress_exam import period_states

    chain = [*before, *readings, *after]
    offset = len(before)
    return [period_states(ctx, [r], chain[: offset + i], chain[offset + i + 1 :]) for i, r in enumerate(readings)]


def finding_states(ctx: NarrativeContext, readings: list, previous: list) -> dict[tuple[str, str], str]:
    """The state of each course item, keyed ``(vital, state)`` as in
    ``progress_exam.yaml`` ``course_items``, from the readings of the note's
    period and of the previous one (oldest first)."""
    from clinosim.modules.document.narrative._progress_exam import in_exit_band, progress_exam_rules

    rules = progress_exam_rules()
    window = rules.course_state
    as_of = getattr(ctx, "authored_datetime", None)
    cur_series, prev_series = _series(ctx, readings, previous), _series(ctx, previous, after=readings)
    sustained = list(range(len(readings)))
    if as_of is not None:
        start = as_of - timedelta(hours=window.resolved_window_hours)
        sustained = [
            i
            for i, r in enumerate(readings)
            if (ts := parse_iso_datetime(_o(r, "timestamp", None), lenient=True)) is not None and ts > start
        ]
    when = as_of or _o(getattr(ctx, "encounter", None), "admission_datetime", None)
    out: dict[tuple[str, str], str] = {}
    for item in rules.course_items:
        key = (item.vital, item.state)

        def flags(rows: list, series: list[dict[str, set[str]]], idx: list[int] | None = None) -> list[bool]:
            picked = range(len(rows)) if idx is None else idx
            return [item.state in series[i].get(item.vital, set()) for i in picked if _measured(rows[i], item.vital)]

        def borderline(rows: list, idx: list[int] | None = None) -> list[bool]:
            """Per measured reading: inside the limit but within the exit margin."""
            picked = range(len(rows)) if idx is None else idx
            return [
                in_exit_band(ctx, rows[i], item.vital, item.state, when)
                for i in picked
                if _measured(rows[i], item.vital)
            ]

        cur, prev = flags(readings, cur_series), flags(previous, prev_series)
        if not cur:
            out[key] = "unknown"
        elif cur[-1]:
            # Issue #3964: a previous period that only came near the limit is
            # not clear of it, so the finding is not new.
            clear = not any(borderline(previous))
            out[key] = "persisting" if any(prev) or not clear else ("new" if prev else "unobserved_before")
        elif any(prev):
            # Issue #3964: the course is stated only once the value left the
            # limit by its margin, over the whole sustained window.
            held = flags(readings, cur_series, sustained)
            near = borderline(readings, sustained)
            if borderline(readings)[-1]:
                out[key] = "borderline"
            else:
                ok = len(held) >= window.resolved_min_readings and not any(held) and not any(near)
                out[key] = "resolved" if ok else "improving"
        else:
            out[key] = "absent"
    return out
