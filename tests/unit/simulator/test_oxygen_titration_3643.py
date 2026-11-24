"""Oxygen is titrated one step at a time towards the target SpO2 (Issue #3643)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules
from clinosim.simulator.vitals_pipeline import o2_target

pytestmark = pytest.mark.unit

T0 = datetime(2026, 1, 1, 8, 0)
TARGET = 92.0
OFF = (False, None, "")
MASK = (True, 8.0, "simple_mask")


def _gain(r: float, f: float) -> float:
    return min(98.0, r + 1.5 * f)


def _run(c: OxygenCourse, spo2: float, hours: float, draw=OFF, target: float = TARGET, gain=_gain):
    return c.resolve(T0 + timedelta(hours=hours), spo2, target, draw, gain)


def test_rules_have_step_sizes() -> None:
    r = oxygen_course_rules()
    assert r.up_step_lpm > 0 and r.down_step_lpm > 0
    # One downward step never takes a satisfactory SpO2 below the target.
    assert r.down_step_lpm * 1.5 < r.down_margin_spo2 + 1e-9


def test_reading_below_target_raises_flow_by_one_step_not_to_the_draw() -> None:
    c = OxygenCourse()
    _run(c, 80.0, 0, (True, 2.0, "nasal_cannula"))
    step = oxygen_course_rules().up_step_lpm
    on, flow, _device, _spo2 = _run(c, 80.0, 1, (True, 10.0, "non-rebreather"))
    assert on and flow == 2.0 + step


def test_flow_never_exceeds_the_draw() -> None:
    c = OxygenCourse()
    _run(c, 80.0, 0, (True, 2.0, "nasal_cannula"))
    flows = [_run(c, 80.0, k, (True, 4.0, "nasal_cannula"))[1] for k in range(1, 12)]
    assert max(f for f in flows if f is not None) == 4.0


def test_device_follows_the_stepped_flow() -> None:
    c = OxygenCourse()
    _run(c, 80.0, 0, (True, 2.0, "nasal_cannula"))
    devices = {}
    for k in range(1, 30):
        _on, flow, device, _s = _run(c, 70.0, k, (True, 10.0, "non-rebreather"))
        devices[flow] = device
    assert devices[3.0] == "nasal_cannula" and devices[6.0] == "simple_mask" and devices[10.0] == "non-rebreather"


def test_start_from_room_air_still_uses_the_draw() -> None:
    c = OxygenCourse()
    assert _run(c, 80.0, 0, (True, 9.0, "non-rebreather"))[:3] == (True, 9.0, "non-rebreather")


def test_no_upward_jump_after_a_satisfactory_reading() -> None:
    c = OxygenCourse()
    _run(c, 80.0, 0, (True, 10.0, "non-rebreather"))
    prev = 10.0
    rules = oxygen_course_rules()
    for k in range(1, 30):
        raw = 92.5 if k % 3 else 78.0
        _on, flow, _d, _s = _run(c, raw, k * 1.0, (True, 10.0, "non-rebreather"))
        assert flow is not None and flow - prev <= rules.up_step_lpm + 1e-9
        prev = flow


def test_98_percent_on_10_lpm_reaches_the_band_within_hours() -> None:
    c = OxygenCourse()
    _run(c, 85.0, 0, (True, 10.0, "non-rebreather"))
    spo2 = 98.0
    hours = 0.0
    while spo2 > TARGET + oxygen_course_rules().down_margin_spo2 and hours < 48:
        hours += 1.0
        _on, _f, _d, spo2 = _run(c, 94.0, hours)
    assert hours <= 24
    assert TARGET <= spo2 <= TARGET + oxygen_course_rules().down_margin_spo2


def test_copd_target_is_respected() -> None:
    target = o2_target("copd_exacerbation")
    cap = lambda r, f: min(94.0, r + 1.5 * f)  # noqa: E731
    c = OxygenCourse()
    _run(c, 80.0, 0, (True, 6.0, "simple_mask"), target, cap)
    for k in range(1, 80):
        _on, _f, _d, spo2 = _run(c, 87.0, k * 1.0, OFF, target, cap)
        assert spo2 >= target
    assert c.flow is not None and c.flow < 6.0
