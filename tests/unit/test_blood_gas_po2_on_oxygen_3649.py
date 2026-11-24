"""The blood-gas po2 follows the saturation on oxygen (Issue #3649)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.physiology._lab_derivation_thresholds import LAB_REFERENCE_SAO2_PCT
from clinosim.modules.physiology.engine import (
    derive_lab_values,
    po2_from_saturation,
    room_air_saturation,
)
from clinosim.simulator.oxygen_course import OxygenCourse
from clinosim.simulator.vitals_pipeline import oxygen_saturation_for_lab
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit

T = datetime(2026, 3, 2, 6, 0)


def _hypoxemic() -> PhysiologicalState:
    state = PhysiologicalState()
    state.oxygenation_impairment = 0.5
    state.inflammation_level = 0.6
    return state


def test_room_air_po2_is_unchanged_without_an_override() -> None:
    state = _hypoxemic()
    a = derive_lab_values(state, sex="F", age=76)
    b = derive_lab_values(state, sex="F", age=76, sao2_pct=None)
    assert a["pO2"] == b["pO2"]
    assert a["pO2"] < 70.0  # hypoxemic on room air


def test_charted_98_percent_on_oxygen_gives_po2_above_90() -> None:
    labs = derive_lab_values(_hypoxemic(), sex="F", age=76, sao2_pct=98.0)
    assert labs["pO2"] > 90.0
    assert abs(labs["pO2"] - po2_from_saturation(98.0)) < 1.0


def test_override_changes_only_po2() -> None:
    state = _hypoxemic()
    a = derive_lab_values(state, sex="F", age=76)
    b = derive_lab_values(state, sex="F", age=76, sao2_pct=98.0)
    assert {k: v for k, v in a.items() if k != "pO2"} == {k: v for k, v in b.items() if k != "pO2"}


def test_saturation_for_lab_is_none_off_oxygen() -> None:
    assert oxygen_saturation_for_lab(OxygenCourse(), T, _hypoxemic(), "pneumonia") is None


def test_saturation_for_lab_on_oxygen_is_raised() -> None:
    state = _hypoxemic()
    course = OxygenCourse(on=True, flow=6.0, device="simple_mask")
    sat = oxygen_saturation_for_lab(course, T, state, "pneumonia")
    assert sat is not None
    assert sat > room_air_saturation(state, LAB_REFERENCE_SAO2_PCT)


def test_saturation_for_lab_on_the_ventilator() -> None:
    course = OxygenCourse()
    course.start_ventilation(datetime(2026, 3, 1, 6, 0))
    sat = oxygen_saturation_for_lab(course, T, _hypoxemic(), "pneumonia")
    assert sat is not None and sat > 90.0
