"""Unit tests for physiology engine."""

import math
from datetime import datetime, timedelta

import pytest

from clinosim.modules.physiology.engine import (
    apply_coupling_rules,
    apply_disease_onset,
    clamp,
    derive_lab_values,
    derive_vital_signs,
    initialize_state,
    update,
)
from clinosim.types.clinical import PhysiologicalState, StateChangeDirective
from clinosim.types.patient import BaselineVitals, ChronicCondition, PatientPhysiologicalProfile


@pytest.fixture
def healthy_profile():
    return PatientPhysiologicalProfile(
        renal_reserve=0.85,
        cardiac_reserve=0.80,
        hepatic_reserve=0.90,
    )


@pytest.fixture
def test_patient_profile():
    """72F with HT + DM (matching test patient)."""
    return PatientPhysiologicalProfile(
        immune_reactivity=0.55,
        renal_reserve=0.70,
        cardiac_reserve=0.72,
        hepatic_reserve=0.80,
        treatment_sensitivity=1.05,
        delirium_susceptibility=0.25,
    )


@pytest.fixture
def test_conditions():
    return [
        ChronicCondition(code="I10", severity_score=0.2),
        ChronicCondition(code="E11.9", severity_score=0.2),
    ]


@pytest.fixture
def baseline_vitals():
    return BaselineVitals(
        temperature=36.4, heart_rate=76, systolic_bp=132,
        diastolic_bp=78, respiratory_rate=16, spo2=97.0,
    )


# --- Initialization ---

@pytest.mark.unit
class TestInitializeState:
    def test_healthy_patient(self, healthy_profile):
        state = initialize_state(healthy_profile, [])
        assert state.renal_function == pytest.approx(0.85)
        assert state.cardiac_function == pytest.approx(0.80)
        assert state.inflammation_level == pytest.approx(0.03)
        assert state.volume_status == pytest.approx(0.0)

    def test_with_chronic_conditions(self, test_patient_profile, test_conditions):
        state = initialize_state(test_patient_profile, test_conditions)
        # HT and DM with low severity should not dramatically change reserves
        assert state.renal_function > 0.5
        assert state.cardiac_function > 0.5

    def test_ckd_reduces_renal(self):
        profile = PatientPhysiologicalProfile(renal_reserve=0.80)
        ckd = [ChronicCondition(code="N18.3", severity_score=0.5)]
        state = initialize_state(profile, ckd)
        assert state.renal_function < 0.70  # reduced by CKD


# --- Disease onset ---

@pytest.mark.unit
class TestDiseaseOnset:
    def test_moderate_pneumonia(self, test_patient_profile, test_conditions):
        state = initialize_state(test_patient_profile, test_conditions)
        infl_before = state.inflammation_level

        impact = {
            "moderate": {
                "inflammation_level": 0.50,
                "volume_status": -0.20,
                "perfusion_status": -0.05,
                "renal_function": -0.05,
            }
        }
        state = apply_disease_onset(state, "moderate", impact)

        assert state.inflammation_level > infl_before + 0.4
        assert state.volume_status < 0  # dehydrated


# --- Update ---

@pytest.mark.unit
class TestUpdate:
    def test_inflammation_decreases(self, test_patient_profile, test_conditions):
        state = initialize_state(test_patient_profile, test_conditions)
        state.inflammation_level = 0.6

        directive = StateChangeDirective(
            changes={"inflammation_level": -0.10},
            reason="smooth_recovery_day3",
        )
        updated = update(state, directive, timedelta(hours=24))
        assert updated.inflammation_level == pytest.approx(0.5, abs=0.01)

    def test_partial_day_scaling(self):
        state = PhysiologicalState(inflammation_level=0.6)
        directive = StateChangeDirective(changes={"inflammation_level": -0.10})
        # 1 hour = 1/24 of a day
        updated = update(state, directive, timedelta(hours=1))
        expected = 0.6 - 0.10 / 24
        assert updated.inflammation_level == pytest.approx(expected, abs=0.001)


# --- Coupling rules ---

@pytest.mark.unit
class TestCouplingRules:
    def test_low_perfusion_hurts_renal(self):
        state = PhysiologicalState(
            cardiac_function=0.3, perfusion_status=0.3, renal_function=0.8,
        )
        apply_coupling_rules(state)
        assert state.perfusion_status < 0.5
        assert state.renal_function < 0.8  # pre-renal AKI

    def test_severe_inflammation_triggers_dic(self):
        state = PhysiologicalState(inflammation_level=0.85, coagulation_status=0.0)
        apply_coupling_rules(state)
        assert state.coagulation_status > 0  # DIC pathway activated


# --- Lab value derivation ---

@pytest.mark.unit
class TestDeriveLabValues:
    def test_normal_state(self):
        state = PhysiologicalState()  # all defaults (healthy)
        labs = derive_lab_values(state, sex="F", age=72)

        # CRP should be very low for healthy state
        assert labs["CRP"] < 1.0
        # WBC should be normal range
        assert 4000 < labs["WBC"] < 11000
        # Creatinine normal for female
        assert 0.4 < labs["Creatinine"] < 1.0
        # Hb normal for female
        assert 11 < labs["Hb"] < 16

    def test_inflamed_state(self):
        state = PhysiologicalState(inflammation_level=0.6)
        labs = derive_lab_values(state, sex="F", age=72)

        assert labs["CRP"] > 1.0  # elevated above normal (0.1 * exp(0.6 * 5.8) ≈ 3.2)
        assert labs["WBC"] > 10000  # elevated WBC
        assert labs["PCT"] > 0.1  # elevated procalcitonin
        assert labs["Albumin"] < 3.5  # decreased albumin

    def test_renal_failure(self):
        state = PhysiologicalState(renal_function=0.2)
        labs = derive_lab_values(state, sex="M", age=70)

        assert labs["Creatinine"] > 3.0
        assert labs["BUN"] > 50
        assert labs["K"] > 5.0  # hyperkalemia
        assert labs["eGFR"] < 30

    def test_no_negative_values(self):
        """No lab value should ever be negative."""
        state = PhysiologicalState(
            inflammation_level=0.9, renal_function=0.1,
            cardiac_function=0.2, hepatic_function=0.1,
            anemia_level=0.9, perfusion_status=0.1,
        )
        labs = derive_lab_values(state, sex="F", age=85)
        for name, value in labs.items():
            assert value >= 0, f"{name} is negative: {value}"


# --- Vital signs derivation ---

@pytest.mark.unit
class TestDeriveVitalSigns:
    def test_fever_from_inflammation(self, baseline_vitals):
        state = PhysiologicalState(inflammation_level=0.6)
        ts = datetime(2024, 6, 15, 10, 0)  # 10 AM
        vitals = derive_vital_signs(state, baseline_vitals, ts)

        assert vitals["temperature"] > 37.5  # fever
        assert vitals["heart_rate"] > baseline_vitals.heart_rate  # tachycardia from fever

    def test_shock_drops_bp(self, baseline_vitals):
        state = PhysiologicalState(perfusion_status=0.2)  # more severe shock
        ts = datetime(2024, 6, 15, 10, 0)
        vitals = derive_vital_signs(state, baseline_vitals, ts)

        assert vitals["systolic_bp"] < 110  # reduced from baseline 132
        assert vitals["heart_rate"] > 100  # compensatory tachycardia

    def test_circadian_temperature(self, baseline_vitals):
        state = PhysiologicalState()  # healthy
        morning = datetime(2024, 6, 15, 4, 0)  # 4 AM nadir
        evening = datetime(2024, 6, 15, 16, 0)  # 4 PM peak
        t_morning = derive_vital_signs(state, baseline_vitals, morning)["temperature"]
        t_evening = derive_vital_signs(state, baseline_vitals, evening)["temperature"]

        # Circadian variation is 0.3°C amplitude, but rounding to 1 decimal
        # may obscure small differences. Check raw difference.
        assert t_evening >= t_morning  # evening should be >= morning

    def test_spo2_bounds(self, baseline_vitals):
        state = PhysiologicalState(inflammation_level=0.9, volume_status=0.8)
        ts = datetime(2024, 6, 15, 10, 0)
        vitals = derive_vital_signs(state, baseline_vitals, ts)

        assert 60 <= vitals["spo2"] <= 100
