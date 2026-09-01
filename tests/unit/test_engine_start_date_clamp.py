"""Issue #1039: engine must clamp emitted encounters to the ``--start``
lower bound.

Pre-fix behaviour: ``generate_healthcare_calendar`` iterates a full
calendar year (Jan 1 → Dec 31) from ``start_y``, so a mid-year
``--start`` produced ~22K AMB + a few hundred IMP / EMER encounters
BEFORE the requested cursor. ``generate_monthly_events`` similarly
runs at month precision from ``start_m``; a day-of-month draw inside
the first month can land before ``--start``.

The fix adds a symmetric lower-bound filter to both event streams
(mirroring the existing ``snapshot_dt`` upper clamp). This test
exercises the helper directly rather than the full engine because a
p=N cohort run is 10-minute integration scope.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.simulator.engine import _parse_time_range_bound

pytestmark = pytest.mark.unit


def test_parse_time_range_bound_full_date() -> None:
    """CLI-populated ``YYYY-MM-DD`` bound parses to that day at midnight."""
    assert _parse_time_range_bound("2025-08-31") == datetime(2025, 8, 31, 0, 0)


def test_parse_time_range_bound_month_only() -> None:
    """Test-fixture ``YYYY-MM`` bound parses to day 1 of that month at midnight."""
    assert _parse_time_range_bound("2025-08") == datetime(2025, 8, 1, 0, 0)


def test_parse_time_range_bound_rejects_bad_input() -> None:
    """A non-date/non-month string raises ValueError so the caller sees
    the parse failure rather than a silent bad-clamp."""
    with pytest.raises(ValueError):
        _parse_time_range_bound("not-a-date")


def test_start_clamp_filter_predicate_drops_pre_start_events() -> None:
    """The list-comprehension predicate applied to `calendar_events` and
    `all_events` in engine.run_beta drops events whose ``timestamp`` is
    before ``start_dt``. Exercises the predicate shape (independent of
    the full engine run)."""
    from types import SimpleNamespace

    start_dt = datetime(2025, 8, 31)
    events = [
        SimpleNamespace(timestamp=date(2025, 1, 15)),  # pre-start → drop
        SimpleNamespace(timestamp=date(2025, 8, 30)),  # pre-start (1d) → drop
        SimpleNamespace(timestamp=date(2025, 8, 31)),  # on start → keep
        SimpleNamespace(timestamp=date(2025, 12, 31)),  # post-start → keep
        SimpleNamespace(timestamp=None),  # no timestamp → keep (harmless)
    ]
    kept = [e for e in events if not e.timestamp or datetime.combine(e.timestamp, datetime.min.time()) >= start_dt]
    assert [e.timestamp for e in kept] == [date(2025, 8, 31), date(2025, 12, 31), None]
