"""Oxygen is titrated down while the SpO2 on oxygen stays above the band (Issue #3632)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules
from clinosim.simulator.vitals_pipeline import o2_target

pytestmark = pytest.mark.unit

T0 = datetime(2026, 1, 1, 8, 0)
TARGET = 92.0
OFF = (False, None, "")


def _gain(r: float, f: float) -> float:
    return min(98.0, r + 1.5 * f)


def _run(course: OxygenCourse, spo2: float, hours: float, draw=OFF):
    return course.resolve(T0 + timedelta(hours=hours), spo2, TARGET, draw, _gain)


def test_rules_come_from_yaml() -> None:
    r = oxygen_course_rules()
    assert r.down_margin_spo2 > 0 and r.down_hours > 0 and r.down_min_readings >= 1 and r.min_flow_lpm > 0


def test_flow_comes_down_step_by_step_and_device_follows() -> None:
    c = OxygenCourse()
    r = oxygen_course_rules()
    _run(c, 80.0, 0, (True, 10.0, "non-rebreather"))
    seen: list[tuple[float | None, str]] = []
    # Room-air SpO2 has recovered to 94 (below the wean threshold would stop it
    # at >= 93, so keep it at 92.5: satisfactory on oxygen, not yet weaned).
    for k in range(1, 200):
        on, flow, device, spo2 = _run(c, 92.5, k * 4.0)
        assert on
        assert flow is not None
        # Stays at or above the target while titrated.
        assert spo2 >= TARGET
        if not seen or seen[-1] != (flow, device):
            seen.append((flow, device))
        if flow <= r.min_flow_lpm:
            break
    flows = [f for f, _ in seen if f is not None]
    assert flows == sorted(flows, reverse=True) and flows[0] == 10.0
    # One flowmeter step at a time.
    assert all(abs((a - b) - r.flow_step_lpm) < 1e-9 for a, b in zip(flows, flows[1:], strict=False))
    devices = [d for _, d in seen]
    assert devices[0] == "non-rebreather"
    assert "simple_mask" in devices and devices[-1] == "nasal_cannula"


def test_no_lowering_before_the_span_has_elapsed() -> None:
    c = OxygenCourse()
    r = oxygen_course_rules()
    _run(c, 80.0, 0, (True, 6.0, "simple_mask"))
    _run(c, 92.5, 1)
    on, flow, _d, _s = _run(c, 92.5, 1 + r.down_hours / 2)
    assert flow == 6.0


def test_no_lowering_while_spo2_on_oxygen_is_within_the_band() -> None:
    c = OxygenCourse()
    _run(c, 80.0, 0, (True, 6.0, "simple_mask"))
    # Room air 80 -> 89 on 6 L/min: not above target + margin.
    for k in range(1, 30):
        assert _run(c, 80.0, k * 4.0)[1] == 6.0


def test_never_below_the_minimum_flow() -> None:
    c = OxygenCourse()
    r = oxygen_course_rules()
    _run(c, 80.0, 0, (True, 1.0, "nasal_cannula"))
    for k in range(1, 40):
        assert _run(c, 92.5, k * 4.0)[1] >= r.min_flow_lpm


def test_copd_band_is_honoured() -> None:
    target = o2_target("copd_exacerbation")
    c = OxygenCourse()
    cap = lambda r, f: min(94.0, r + 1.5 * f)  # noqa: E731
    c.resolve(T0, 80.0, target, (True, 6.0, "simple_mask"), cap)
    flow = 6.0
    for k in range(1, 60):
        _on, flow, _d, spo2 = c.resolve(T0 + timedelta(hours=4 * k), 87.0, target, OFF, cap)
        assert spo2 >= target
    assert flow < 6.0


def test_no_ward_reading_at_icu_level_after_a_recovering_stay() -> None:
    """A recovering stay's flow reaches below 8 L/min within days, not weeks."""
    c = OxygenCourse()
    _run(c, 78.0, 0, (True, 10.0, "non-rebreather"))
    flow = 10.0
    for k in range(1, 6 * 6):  # six days, readings every 4 h
        _on, flow, _d, _s = _run(c, 92.5, k * 4.0)
    assert flow is not None and flow < 8.0
