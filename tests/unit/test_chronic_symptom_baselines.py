"""Chronic conditions set steady-state symptom axes (#2061)."""

from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import initialize_state
from clinosim.simulator.daily_loop import apply_symptom_floor
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, PatientPhysiologicalProfile

pytestmark = pytest.mark.unit


def _state(*conditions: ChronicCondition) -> PhysiologicalState:
    return initialize_state(PatientPhysiologicalProfile(), list(conditions))


def test_copd_has_no_extra_oxygenation_baseline() -> None:
    # Resting COPD hypoxemia already comes from the existing COPD coupling
    # (outpatient SpO2 median ~94%); an extra axis baseline double-counts it.
    assert _state(ChronicCondition(code="J44.9", severity_score=0.7)).oxygenation_impairment == 0


def test_osteoarthritis_sets_baseline_pain() -> None:
    mild = _state(ChronicCondition(code="M17", severity_score=0.12)).pain_level
    typical = _state(ChronicCondition(code="M17", severity_score=0.25)).pain_level
    assert 0.15 <= mild < typical <= 0.35


def test_conditions_without_symptom_axes_stay_zero() -> None:
    state = _state(ChronicCondition(code="I10"), ChronicCondition(code="E11.9"))
    assert state.oxygenation_impairment == 0 and state.pain_level == 0


def test_symptom_floor_keeps_chronic_baseline_during_recovery() -> None:
    state = PhysiologicalState(pain_level=0.1, oxygenation_impairment=0.02)
    apply_symptom_floor(state, {"pain_level": 0.3, "oxygenation_impairment": 0.1})
    assert state.pain_level == 0.3 and state.oxygenation_impairment == 0.1
    state.pain_level = 0.6
    apply_symptom_floor(state, {"pain_level": 0.3})
    assert state.pain_level == 0.6


def test_mild_chronic_pain_does_not_raise_heart_rate() -> None:
    from datetime import datetime

    from clinosim.modules.physiology.engine import derive_vital_signs
    from clinosim.types.patient import BaselineVitals

    base = BaselineVitals(
        temperature=36.6, heart_rate=72, systolic_bp=122, diastolic_bp=76, respiratory_rate=14, spo2=98.0
    )
    ts = datetime(2026, 5, 1, 14, 0)
    calm = derive_vital_signs(PhysiologicalState(), base, ts)
    chronic = derive_vital_signs(PhysiologicalState(pain_level=0.35), base, ts)
    acute = derive_vital_signs(PhysiologicalState(pain_level=0.8), base, ts)
    assert chronic["heart_rate"] == calm["heart_rate"]
    assert acute["heart_rate"] > calm["heart_rate"]
