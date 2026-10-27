"""Blood-gas pO2 / pCO2 follow oxygenation impairment, consistent with SpO2 (#2088)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.physiology.engine import derive_lab_values, derive_vital_signs
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_BASE = BaselineVitals(
    temperature=36.6, heart_rate=72, systolic_bp=122, diastolic_bp=76, respiratory_rate=14, spo2=97.3
)


def _abg(state: PhysiologicalState) -> dict:
    return derive_lab_values(state, "M", 60)


def test_healthy_po2_unchanged() -> None:
    assert _abg(PhysiologicalState())["pO2"] == pytest.approx(95, abs=2)


@pytest.mark.parametrize("oxy", [0.2, 0.36, 0.5])
def test_po2_matches_spo2_on_the_dissociation_curve(oxy: float) -> None:
    state = PhysiologicalState(oxygenation_impairment=oxy)
    spo2 = derive_vital_signs(state, _BASE, datetime(2026, 5, 1, 12))["spo2"]
    po2 = _abg(state)["pO2"]
    # Severinghaus: SpO2 88 ~ pO2 55, 92 ~ 63, 85 ~ 50
    expected = {0.2: (62, 72), 0.36: (52, 60), 0.5: (45, 52)}[oxy]
    assert expected[0] <= po2 <= expected[1], (spo2, po2)


def test_hypoxemia_drives_hyperventilation_without_co2_retention() -> None:
    pe_like = _abg(PhysiologicalState(oxygenation_impairment=0.44))
    assert pe_like["pCO2"] < 36
    assert pe_like["pH"] > 7.42


def test_co2_retainers_do_not_hyperventilate() -> None:
    copd = PhysiologicalState(oxygenation_impairment=0.44, ph_status=-0.2, respiratory_fraction=1.0)
    baseline_copd = PhysiologicalState(ph_status=-0.2, respiratory_fraction=1.0)
    assert _abg(copd)["pCO2"] == pytest.approx(_abg(baseline_copd)["pCO2"])
