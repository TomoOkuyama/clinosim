"""YAML in_hospital_mortality is the cumulative risk over a target_los stay, not a per-day rate times weights."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.simulator.discharge_gate import _evaluate_mortality
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


class _FixedRng:
    """Returns a constant draw so _evaluate_mortality exposes its hazard threshold."""

    def __init__(self) -> None:
        self.value = 0.0

    def random(self) -> float:
        return self.value


def _daily_hazard(rate: float, day: int, target_los: int) -> float:
    """Bisect the draw threshold at which _evaluate_mortality flips to death."""
    rng = _FixedRng()
    patient = SimpleNamespace(age=60)
    state = PhysiologicalState(perfusion_status=1.0)
    lo, hi = 0.0, 1.0
    for _ in range(60):
        rng.value = (lo + hi) / 2
        died = _evaluate_mortality(
            state, patient, severity="moderate", day=day, rng=rng, disease_mortality_rate=rate, target_los=target_los
        )
        lo, hi = (rng.value, hi) if died else (lo, rng.value)
    return lo


@pytest.mark.parametrize("target_los", [2, 3, 4, 6, 8, 12, 20])
def test_cumulative_hazard_over_target_los_equals_benchmark(target_los: int) -> None:
    rate = 0.05
    total = sum(_daily_hazard(rate, d, target_los) for d in range(target_los))
    assert total == pytest.approx(rate, rel=1e-6)


def test_early_window_days_still_weigh_more_than_admission_day() -> None:
    assert _daily_hazard(0.05, 3, 8) > _daily_hazard(0.05, 0, 8)
