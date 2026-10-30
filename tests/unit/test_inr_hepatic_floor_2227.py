"""INR rises with liver injury, not with the ordinary hepatic reserve (Issue #2227)."""

from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def _inr(hepatic: float, coag: float = 0.0, on_warfarin: bool = False) -> float:
    state = PhysiologicalState(hepatic_function=hepatic, coagulation_status=coag)
    return derive_lab_values(state, "M", 78, on_warfarin=on_warfarin)["PT_INR"]


@pytest.mark.parametrize("reserve", [0.95, 0.85, 0.73])
def test_healthy_reserve_keeps_inr_in_the_reference_interval(reserve: float) -> None:
    # An elderly patient's hepatic reserve (about 0.7-0.95) is not liver disease.
    assert _inr(reserve) <= 1.1


def test_liver_injury_and_dic_raise_inr() -> None:
    assert _inr(0.3) >= 1.8  # decompensated cirrhosis
    assert _inr(0.9, coag=0.6) >= 1.8  # consumptive coagulopathy
    assert _inr(0.3) > _inr(0.5) > _inr(0.69)


def test_warfarin_still_centres_on_the_therapeutic_target() -> None:
    assert 2.3 <= _inr(0.85, on_warfarin=True) <= 2.7
