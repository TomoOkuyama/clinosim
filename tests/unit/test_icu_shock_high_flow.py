"""ICU escalation for distributive shock and high oxygen requirement (#2110)."""

from __future__ import annotations

import pytest

from clinosim.simulator.daily_loop import airway_escalation_needed, icu_escalation_needed
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_distributive_shock_goes_to_icu_without_intubation() -> None:
    state = PhysiologicalState(inflammation_level=0.99, perfusion_status=0.7)
    assert icu_escalation_needed(state) and not airway_escalation_needed(state)
    assert not icu_escalation_needed(PhysiologicalState(inflammation_level=0.9, perfusion_status=0.7))
    assert not icu_escalation_needed(PhysiologicalState(inflammation_level=0.99, perfusion_status=0.85))


def test_high_flow_oxygen_requirement_goes_to_icu() -> None:
    state = PhysiologicalState(oxygenation_impairment=0.52)
    assert icu_escalation_needed(state) and not airway_escalation_needed(state)
    assert not icu_escalation_needed(PhysiologicalState(oxygenation_impairment=0.45))
