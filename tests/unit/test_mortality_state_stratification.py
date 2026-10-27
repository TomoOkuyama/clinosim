"""In-hospital mortality is stratified by consciousness and oxygenation (#2098)."""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.discharge_gate import (
    _evaluate_mortality,
    expected_state_multiplier,
    mortality_state_multiplier,
)
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def test_multiplier_rises_with_impairment() -> None:
    assert mortality_state_multiplier(0.0, 0.0) == 1.0
    assert mortality_state_multiplier(0.55, 0.0) > 1.0
    assert mortality_state_multiplier(0.8, 0.0) > mortality_state_multiplier(0.55, 0.0)
    assert mortality_state_multiplier(0.0, 0.6) > 1.0


def test_expected_multiplier_from_severity_mix() -> None:
    ich = expected_state_multiplier(load_disease_protocol("hemorrhagic_stroke"))
    assert ich > 1.0  # severe ICH presents in the stupor range
    assert expected_state_multiplier(load_disease_protocol("cellulitis")) == 1.0


def test_relative_risk_preserves_the_disease_average() -> None:
    patient = SimpleNamespace(age=60)

    def deaths(relative: float) -> int:
        rng = np.random.default_rng(3)
        return sum(
            _evaluate_mortality(
                PhysiologicalState(),
                patient,
                "severe",
                2,
                rng,
                disease_mortality_rate=0.2,
                target_los=7,
                state_relative_risk=relative,
            )
            for _ in range(4000)
        )

    assert deaths(2.0) > 1.5 * deaths(1.0) > 1.5 * deaths(0.5)
