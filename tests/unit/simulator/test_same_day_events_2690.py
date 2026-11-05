"""Issue #2690: same-day visits from different events do not overlap."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.simulator._scheduling_thresholds import OUTPATIENT_SAME_DAY_GAP_MIN
from clinosim.simulator.phases._healthcare_calendar import note_outpatient_visit, place_outpatient_visit

pytestmark = pytest.mark.unit


def _record(start: datetime, end: datetime) -> SimpleNamespace:
    return SimpleNamespace(encounters=[SimpleNamespace(admission_datetime=start, discharge_datetime=end)])


def test_a_second_visit_starts_after_the_first_ends() -> None:
    ends: dict = {}
    note_outpatient_visit(ends, "P1", _record(datetime(2025, 3, 1, 10, 11), datetime(2025, 3, 1, 10, 54)))
    start = place_outpatient_visit(ends, "P1", datetime(2025, 3, 1, 10, 23))
    assert start == datetime(2025, 3, 1, 10, 54) + timedelta(minutes=OUTPATIENT_SAME_DAY_GAP_MIN)


def test_a_visit_after_the_first_keeps_its_time() -> None:
    ends: dict = {}
    note_outpatient_visit(ends, "P1", _record(datetime(2025, 3, 1, 10, 0), datetime(2025, 3, 1, 10, 20)))
    assert place_outpatient_visit(ends, "P1", datetime(2025, 3, 1, 14, 0)) == datetime(2025, 3, 1, 14, 0)


def test_other_patients_and_days_are_independent() -> None:
    ends: dict = {}
    note_outpatient_visit(ends, "P1", _record(datetime(2025, 3, 1, 10, 0), datetime(2025, 3, 1, 10, 40)))
    assert place_outpatient_visit(ends, "P2", datetime(2025, 3, 1, 10, 5)) == datetime(2025, 3, 1, 10, 5)
    assert place_outpatient_visit(ends, "P1", datetime(2025, 3, 2, 10, 5)) == datetime(2025, 3, 2, 10, 5)
