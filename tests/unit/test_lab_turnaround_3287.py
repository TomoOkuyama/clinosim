"""Inpatient lab turnaround is calibrated to laboratory benchmarks (Issue #3287).

Benchmarks (CAP Q-Probes, as summarised in Hawkins RC, Clin Biochem Rev
2007;28:179-194):

- routine early-morning inpatient collections, 657 institutions (Dale,
  Steindel, Walsh 1998): institutional median total turnaround 73 min,
  interquartile range 58-92 min;
- emergency-department STAT orders, 693 laboratories (Steindel, Howanitz
  2001): median laboratory 90%-completion time, order to report, 69 min for
  potassium and 55 min for hemoglobin.

The hospital-state delay model used to multiply the base processing time by
an uncapped congestion x staffing factor, so a saturated morning queue on the
night shift returned routine chemistry after about 12 hours.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
import yaml

from clinosim import determinism
from clinosim.modules.facility.hospital_state import HospitalState
from clinosim.modules.order.engine import calculate_result_time_from_state
from clinosim.types.encounter import Order, OrderType

pytestmark = pytest.mark.unit

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "clinosim" / "config"
_HOSPITAL_CONFIGS = ["hospital_operations.yaml", "hospital_small.yaml", "hospital_large.yaml"]

# Cited ranges (minutes).
_ROUTINE_MEDIAN_RANGE = (58.0, 92.0)  # Dale 1998: institutional median IQR
_ROUTINE_P90_MAX = 120.0
_STAT_P90_MAX = 69.0  # Steindel & Howanitz 2001: potassium 90% completion


def _ops(name: str) -> dict:
    with open(_CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _turnaround_minutes(ops: dict, urgency: str, ordered: datetime, n: int = 400) -> np.ndarray:
    """Turnaround of ``n`` orders placed on a saturated laboratory."""
    state = HospitalState()
    out = []
    for i in range(n):
        order = Order(
            order_id=f"ORD-{i}",
            order_type=OrderType.LAB,
            display_name="Creatinine",
            urgency=urgency,
            ordered_datetime=ordered,
        )
        rng = determinism.default_rng(1000 + i)
        result = calculate_result_time_from_state(order, state, ops, rng)
        out.append((result - ordered).total_seconds() / 60.0)
    return np.array(out)


# Saturday 11:00 (weekend, day shift) and Saturday 06:00 (night shift, morning rush).
_SAT_LATE_MORNING = datetime(2026, 1, 10, 11, 0)
_SAT_EARLY_MORNING = datetime(2026, 1, 10, 6, 0)


@pytest.mark.parametrize("config", _HOSPITAL_CONFIGS)
def test_routine_turnaround_matches_the_morning_collection_benchmark(config: str) -> None:
    tat = _turnaround_minutes(_ops(config), "routine", _SAT_LATE_MORNING)
    assert np.percentile(tat, 90) <= _ROUTINE_P90_MAX
    assert np.median(tat) <= _ROUTINE_MEDIAN_RANGE[1]


def test_default_hospital_routine_median_is_within_the_benchmark_range() -> None:
    tat = _turnaround_minutes(_ops("hospital_operations.yaml"), "routine", _SAT_LATE_MORNING)
    lo, hi = _ROUTINE_MEDIAN_RANGE
    assert lo <= np.median(tat) <= hi


@pytest.mark.parametrize("config", _HOSPITAL_CONFIGS)
def test_stat_is_faster_than_routine_and_within_the_stat_benchmark(config: str) -> None:
    ops = _ops(config)
    stat = _turnaround_minutes(ops, "stat", _SAT_EARLY_MORNING)
    routine = _turnaround_minutes(ops, "routine", _SAT_LATE_MORNING)
    assert np.percentile(stat, 90) <= _STAT_P90_MAX
    assert np.median(stat) < np.median(routine)


def test_morning_draw_is_resulted_before_rounds() -> None:
    """A 06:00 routine draw on a saturated night-shift laboratory is out within two hours."""
    tat = _turnaround_minutes(_ops("hospital_operations.yaml"), "routine", _SAT_EARLY_MORNING)
    assert tat.max() <= 2 * _ROUTINE_P90_MAX
    assert np.percentile(tat, 90) <= _ROUTINE_P90_MAX


def test_resource_without_limits_keeps_the_generic_caps() -> None:
    """Imaging has no ``delay_limits`` entry; its delay is still bounded by the generic routine cap."""
    ops = _ops("hospital_operations.yaml")
    assert "ct" not in ops.get("delay_limits", {})
    state = HospitalState()
    state.update_for_time(_SAT_EARLY_MORNING, ops)
    for _ in range(20):
        state.add_to_queue("ct", ops, until=_SAT_EARLY_MORNING + timedelta(hours=6))
    lab_limit = ops["delay_limits"]["lab"]["max_delay_min"]["routine"]
    assert state.calculate_delay("ct", "routine", ops) > lab_limit
