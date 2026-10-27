"""Vital-sign monitoring intensity follows the state axes (#2092)."""

from __future__ import annotations

import pytest

from clinosim.simulator.vitals_pipeline import monitoring_tier
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("state", "tier"),
    [
        (PhysiologicalState(), "routine"),
        (PhysiologicalState(consciousness_impairment=0.3), "unstable"),
        (PhysiologicalState(oxygenation_impairment=0.35), "unstable"),
        (PhysiologicalState(sympathetic_activation=0.55), "unstable"),
        (PhysiologicalState(consciousness_impairment=0.55), "critical"),
        (PhysiologicalState(oxygenation_impairment=0.55), "critical"),
        (PhysiologicalState(perfusion_status=0.2), "critical"),
    ],
)
def test_monitoring_tier(state: PhysiologicalState, tier: str) -> None:
    assert monitoring_tier(state, "cellulitis", day=5) == tier


def test_critical_disease_list_only_early_days() -> None:
    assert monitoring_tier(PhysiologicalState(), "hemorrhagic_stroke", day=0) == "critical"
    assert monitoring_tier(PhysiologicalState(), "hemorrhagic_stroke", day=6) == "routine"
