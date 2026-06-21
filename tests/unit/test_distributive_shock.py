"""Distributive (vasodilatory) shock hypotension at vitals-derivation (follow-up A).

Septic shock is distributive: severe systemic inflammation drops blood pressure.
Audit found sepsis SBP<90 = 0% (no hypotension), contradicting the R65.21 coding.
We add an inflammation-driven SBP/DBP reduction in derive_vital_signs only — the
displayed vital — WITHOUT mutating perfusion_status. perfusion drives the
clinical-course/complication/LOS/mortality RNG branches; touching it would perturb
the shared master stream (76% demographic churn, large lab regression). Master
sepsis labs (lactate, creatinine) are already coherently elevated via
initial_state_impact, so adding hypotension here completes the septic-shock
picture (SBP down + already-elevated lactate/AKI) golden-safely.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.physiology.engine import (
    DISTRIBUTIVE_THRESHOLD,
    derive_vital_signs,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_TS = datetime(2026, 6, 21, 12, 0, 0)


def _state(inflammation: float, perfusion: float = 1.0, volume: float = 0.0) -> PhysiologicalState:
    s = PhysiologicalState(patient_id="t")
    s.inflammation_level = inflammation
    s.perfusion_status = perfusion
    s.volume_status = volume
    return s


def test_high_inflammation_lowers_sbp_relative_to_threshold() -> None:
    base = BaselineVitals()
    sbp_hi = derive_vital_signs(_state(0.85), base, _TS)["systolic_bp"]
    sbp_thr = derive_vital_signs(_state(DISTRIBUTIVE_THRESHOLD), base, _TS)["systolic_bp"]
    assert sbp_hi < sbp_thr


def test_at_or_below_threshold_sbp_unchanged() -> None:
    # At threshold the distributive drop is exactly zero — SBP equals the
    # non-distributive value (here baseline 120, healthy perfusion/volume).
    base = BaselineVitals()
    assert derive_vital_signs(_state(DISTRIBUTIVE_THRESHOLD), base, _TS)["systolic_bp"] == 120


def test_severe_sepsis_state_reaches_shock_sbp() -> None:
    # Severe septic shock requires the combination the calibrated coefficient
    # targets: peak inflammation + hypovolemia in a patient of typical (here
    # slightly elderly, 108) baseline SBP -> SBP < 90. Per the generation audit
    # ~25% of sepsis reaches this; a single mild state at the threshold does not.
    base = BaselineVitals(systolic_bp=108)
    sbp = derive_vital_signs(_state(0.95, volume=-0.50), base, _TS)["systolic_bp"]
    assert sbp < 90


def test_does_not_mutate_perfusion_state() -> None:
    # Option 1 is observation-time only: the state variable that feeds the
    # clinical-course/complication RNG must be left untouched.
    s = _state(0.85)
    derive_vital_signs(s, BaselineVitals(), _TS)
    assert s.perfusion_status == 1.0


def test_deterministic() -> None:
    base = BaselineVitals()
    a = derive_vital_signs(_state(0.85), base, _TS)["systolic_bp"]
    b = derive_vital_signs(_state(0.85), base, _TS)["systolic_bp"]
    assert a == b
