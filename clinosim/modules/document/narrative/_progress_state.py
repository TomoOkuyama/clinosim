"""One state per vital finding of a progress note (Issue #3541).

The Subjective sentences (fever, consciousness) and the Assessment's course
line of a daily note are written from the table :func:`finding_states`
returns, so one note never says a finding both resolved and persists, or new
and persistent. The table is judged only on the readings up to the note's
authored time.

States of an ``progress_exam.yaml`` course item:

``new``            present at the latest reading, absent over the previous period
``persisting``     present at the latest reading and over the previous period
``improving``      absent at the latest reading, present in the previous period,
                   but not yet absent over the sustained window (``course_state``)
``resolved``       absent over the sustained window, with enough readings
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
    from clinosim.modules.document.narrative._progress_exam import progress_exam_rules

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
    out: dict[tuple[str, str], str] = {}
    for item in rules.course_items:
        key = (item.vital, item.state)

        def flags(rows: list, series: list[dict[str, set[str]]], idx: list[int] | None = None) -> list[bool]:
            picked = range(len(rows)) if idx is None else idx
            return [item.state in series[i].get(item.vital, set()) for i in picked if _measured(rows[i], item.vital)]

        cur, prev = flags(readings, cur_series), flags(previous, prev_series)
        if not cur:
            out[key] = "unknown"
        elif cur[-1]:
            out[key] = "persisting" if any(prev) else ("new" if prev else "unobserved_before")
        elif any(prev):
            held = flags(readings, cur_series, sustained)
            ok = len(held) >= window.resolved_min_readings and not any(held)
            out[key] = "resolved" if ok else "improving"
        else:
            out[key] = "absent"
    return out
