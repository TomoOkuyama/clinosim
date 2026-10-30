"""Uncontrolled systemic inflammation is not safe for home (Issue #2239)."""

from __future__ import annotations

import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.simulator.discharge_gate import discharge_disposition_for, unsafe_for_home
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_maximal_inflammation_is_unsafe_for_home() -> None:
    assert unsafe_for_home(PhysiologicalState(inflammation_level=1.0), None)
    assert unsafe_for_home(PhysiologicalState(inflammation_level=0.85), None)


def test_resolving_inflammation_does_not_block_home() -> None:
    assert not unsafe_for_home(PhysiologicalState(inflammation_level=0.5), None)


def test_survivor_with_uncontrolled_sepsis_is_not_sent_home() -> None:
    disposition = discharge_disposition_for(PhysiologicalState(inflammation_level=1.0), None, died=False)
    assert disposition is not DischargeDisposition.HOME
