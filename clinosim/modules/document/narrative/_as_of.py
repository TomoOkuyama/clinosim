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

__all__ = ["in_force_at"]


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
