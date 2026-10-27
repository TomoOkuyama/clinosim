"""Discharge waits for autonomic symptoms to settle (#2055)."""

from __future__ import annotations

import pytest

from clinosim.simulator._discharge_gate_thresholds import DISCHARGE_SYMPATHETIC_MAX
from clinosim.simulator.discharge_gate import _check_discharge_ready, extend_stay_for_symptoms
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("country_key", ["us", "japan"])
def test_uncontrolled_sympathetic_activation_blocks_discharge(country_key: str) -> None:
    state = PhysiologicalState()
    assert _check_discharge_ready(state, 5, country_key)
    state.sympathetic_activation = DISCHARGE_SYMPATHETIC_MAX
    assert not _check_discharge_ready(state, 5, country_key)


def test_stay_extends_only_while_symptoms_persist_and_below_max() -> None:
    state = PhysiologicalState()
    assert not extend_stay_for_symptoms(state, los_ceiling=4, max_los=7)
    state.sympathetic_activation = 0.5
    assert extend_stay_for_symptoms(state, los_ceiling=4, max_los=7)
    assert not extend_stay_for_symptoms(state, los_ceiling=7, max_los=7)
    assert not extend_stay_for_symptoms(state, los_ceiling=4, max_los=None)
