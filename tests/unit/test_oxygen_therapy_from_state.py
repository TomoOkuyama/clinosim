"""Oxygen follows SpO2 and raises it (#2083)."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.simulator.vitals_pipeline import _o2_for, spo2_on_oxygen
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_no_oxygen_at_target_even_for_respiratory_disease() -> None:
    rng = np.random.default_rng(1)
    for disease in ("bacterial_pneumonia", "copd_exacerbation", "heart_failure_exacerbation"):
        assert _o2_for(95.0, disease, rng) == (False, None, "")


def test_oxygen_below_target_and_copd_target_is_lower() -> None:
    rng = np.random.default_rng(1)
    assert _o2_for(90.0, "bacterial_pneumonia", rng)[0]
    assert not _o2_for(90.0, "copd_exacerbation", rng)[0]
    assert _o2_for(86.0, "copd_exacerbation", rng)[0]


def test_oxygen_raises_recorded_spo2() -> None:
    state = PhysiologicalState(oxygenation_impairment=0.3)
    on_o2 = spo2_on_oxygen(88.0, 5.0, state, "bacterial_pneumonia")
    assert 92.0 <= on_o2 <= 99.0


def test_refractory_hypoxemia_responds_less() -> None:
    mild = spo2_on_oxygen(85.0, 8.0, PhysiologicalState(oxygenation_impairment=0.2), "sepsis")
    shunt = spo2_on_oxygen(85.0, 8.0, PhysiologicalState(oxygenation_impairment=0.8), "sepsis")
    assert shunt < mild


def test_copd_titrated_to_88_92_band() -> None:
    assert spo2_on_oxygen(84.0, 4.0, PhysiologicalState(oxygenation_impairment=0.3), "copd_exacerbation") <= 94.0
