"""New physiology axes: sympathetic activation, pain, oxygenation, consciousness (#2053)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.physiology.engine import apply_state_delta, canonical_state_vars, derive_vital_signs
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_TS = datetime(2026, 5, 1, 14, 0)
_AXES = ("sympathetic_activation", "pain_level", "oxygenation_impairment", "consciousness_impairment")


def _baseline() -> BaselineVitals:
    return BaselineVitals(
        temperature=36.6, heart_rate=72, systolic_bp=122, diastolic_bp=76, respiratory_rate=14, spo2=98.0
    )


def test_axes_are_canonical_and_default_zero() -> None:
    state = PhysiologicalState()
    for axis in _AXES:
        assert axis in canonical_state_vars()
        assert getattr(state, axis) == 0.0


def test_axes_clamp_to_unit_range() -> None:
    state = PhysiologicalState()
    apply_state_delta(state, "pain_level", 2.0)
    apply_state_delta(state, "oxygenation_impairment", -1.0)
    assert state.pain_level == 1.0
    assert state.oxygenation_impairment == 0.0


def test_zero_axes_leave_vitals_unchanged() -> None:
    state = PhysiologicalState(inflammation_level=0.3, volume_status=-0.2, perfusion_status=0.9)
    assert derive_vital_signs(state, _baseline(), _TS) == derive_vital_signs(
        replace(state, sympathetic_activation=0.0, pain_level=0.0), _baseline(), _TS
    )


def test_sympathetic_activation_raises_hr_and_bp() -> None:
    calm = derive_vital_signs(PhysiologicalState(), _baseline(), _TS)
    wired = derive_vital_signs(PhysiologicalState(sympathetic_activation=0.8), _baseline(), _TS)
    assert wired["heart_rate"] >= calm["heart_rate"] + 20
    assert wired["systolic_bp"] >= calm["systolic_bp"] + 15
    assert wired["respiratory_rate"] > calm["respiratory_rate"]


def test_pain_adds_partial_sympathetic_drive() -> None:
    calm = derive_vital_signs(PhysiologicalState(), _baseline(), _TS)
    pain = derive_vital_signs(PhysiologicalState(pain_level=0.8), _baseline(), _TS)
    assert calm["heart_rate"] < pain["heart_rate"]


def test_oxygenation_impairment_lowers_spo2_and_raises_rr() -> None:
    calm = derive_vital_signs(PhysiologicalState(), _baseline(), _TS)
    hypoxic = derive_vital_signs(PhysiologicalState(oxygenation_impairment=0.4), _baseline(), _TS)
    assert hypoxic["spo2"] <= calm["spo2"] - 8
    assert hypoxic["respiratory_rate"] >= calm["respiratory_rate"] + 4


@pytest.mark.parametrize(("level", "avpu"), [(0.3, "V"), (0.6, "P"), (0.9, "U")])
def test_consciousness_impairment_sets_avpu(level: float, avpu: str) -> None:
    from clinosim.simulator.vitals_pipeline import _loc_for

    state = PhysiologicalState(consciousness_impairment=level)
    assert _loc_for(state, "bacterial_pneumonia", 3, np.random.default_rng(0)) == avpu


def test_pain_score_floor_from_pain_level() -> None:
    from clinosim.simulator.vitals_pipeline import _pain_score

    assert _pain_score(PhysiologicalState(pain_level=0.8), day=5, rng=np.random.default_rng(0)) >= 8
