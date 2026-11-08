"""Canonical parsing of CIF timestamps (Issue #2841).

CIF timestamps reach their readers either as ``datetime`` objects (in-memory
dataclasses) or as ISO 8601 strings (after the structural-CIF JSON round
trip). :func:`parse_iso_datetime` is the one reader for both shapes; do not
write a local ``_parse_dt`` helper.

The writing side (FHIR ``dateTime`` / ``instant`` strings with the country
time zone) lives in ``clinosim/modules/output/fhir_r4/lib/fhir_time.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any


def parse_iso_datetime(value: Any, *, lenient: bool = False) -> datetime | None:
    """Parse a CIF timestamp into a ``datetime``; ``None`` when absent or unparseable.

    Accepted forms:

    * ``datetime`` — returned unchanged (its ``tzinfo``, if any, is kept).
    * ``date`` — midnight of that day, naive.
    * ISO 8601 string (``datetime.fromisoformat``) — a trailing ``Z`` means
      UTC; an offset such as ``+09:00`` gives an aware result, no offset a
      naive one. The time zone is never added, removed or converted.
    * a date-only string (``"2025-01-01"``) — midnight of that day, naive.
    * ``None``, ``""``, any other type and any other string — ``None``.

    ``lenient=True`` additionally strips surrounding whitespace and, when the
    whole string does not parse, falls back to its first ten characters as a
    date (``"2025-01-01 garbage"`` → midnight of 2025-01-01). Narrative
    day-bucketing readers use it; the default is strict.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str):
        return None
    s = value.strip() if lenient else value
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        if not lenient:
            return None
    try:
        return datetime.fromisoformat(s[:10])
    except ValueError:
        return None
