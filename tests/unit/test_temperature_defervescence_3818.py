"""Temperature in the low-grade range — Issue #3818.

Fever follows the cytokine response and settles before CRP does: treated
community-acquired pneumonia reaches a temperature of 37.2 C or lower in a
median of 3 days (Halm et al., JAMA 1998;279:1452-7), while CRP is still
falling. A linear lift of 3 C per unit inflammation kept a patient whose CRP
was near normal (inflammation 0.3, CRP about 11 mg/L) at 37.4 C on average,
so readings of 38 C and a febrile discharge hold persisted for days. Below
the knee the lift now grows with the square of inflammation; at and above it
the linear lift is unchanged, so presenting fevers are as before."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.physiology._vital_signs_thresholds import (
    TEMPERATURE_INFLAMMATION_KNEE,
    TEMPERATURE_INFLAMMATION_SCALE,
)
from clinosim.modules.physiology.engine import derive_vital_signs
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

# 10:00 is the circadian zero crossing (offset 4 h, period 12 h).
_NEUTRAL = datetime(2026, 1, 1, 10, 0)


def _temp(inflammation: float) -> float:
    state = PhysiologicalState(inflammation_level=inflammation)
    return derive_vital_signs(state, BaselineVitals(), _NEUTRAL)["temperature"]


def test_near_normal_crp_is_not_low_grade_fever() -> None:
    assert _temp(0.3) <= 37.1


def test_presenting_fever_is_unchanged_from_the_linear_lift() -> None:
    for x in (TEMPERATURE_INFLAMMATION_KNEE, 0.75, 1.0):
        assert _temp(x) == pytest.approx(BaselineVitals().temperature + TEMPERATURE_INFLAMMATION_SCALE * x, abs=0.05)


def test_temperature_rises_with_inflammation() -> None:
    temps = [_temp(i / 20) for i in range(21)]
    assert temps == sorted(temps)
