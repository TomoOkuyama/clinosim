"""Issue #2635: an ED lab is never resulted before it is ordered."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator._ed_thresholds import ED_LAB_MIN_TURNAROUND_MIN
from clinosim.simulator.emergency import ed_lab_result_time

pytestmark = pytest.mark.unit

_VISIT = datetime(2025, 3, 25, 10, 0)


def test_a_result_drawn_before_its_order_follows_the_order() -> None:
    ordered = _VISIT + timedelta(minutes=28)
    resulted = ed_lab_result_time(_VISIT, ordered, result_offset_min=25)
    assert resulted == ordered + timedelta(minutes=ED_LAB_MIN_TURNAROUND_MIN)


def test_a_result_drawn_after_the_turnaround_keeps_its_time() -> None:
    ordered = _VISIT + timedelta(minutes=10)
    assert ed_lab_result_time(_VISIT, ordered, result_offset_min=50) == _VISIT + timedelta(minutes=50)


def test_the_minimum_turnaround_is_a_plausible_stat_time() -> None:
    assert 10 <= ED_LAB_MIN_TURNAROUND_MIN <= 30
