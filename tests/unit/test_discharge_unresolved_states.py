"""No home discharge with hypoxemia, impaired consciousness or hypoperfusion (#2084)."""

from __future__ import annotations

import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.simulator.discharge_gate import (
    _check_discharge_ready,
    discharge_disposition_for,
    extend_stay_for_symptoms,
    unsafe_for_home,
)
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "state",
    [
        PhysiologicalState(oxygenation_impairment=0.3),
        PhysiologicalState(consciousness_impairment=0.3),
        PhysiologicalState(perfusion_status=0.4),
    ],
)
def test_unresolved_states_extend_the_stay_and_block_discharge(state: PhysiologicalState) -> None:
    assert unsafe_for_home(state, {})
    assert extend_stay_for_symptoms(state, los_ceiling=4, max_los=8)
    assert not _check_discharge_ready(state, 5, "us")


def test_chronic_baseline_does_not_count_as_unresolved() -> None:
    state = PhysiologicalState(oxygenation_impairment=0.2)
    assert not unsafe_for_home(state, {"oxygenation_impairment": 0.15})
    assert unsafe_for_home(state, {"oxygenation_impairment": 0.0})


def test_resolved_patient_goes_home() -> None:
    state = PhysiologicalState()
    assert not unsafe_for_home(state, {})
    assert discharge_disposition_for(state, {}, died=False) == DischargeDisposition.HOME


def test_unresolved_at_maximum_stay_goes_to_skilled_nursing() -> None:
    state = PhysiologicalState(consciousness_impairment=0.4)
    assert not extend_stay_for_symptoms(state, los_ceiling=8, max_los=8)
    assert discharge_disposition_for(state, {}, died=False) == DischargeDisposition.SNF
    assert discharge_disposition_for(state, {}, died=True) == DischargeDisposition.EXP
