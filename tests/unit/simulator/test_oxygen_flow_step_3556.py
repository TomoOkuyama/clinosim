"""Recorded oxygen flows are in flowmeter steps, SpO2 uses the unrounded flow (Issue #3556)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules, round_oxygen_flow
from clinosim.simulator.vitals_pipeline import resolve_oxygen

pytestmark = pytest.mark.unit


def test_step_comes_from_yaml() -> None:
    assert oxygen_course_rules().flow_step_lpm == 0.5


@pytest.mark.parametrize("raw,expected", [(2.9, 3.0), (3.2, 3.0), (3.3, 3.5), (6.74, 6.5), (10.0, 10.0)])
def test_flow_rounds_to_step(raw: float, expected: float) -> None:
    assert round_oxygen_flow(raw) == expected


def test_none_and_zero_pass_through_and_floor_is_one_step() -> None:
    assert round_oxygen_flow(None) is None
    assert round_oxygen_flow(0.0) is None
    assert round_oxygen_flow(0.1) == 0.5


def test_course_keeps_unrounded_flow_and_spo2_uses_it() -> None:
    t0 = datetime(2026, 1, 1, 8)

    class _S:
        oxygenation_impairment = 0.0

    resolved = resolve_oxygen(OxygenCourse(), [(0, t0, 85.0, (True, 2.9, "nasal_cannula"))], _S(), "pneumonia")
    on, flow, _device, spo2 = resolved[0]
    assert on and flow == 2.9
    assert round_oxygen_flow(flow) == 3.0
    from clinosim.simulator.vitals_pipeline import spo2_on_oxygen

    assert spo2 == spo2_on_oxygen(85.0, 2.9, _S(), "pneumonia")
