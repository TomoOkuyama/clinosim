"""Unit tests for physiology engine."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.modules.physiology.engine import (
    apply_coupling_rules,
    apply_disease_onset,
    derive_lab_values,
    derive_observed_vitals,
    derive_vital_signs,
    initialize_state,
    update,
    _variable_range,
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

    def test_dka_hyperglycemia_from_glucose_status(self):
        """DKA's acute glycemic state drives glucose to 300-500+, not baseline (AD-57)."""
        normal = derive_lab_values(PhysiologicalState(), sex="M", age=55)
        dka = derive_lab_values(
            PhysiologicalState(glucose_status=0.6), sex="M", age=55)
        severe = derive_lab_values(
            PhysiologicalState(glucose_status=0.8), sex="M", age=55)
        assert normal["Glucose"] < 130
        assert dka["Glucose"] > 300
        assert severe["Glucose"] > dka["Glucose"]
        assert dka["Glucose"] <= 1200  # clamped to a physiological bound

    def test_hypoglycemia_from_negative_glucose_status(self):
        labs = derive_lab_values(
            PhysiologicalState(glucose_status=-0.5), sex="M", age=55)
        assert labs["Glucose"] < 95

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


# --- Acid-base (two-axis metabolic / respiratory, AD-57) ---

@pytest.mark.unit
class TestAcidBase:
    def test_normal_blood_gas(self):
        labs = derive_lab_values(PhysiologicalState(), sex="M", age=50)
        assert 7.38 <= labs["pH"] <= 7.42
        assert 22 <= labs["HCO3"] <= 26
        assert 38 <= labs["pCO2"] <= 42

    def test_metabolic_acidosis_has_respiratory_compensation(self):
        """DKA-style metabolic acidosis: low HCO3 AND low pCO2 (Kussmaul)."""
        state = PhysiologicalState(ph_status=-0.5, respiratory_fraction=0.0)
        labs = derive_lab_values(state, sex="M", age=50)
        assert labs["pH"] < 7.35
        assert labs["HCO3"] < 18          # primary metabolic drop
        assert labs["pCO2"] < 36          # respiratory compensation (NOT a rise)

    def test_respiratory_acidosis_has_metabolic_compensation(self):
        """COPD-style respiratory acidosis: high pCO2 AND compensating high HCO3."""
        state = PhysiologicalState(ph_status=-0.25, respiratory_fraction=1.0)
        labs = derive_lab_values(state, sex="M", age=50)
        assert labs["pCO2"] > 45          # CO2 retention
        assert labs["HCO3"] > 25          # renal compensation (NOT a drop)
        assert labs["pH"] > 7.30          # chronic compensation keeps pH near-normal

    def test_axis_distinguishes_same_magnitude(self):
        """Same ph_status magnitude routes differently by respiratory_fraction."""
        met = derive_lab_values(
            PhysiologicalState(ph_status=-0.3, respiratory_fraction=0.0), sex="M", age=50)
        resp = derive_lab_values(
            PhysiologicalState(ph_status=-0.3, respiratory_fraction=1.0), sex="M", age=50)
        assert met["HCO3"] < resp["HCO3"]   # metabolic drops bicarb, respiratory raises it
        assert met["pCO2"] < resp["pCO2"]   # metabolic lowers CO2, respiratory raises it

    def test_copd_chronic_sets_respiratory_axis(self):
        """A chronic COPD patient initializes onto the respiratory axis."""
        profile = PatientPhysiologicalProfile(
            renal_reserve=0.9, cardiac_reserve=0.9, hepatic_reserve=0.9)
        copd = ChronicCondition(code="J44.9", severity="moderate", severity_score=0.5)
        state = initialize_state(profile, [copd])
        assert state.respiratory_fraction == 1.0

    def test_disease_onset_sets_axis_from_type(self):
        state = PhysiologicalState()
        apply_disease_onset(state, "severe", {"severe": {"ph_status": -0.3}},
                            acid_base_type="respiratory")
        assert state.respiratory_fraction == 1.0
        labs = derive_lab_values(state, sex="M", age=50)
        assert labs["pCO2"] > 45 and labs["HCO3"] > 25


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


# --- Observed vitals (shared inpatient/ED/outpatient path, AD-57) ---

@pytest.mark.unit
class TestDeriveObservedVitals:
    def test_keys_and_determinism(self, baseline_vitals):
        state = PhysiologicalState()
        ts = datetime(2024, 6, 15, 10, 0)
        a = derive_observed_vitals(state, baseline_vitals, ts, np.random.default_rng(7))
        b = derive_observed_vitals(state, baseline_vitals, ts, np.random.default_rng(7))
        assert set(a) == {"temperature", "heart_rate", "systolic_bp",
                          "diastolic_bp", "respiratory_rate", "spo2"}
        assert a == b  # same seed → identical observed values

    def test_noise_keeps_spo2_in_range(self, baseline_vitals):
        state = PhysiologicalState(inflammation_level=0.9, volume_status=0.8)
        ts = datetime(2024, 6, 15, 10, 0)
        for seed in range(20):
            raw = derive_observed_vitals(state, baseline_vitals, ts, np.random.default_rng(seed))
            assert 60 <= raw["spo2"] <= 100

    def test_tracks_physiology(self, baseline_vitals):
        """Observed vitals follow the hidden state, not a fixed normal template."""
        ts = datetime(2024, 6, 15, 10, 0)
        rng = np.random.default_rng(0)
        febrile = derive_observed_vitals(
            PhysiologicalState(inflammation_level=0.7), baseline_vitals, ts, rng)
        healthy = derive_observed_vitals(
            PhysiologicalState(), baseline_vitals, ts, np.random.default_rng(0))
        assert febrile["temperature"] > healthy["temperature"]
        assert febrile["heart_rate"] > healthy["heart_rate"]


# --- Sodium axis (dysnatremia) ---

@pytest.mark.unit
def test_sodium_status_field_and_range():
    """Smoke test: sodium_status field exists and has correct range."""
    s = PhysiologicalState()
    assert s.sodium_status == 0.0
    assert _variable_range("sodium_status") == (-1.0, 1.0)


@pytest.mark.unit
def test_na_mapping_from_sodium_status():
    """Na lab value is driven by the dysnatremia axis (sodium_status * 14 term)."""
    # Normal: sodium_status=0, renal=1.0 -> 140 + 0*14 - 0*3 = 140
    s = PhysiologicalState(renal_function=1.0, sodium_status=0.0)
    assert abs(derive_lab_values(s, sex="M", age=60)["Na"] - 140.0) < 0.01

    # Hyponatremia: sodium_status=-1 -> 140 - 14 - 0 = 126
    s_lo = PhysiologicalState(renal_function=1.0, sodium_status=-1.0)
    assert 124 <= derive_lab_values(s_lo, sex="M", age=60)["Na"] <= 128

    # Hypernatremia: sodium_status=+1 -> 140 + 14 - 0 = 154 (>145)
    s_hi = PhysiologicalState(renal_function=1.0, sodium_status=1.0)
    assert derive_lab_values(s_hi, sex="M", age=60)["Na"] >= 148


@pytest.mark.unit
def test_dehydration_coupling_raises_sodium():
    """Severe volume depletion (dehydration) concentrates serum sodium."""
    s = PhysiologicalState(volume_status=-0.6, sodium_status=0.0)
    apply_coupling_rules(s)
    assert s.sodium_status > 0.0  # dehydration concentrates Na


@pytest.mark.unit
def test_chronic_hf_cirrhosis_baseline_hyponatremia():
    """Chronic HF and cirrhosis drive sodium_status negative (dilutional hyponatremia)."""
    profile = PatientPhysiologicalProfile(
        renal_reserve=0.85,
        cardiac_reserve=0.80,
        hepatic_reserve=0.90,
    )

    # Heart failure (I50.9) with moderate severity -> dilutional hyponatremia
    hf = ChronicCondition(code="I50.9", severity_score=0.6)
    state_hf = initialize_state(profile, [hf])
    assert state_hf.sodium_status < 0.0, (
        f"HF should lower sodium_status, got {state_hf.sodium_status}"
    )

    # Cirrhosis (K74.6) -> dilutional hyponatremia
    cirrhosis = ChronicCondition(code="K74.6", severity_score=0.6)
    state_k74 = initialize_state(profile, [cirrhosis])
    assert state_k74.sodium_status < 0.0, (
        f"Cirrhosis should lower sodium_status, got {state_k74.sodium_status}"
    )
