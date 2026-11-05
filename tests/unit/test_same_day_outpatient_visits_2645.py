"""Issue #2645: a patient's same-day clinic visits do not overlap."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator._scheduling_thresholds import OUTPATIENT_SAME_DAY_GAP_MIN
from clinosim.simulator.phases._healthcare_calendar import next_visit_start, specialty_departments_to_visit

pytestmark = pytest.mark.unit


def test_a_specialty_in_the_same_department_is_the_same_visit() -> None:
    assert specialty_departments_to_visit("internal_medicine", [("psychiatry", "internal_medicine")]) == []


def test_two_specialties_in_one_other_department_are_one_visit() -> None:
    planned = specialty_departments_to_visit(
        "internal_medicine", [("cardiology", "cardiology"), ("heart_failure", "cardiology"), ("oncology", "oncology")]
    )
    assert planned == [("cardiology", "cardiology"), ("oncology", "oncology")]


def test_the_next_visit_starts_after_the_previous_one_ends() -> None:
    end = datetime(2025, 10, 11, 10, 58)
    assert next_visit_start(end) == end + timedelta(minutes=OUTPATIENT_SAME_DAY_GAP_MIN)
