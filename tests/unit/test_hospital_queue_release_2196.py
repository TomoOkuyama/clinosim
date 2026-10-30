"""Hospital resource queues drain as work completes (Issue #2196)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.facility.hospital_state import HospitalState

pytestmark = pytest.mark.unit

_OPS = {
    "resource_capacity": {"lab_analyzers": 4},
    "base_processing_time": {"lab_routine": 55},
    "daily_patterns": {"morning_lab_rush": {"hours": [6, 8], "lab_queue_delta": 0.35}},
}


def test_queue_returns_to_baseline_after_the_work_completes() -> None:
    hs = HospitalState()
    t0 = datetime(2025, 3, 3, 13, 0)  # Monday afternoon, no daily pattern active
    hs.update_for_time(t0, _OPS)
    baseline = hs.lab_queue
    hs.add_to_queue("lab", _OPS, until=t0 + timedelta(minutes=60))
    assert hs.lab_queue == pytest.approx(baseline + 0.25)
    hs.update_for_time(t0 + timedelta(minutes=61), _OPS)
    assert hs.lab_queue == pytest.approx(baseline)


def test_queue_stays_bounded_over_a_long_run() -> None:
    hs = HospitalState()
    t = datetime(2024, 1, 2, 13, 0)
    for _ in range(3 * 365):
        hs.update_for_time(t, _OPS)
        hs.add_to_queue("lab", _OPS)  # default hold: the resource's base processing time
        t += timedelta(days=1)
    hs.update_for_time(t, _OPS)
    assert hs.lab_queue < 0.5


def test_daily_pattern_applies_while_active_and_does_not_accumulate() -> None:
    hs = HospitalState()
    noon = datetime(2025, 3, 4, 12, 0)  # Tuesday
    hs.update_for_time(noon, _OPS)
    baseline = hs.lab_queue
    for minute in range(10):
        hs.update_for_time(datetime(2025, 3, 4, 7, minute), _OPS)
    assert hs.lab_queue == pytest.approx(baseline + 0.35)
    hs.update_for_time(noon + timedelta(days=1), _OPS)
    assert hs.lab_queue == pytest.approx(baseline)


def test_bed_occupancy_pattern_is_transient() -> None:
    ops = {"daily_patterns": {"afternoon_discharge": {"hours": [10, 14], "bed_occupancy_delta": -0.05}}}
    hs = HospitalState()
    hs.update_for_time(datetime(2025, 3, 4, 9, 0), ops)
    before = hs.bed_occupancy
    for minute in range(10):
        hs.update_for_time(datetime(2025, 3, 4, 11, minute), ops)
    assert hs.bed_occupancy == pytest.approx(before - 0.05)
    hs.bed_occupancy += 0.1  # an admission recorded by the dispatcher
    hs.update_for_time(datetime(2025, 3, 4, 15, 0), ops)
    assert hs.bed_occupancy == pytest.approx(before + 0.1)
