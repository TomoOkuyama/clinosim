"""Supplemental oxygen is a state of the stay, not a per-reading flag (Issue #3469)."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.simulator.oxygen_course import OxygenCourse, oxygen_course_rules
from clinosim.simulator.vitals_pipeline import _o2_for, o2_target, resolve_oxygen

pytestmark = pytest.mark.unit

T0 = datetime(2026, 1, 1, 8, 0)
TARGET = 92.0
NC = (True, 2.0, "nasal_cannula")
MASK = (True, 8.0, "simple_mask")
OFF = (False, None, "")


def _gain(r: float, f: float) -> float:
    return min(98.0, r + 1.5 * f)


def _run(course: OxygenCourse, spo2: float, hours: float, draw) -> tuple[bool, float | None, str, float]:
    return course.resolve(T0 + timedelta(hours=hours), spo2, TARGET, draw, _gain)


def test_starts_below_target_and_holds_through_a_noisy_reading() -> None:
    c = OxygenCourse()
    assert _run(c, 95.0, 0, OFF)[0] is False
    assert _run(c, 90.0, 4, NC)[:3] == (True, 2.0, "nasal_cannula")
    # A reading above the target is not a wean: oxygen stays on.
    on, flow, device, spo2 = _run(c, 95.0, 8, OFF)
    assert (on, flow, device) == (True, 2.0, "nasal_cannula")
    assert spo2 == _gain(95.0, 2.0)


def test_weans_only_after_sustained_satisfactory_readings() -> None:
    c = OxygenCourse()
    _run(c, 90.0, 0, NC)
    rules = oxygen_course_rules()
    assert _run(c, 95.0, 1, OFF)[0] is True
    assert _run(c, 95.0, 1 + rules.wean_hours - 1, OFF)[0] is True
    assert _run(c, 95.0, 1 + rules.wean_hours, OFF)[0] is False
    assert _run(c, 95.0, 30, OFF)[:3] == (False, None, "")


def test_a_dip_resets_the_wean_window() -> None:
    c = OxygenCourse()
    _run(c, 90.0, 0, NC)
    _run(c, 95.0, 1, OFF)
    _run(c, 91.0, 8, NC)  # below target again: the window restarts
    assert _run(c, 95.0, 14, OFF)[0] is True
    assert _run(c, 95.0, 14 + oxygen_course_rules().wean_hours, OFF)[0] is False


def test_restart_after_wean_is_a_new_course() -> None:
    c = OxygenCourse()
    _run(c, 90.0, 0, NC)
    _run(c, 95.0, 1, OFF)
    _run(c, 95.0, 20, OFF)
    assert c.on is False
    assert _run(c, 89.0, 30, MASK)[:3] == (True, 8.0, "simple_mask")


def test_titrates_up_never_down() -> None:
    c = OxygenCourse()
    _run(c, 85.0, 0, NC)
    # On 2 L/min the recorded SpO2 is still below the target: flow goes up.
    on, flow, device, _ = _run(c, 80.0, 2, MASK)
    assert (on, flow, device) == (True, 8.0, "simple_mask")
    # A later, smaller draw does not lower it.
    assert _run(c, 89.0, 4, NC)[1] == 8.0


def test_no_flicker_with_noisy_readings() -> None:
    rng = np.random.default_rng(7)
    c = OxygenCourse()
    flags = []
    for h in range(0, 48, 2):
        raw = float(rng.normal(91.0, 2.0))
        draw = (True, 2.0, "nasal_cannula") if raw < TARGET else OFF
        flags.append(c.resolve(T0 + timedelta(hours=h), raw, TARGET, draw, _gain)[0])
    flips = sum(a != b for a, b in zip(flags, flags[1:], strict=False))
    assert flips <= 2


def test_resolve_oxygen_orders_readings_by_time_and_keeps_draws() -> None:
    class S:
        oxygenation_impairment = 0.0

    # Readings made out of order (routine rounds first, monitor readings after).
    readings = [
        (0, T0 + timedelta(hours=6), 96.0, OFF),
        (1, T0, 88.0, NC),
        (2, T0 + timedelta(hours=3), 96.0, OFF),
    ]
    out = resolve_oxygen(OxygenCourse(), readings, S(), "pneumonia")
    assert [out[k][0] for k in (1, 2, 0)] == [True, True, True]


def test_o2_for_draws_are_unchanged() -> None:
    """The per-reading dispatcher draws exactly as before (flow only below target)."""
    a, b = np.random.default_rng(1), np.random.default_rng(1)
    _o2_for(95.0, "pneumonia", a)
    assert a.random() == b.random()  # no draw above the target
    _o2_for(85.0, "pneumonia", a)
    b.uniform(0, 1)
    assert a.random() == b.random()  # one draw below it


def test_copd_target() -> None:
    assert o2_target("copd_exacerbation") == 88.0
    assert o2_target("pneumonia") == 92.0
