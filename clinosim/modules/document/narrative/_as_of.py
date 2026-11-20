"""What a document knew at its authored time (Issue #3236).

A narrative document reflects only the data recorded up to the time it was
written (``NarrativeContext.authored_datetime``). The helpers here pick that
data out of the stay-wide CIF lists so that no builder reads the last entry
of the stay by position.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from clinosim.modules._shared import get_attr_or_key
from clinosim.timeutil import parse_iso_datetime

__all__ = ["in_force_at", "recorded_by", "results_after", "results_known_at"]


def in_force_at(records: list[Any], as_of: datetime | None, key: str = "date") -> Any | None:
    """The record in force at ``as_of``: the latest one whose ``key`` time is
    at or before ``as_of`` (a date-only value counts from the start of its
    day). Before the first dated record, the first record (the admission
    assessment). ``as_of`` None (no authored time): the last record. ``None``
    for an empty list."""
    rows = list(records or [])
    if not rows:
        return None
    if as_of is None:
        return rows[-1]
    best: Any | None = None
    best_at: datetime | None = None
    for row in rows:
        at = parse_iso_datetime(get_attr_or_key(row, key, None), lenient=True)
        if at is None or at > as_of:
            continue
        if best_at is None or at >= best_at:
            best, best_at = row, at
    return best if best is not None else rows[0]


def recorded_by(records: list[Any], as_of: datetime | None, key: str = "timestamp") -> list[Any]:
    """The records whose ``key`` time is at or before ``as_of`` (Issue #3241):
    what existed when a document was written. A record without a parseable
    time is kept (it cannot be placed after the document); ``as_of`` None (no
    authored time): every record."""
    rows = list(records or [])
    if as_of is None:
        return rows
    kept: list[Any] = []
    for row in rows:
        at = parse_iso_datetime(get_attr_or_key(row, key, None), lenient=True)
        if at is None or at <= as_of:
            kept.append(row)
    return kept


def _naive(when: datetime | None) -> datetime | None:
    return when.replace(tzinfo=None) if when is not None else None


def _result_at(row: Any) -> datetime | None:
    return _naive(parse_iso_datetime(get_attr_or_key(row, "result_datetime", None), lenient=True))


def results_known_at(labs: list[Any], as_of: datetime | None) -> list[Any]:
    """The lab results reported at or before ``as_of`` (Issue #3396): a test
    drawn at the visit is resulted some hours later, so a note authored at the
    visit cannot quote it. A result without a parseable time is kept; ``as_of``
    None (no authored time): every result."""
    rows = list(labs or [])
    cutoff = _naive(as_of)
    if cutoff is None:
        return rows
    return [r for r in rows if (at := _result_at(r)) is None or at <= cutoff]


def results_after(labs: list[Any], as_of: datetime | None) -> list[Any]:
    """The lab results reported after ``as_of``: the complement of
    :func:`results_known_at` (what the note can only word as pending)."""
    cutoff = _naive(as_of)
    if cutoff is None:
        return []
    return [r for r in list(labs or []) if (at := _result_at(r)) is not None and at > cutoff]
