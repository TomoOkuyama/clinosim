"""Chronic troponin I calibration in non-ACS patients (Issue #2903).

The ED builds its labs from the chronic state (``initialize_state``), so the
troponin of a patient with no acute coronary syndrome is set by the age-reduced
cardiac / renal reserve and the chronic conditions. These tests pin troponin I
for representative states: a healthy adult reads normal, chronic elevation
appears in CKD stage 4-5 and heart failure, and ACS stays at MI level.
"""

from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import derive_lab_values, initialize_state
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, PatientPhysiologicalProfile

pytestmark = pytest.mark.unit

TROPONIN_URL = 0.04  # ng/mL, male 99th-percentile upper reference limit


def _reserve(age: int) -> float:
    """Mean Beta(30, 2) reserve minus the activator's age penalty."""
    return 0.94 - max(0, (age - 40) * 0.005)


def _chronic_state(age: int, conditions: list[ChronicCondition]) -> PhysiologicalState:
    r = _reserve(age)
    profile = PatientPhysiologicalProfile(renal_reserve=r, cardiac_reserve=r)
    return initialize_state(profile, conditions)


def _troponin(state: PhysiologicalState, age: int, *, acs: bool = False) -> float:
    return derive_lab_values(state, sex="M", age=age, myocardial_injury=acs)["Troponin_I"]


def test_healthy_adult_reads_baseline() -> None:
    assert _troponin(_chronic_state(45, []), 45) == pytest.approx(0.010, abs=0.001)


def test_healthy_older_adult_stays_below_limit() -> None:
    # Before #2903 the age-reduced reserve alone gave ~0.105 ng/mL at 70.
    assert _troponin(_chronic_state(70, []), 70) == pytest.approx(0.0165, abs=0.002)


def test_ckd3_stays_below_limit() -> None:
    ckd3 = ChronicCondition(code="N18.31", severity_score=0.35, stage="CKD G3a")
    assert _troponin(_chronic_state(70, [ckd3]), 70) == pytest.approx(0.0226, abs=0.002)


def test_ckd4_reaches_limit() -> None:
    ckd4 = ChronicCondition(code="N18.4", severity_score=0.7, stage="CKD G4")
    value = _troponin(_chronic_state(70, [ckd4]), 70)
    assert value == pytest.approx(0.0406, abs=0.003)
    assert value < 0.1  # chronic, not MI-level


def test_heart_failure_mildly_elevated() -> None:
    hf = ChronicCondition(code="I50.22", severity_score=0.45, stage="NYHA III")
    value = _troponin(_chronic_state(70, [hf]), 70)
    assert value == pytest.approx(0.111, abs=0.01)
    assert TROPONIN_URL < value < 0.5


def test_acs_stays_mi_level() -> None:
    state = _chronic_state(70, [])
    state.cardiac_function = 0.4
    assert _troponin(state, 70, acs=True) == pytest.approx(44.1, abs=0.5)
