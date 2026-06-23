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
    hba1c_from_glycemic_control,
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

    def test_bnp_discriminates_hf_from_mi(self):
        # State values mirror what the simulator actually produces (verified by the
        # generation audit), not design estimates: HF exacerbation drops cardiac to
        # ~0.27 with volume overload ~0.56; acute MI drops cardiac to ~0.19 with normal
        # volume. The thresholds encode the clinical target bands (HF 800-1500, MI <400).
        # HF exacerbation: low cardiac + volume overload (wall stress) -> high BNP.
        hf = derive_lab_values(
            PhysiologicalState(cardiac_function=0.27, volume_status=0.56),
            sex="M", age=75)
        # Uncomplicated MI: low cardiac, normal/low volume -> moderate BNP.
        mi = derive_lab_values(
            PhysiologicalState(cardiac_function=0.19, volume_status=-0.05),
            sex="M", age=75)
        # Normal heart -> near-baseline BNP.
        normal = derive_lab_values(
            PhysiologicalState(cardiac_function=0.90, volume_status=0.0),
            sex="M", age=75)
        assert normal["BNP"] < 100
        assert 100 < mi["BNP"] < 400
        assert hf["BNP"] > 800
        assert hf["BNP"] > 5 * mi["BNP"]

    def test_bnp_volume_term_gated_by_cardiac(self):
        # Volume overload in a PRESERVED heart (e.g. cirrhosis ascites, AKI) must NOT
        # spuriously elevate BNP — the volume term is gated by cardiac dysfunction.
        preserved = derive_lab_values(
            PhysiologicalState(cardiac_function=0.85, volume_status=0.50),
            sex="M", age=75)
        assert preserved["BNP"] < 100

    def test_bnp_dehydration_does_not_suppress(self):
        # Negative volume_status (dehydration) must not push BNP below the cardiac floor.
        dry = derive_lab_values(
            PhysiologicalState(cardiac_function=0.50, volume_status=-0.60),
            sex="M", age=75)
        floor = derive_lab_values(
            PhysiologicalState(cardiac_function=0.50, volume_status=0.0),
            sex="M", age=75)
        assert dry["BNP"] == pytest.approx(floor["BNP"])

    def test_bnp_clamped_to_assay_ceiling(self):
        from clinosim.modules.observation.engine import (
            PHYSIOLOGIC_LIMITS,
            apply_realistic_variability,
        )
        assert PHYSIOLOGIC_LIMITS["BNP"] == (0.0, 5000.0)
        rng = np.random.default_rng(0)
        # A divergent true BNP (severe HF) must be capped at the assay ceiling.
        observed = apply_realistic_variability("BNP", 12000.0, rng)
        assert observed <= 5000.0

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


@pytest.mark.unit
class TestHbA1cGlycemicControl:
    def test_hba1c_from_glycemic_control_monotonic_and_bounds(self):
        best = hba1c_from_glycemic_control(1.0)
        worst = hba1c_from_glycemic_control(0.0)
        assert best < worst                      # worse control -> higher HbA1c
        assert 6.0 <= best <= 7.0                # well-controlled diabetic
        assert 10.0 <= worst <= 13.0             # very poor control
        # clamps out-of-range input
        assert hba1c_from_glycemic_control(2.0) == hba1c_from_glycemic_control(1.0)

    def test_derive_lab_values_hba1c_diabetic_vs_nondiabetic(self):
        nondm = PhysiologicalState()
        labs_nondm = derive_lab_values(nondm, sex="M", age=55, has_diabetes=False)
        assert 4.5 <= labs_nondm["HbA1c"] <= 5.8

        good = PhysiologicalState(glycemic_control=0.9)
        labs_good = derive_lab_values(good, sex="M", age=55, has_diabetes=True)
        assert 6.0 <= labs_good["HbA1c"] <= 7.6

        poor = PhysiologicalState(glycemic_control=0.1)
        labs_poor = derive_lab_values(poor, sex="M", age=55, has_diabetes=True)
        assert labs_poor["HbA1c"] > labs_good["HbA1c"]
        # Glucose co-moves with control
        assert labs_poor["Glucose"] > labs_good["Glucose"]


@pytest.mark.unit
def test_initialize_state_seeds_glycemic_control_from_e11():
    prof = PatientPhysiologicalProfile()
    dm = ChronicCondition(code="E11.9", glycemic_control=0.2)
    st = initialize_state(prof, [dm], "pt-1")
    assert st.glycemic_control == 0.2
    # non-diabetic -> stays None
    st2 = initialize_state(prof, [], "pt-2")
    assert st2.glycemic_control is None


@pytest.mark.unit
def test_creatinine_curve_matches_clinical_bands():
    """Pin the (state.renal_function -> Creatinine) curve to clinically realistic bands.

    Guard against an accidental re-steepening of the low-renal slope. The 0.5
    boundary value MUST stay continuous between the >0.5 (base_cr / renal) and
    <=0.5 (linear) branches.
    """
    # Male baseline (base_cr = 0.9). State is fabricated directly so we exercise
    # the formula independent of disease onset / coupling.
    expected = {
        # state.renal_function -> Cr (mg/dL), tolerance 0.05
        0.0: 5.05,   # severe AKI (anuric state) - KDIGO 3 mid-high
        0.1: 4.40,   # KDIGO 3
        0.2: 3.75,   # KDIGO 2
        0.3: 3.10,   # CKD3 typical
        0.4: 2.45,   # early CKD
        0.5: 1.80,   # baseline (boundary, continuous with renal>0.5 branch)
    }
    for renal, target in expected.items():
        st = PhysiologicalState(patient_id="pt")
        st.renal_function = renal
        labs = derive_lab_values(st, sex="M", age=70)
        assert abs(labs["Creatinine"] - target) < 0.05, (
            f"renal={renal:.2f} Cr={labs['Creatinine']:.2f} expected~{target}"
        )

    # Continuity at the 0.5 boundary: top branch (base_cr / renal) and bottom
    # branch (linear) must agree to within 0.01.
    st = PhysiologicalState(patient_id="pt")
    st.renal_function = 0.5
    cr_at_05 = derive_lab_values(st, sex="M", age=70)["Creatinine"]
    st.renal_function = 0.500001
    cr_just_above = derive_lab_values(st, sex="M", age=70)["Creatinine"]
    assert abs(cr_at_05 - cr_just_above) < 0.01


@pytest.mark.unit
def test_aki_creatinine_not_anuric_on_elderly_baseline():
    """AKI on a typical elderly baseline (no CKD) should land Cr in the KDIGO 1-3
    envelope, not pin Creatinine at dialysis/ESRD level. Ceilings track the
    BNP-pattern surgical curve (Cr low-renal slope = 6.5). state is at master,
    so this is a pure lab-formula assertion."""
    from clinosim.modules.disease.protocol import load_disease_protocol

    proto = load_disease_protocol("acute_kidney_injury")
    for severity, ceiling in (("mild", 3.0), ("moderate", 4.5), ("severe", 5.5)):
        prof = PatientPhysiologicalProfile(renal_reserve=0.60)  # elderly, no CKD
        state = initialize_state(prof, [], "pt")
        state = apply_disease_onset(state, severity, proto.initial_state_impact)
        labs = derive_lab_values(state, sex="M", age=78)
        assert labs["Creatinine"] < ceiling, (
            f"{severity}: state.renal={state.renal_function:.2f} "
            f"Cr={labs['Creatinine']:.2f} >= ceiling {ceiling}"
        )


@pytest.mark.unit
def test_hco3_metabolic_axis_matches_ada_bands():
    """Pin the (state.ph_status -> HCO3) curve on the pure metabolic axis
    (respiratory_fraction=0). Guards the DKA / sepsis / CKD HCO3 calibration."""
    # state.ph_status -> HCO3 (mEq/L), tolerance 0.10
    expected = {
        0.00: 24.00,    # no disturbance
        -0.10: 20.90,   # CKD chronic mild metabolic
        -0.15: 19.35,   # severe sepsis
        -0.35: 13.15,   # DKA moderate (ADA moderate band: 10-15)
        -0.60: 5.40,    # DKA severe (ADA severe band: <10; clamped at 5.0 floor below -0.61)
    }
    for ph, target in expected.items():
        st = PhysiologicalState(patient_id="pt")
        st.respiratory_fraction = 0.0   # pure metabolic axis
        st.ph_status = ph
        labs = derive_lab_values(st, sex="M", age=55)
        assert abs(labs["HCO3"] - target) < 0.10, (
            f"ph_status={ph:.2f} HCO3={labs['HCO3']:.2f} expected≈{target}"
        )


@pytest.mark.unit
def test_dka_moderate_acidosis_in_clinical_range():
    """Moderate DKA admit should produce HCO3 ~10-15 (ADA moderate) and pH
    ~7.0-7.27 with master's initial_state_impact. state unchanged; the
    HCO3 gain change (24->31) is what lands the band."""
    from clinosim.modules.disease.protocol import load_disease_protocol

    proto = load_disease_protocol("diabetic_ketoacidosis")
    state = initialize_state(PatientPhysiologicalProfile(), [], "pt")
    # acid_base_type='metabolic' is the DKA default in apply_disease_onset.
    state = apply_disease_onset(state, "moderate", proto.initial_state_impact)
    labs = derive_lab_values(state, sex="M", age=55)
    assert 10.0 <= labs["HCO3"] <= 15.5, f"HCO3={labs['HCO3']:.2f}"
    assert labs["pH"] <= 7.27, f"pH={labs['pH']:.2f}"


# ---------------------------------------------------------------------------
# BMP Cl/Ca physiology — Phase 1 (anion_gap_status axis + Cl/Ca formulas)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_anion_gap_status_field_default_is_zero():
    state = PhysiologicalState()
    assert hasattr(state, "anion_gap_status"), \
        "PhysiologicalState should have anion_gap_status field"
    assert state.anion_gap_status == 0.0, \
        "default anion_gap_status should be 0.0 (normal AG)"


@pytest.mark.unit
def test_anion_gap_status_field_is_settable():
    state = PhysiologicalState(anion_gap_status=1.0)
    assert state.anion_gap_status == 1.0
    state.anion_gap_status = -0.5
    assert state.anion_gap_status == -0.5


def _healthy_state() -> PhysiologicalState:
    return PhysiologicalState()


def _dka_state() -> PhysiologicalState:
    """DKA: severe metabolic acidosis with high AG (ketone bodies)."""
    return PhysiologicalState(
        ph_status=-0.5, respiratory_fraction=0.0,
        anion_gap_status=1.0, glucose_status=0.6,
        volume_status=-0.4, renal_function=0.85,
    )


def _sepsis_state() -> PhysiologicalState:
    """Sepsis: high inflammation + lactic acidosis (high-AG mixed)."""
    return PhysiologicalState(
        inflammation_level=0.85, ph_status=-0.30,
        respiratory_fraction=0.0, anion_gap_status=0.7,
        perfusion_status=0.5,
    )


def _diarrhea_state() -> PhysiologicalState:
    """Non-AG hyperchloremic acidosis from GI HCO3 loss."""
    return PhysiologicalState(
        inflammation_level=0.08, ph_status=-0.25,
        respiratory_fraction=0.0, anion_gap_status=-0.5,
        volume_status=-0.22,
    )


def _ckd_state() -> PhysiologicalState:
    """CKD: low renal function with uremic mild AG."""
    return PhysiologicalState(
        renal_function=0.3, anion_gap_status=0.4,
        ph_status=-0.1, respiratory_fraction=0.0,
    )


def _dehydration_state() -> PhysiologicalState:
    """Mild dehydration (hyper-Na, no acid-base disturbance)."""
    return PhysiologicalState(sodium_status=0.3, volume_status=-0.2)


@pytest.mark.unit
def test_cl_normal_healthy_state():
    labs = derive_lab_values(_healthy_state(), sex="M", age=45)
    assert 100 <= labs["Cl"] <= 106, f"healthy Cl out of range: {labs['Cl']}"


@pytest.mark.unit
def test_cl_high_ag_dka_keeps_normal():
    """High AG: unmeasured anion absorbs HCO3 deficit, Cl stays near normal."""
    labs = derive_lab_values(_dka_state(), sex="M", age=45)
    assert labs["Cl"] <= 108, f"DKA should keep Cl near normal (got {labs['Cl']})"
    ag = labs["Na"] - labs["Cl"] - labs["HCO3"]
    assert ag >= 20, f"DKA AG should be >= 20 (got {ag})"


@pytest.mark.unit
def test_cl_non_ag_diarrhea_hyperchloremic():
    """Non-AG: Cl absorbs the HCO3 deficit 1:1, hyperchloremic."""
    labs = derive_lab_values(_diarrhea_state(), sex="M", age=45)
    assert labs["Cl"] >= 108, \
        f"diarrhea non-AG should give Cl >= 108 (got {labs['Cl']})"
    ag = labs["Na"] - labs["Cl"] - labs["HCO3"]
    assert 5 <= ag <= 14, f"diarrhea AG should be normal (got {ag})"


@pytest.mark.unit
def test_ca_normal_healthy_state():
    labs = derive_lab_values(_healthy_state(), sex="M", age=45)
    assert 9.0 <= labs["Ca"] <= 10.0, f"healthy Ca out of range: {labs['Ca']}"


@pytest.mark.unit
def test_ca_sepsis_low_calcium():
    labs = derive_lab_values(_sepsis_state(), sex="M", age=45)
    assert labs["Ca"] < 9.0, f"sepsis should give Ca < 9.0 (got {labs['Ca']})"


@pytest.mark.unit
def test_ca_ckd_low_calcium():
    labs = derive_lab_values(_ckd_state(), sex="M", age=45)
    assert labs["Ca"] < 9.2, f"CKD should give Ca < 9.2 (got {labs['Ca']})"


@pytest.mark.unit
def test_ca_dehydration_normal_upper_range():
    labs = derive_lab_values(_dehydration_state(), sex="M", age=45)
    assert 9.3 <= labs["Ca"] <= 10.0, \
        f"dehydration Ca should land in upper-normal (got {labs['Ca']})"


@pytest.mark.unit
def test_anion_gap_status_does_not_mutate_other_labs():
    """AG axis must NOT cascade. Compare derive output for AG=0 vs AG=1 with
    all other state held equal — only Cl should change. In a healthy state
    HCO3=24 so the AG term collapses; only the Cl value can shift between
    the two via the (HCO3-deficit * non_ag_fraction) term, which is zero
    when HCO3 is normal."""
    base = _healthy_state()
    high_ag = PhysiologicalState(anion_gap_status=1.0)
    labs_base = derive_lab_values(base, sex="M", age=45)
    labs_ag = derive_lab_values(high_ag, sex="M", age=45)
    for key in ("HCO3", "pCO2", "pH", "K", "Na", "Creatinine", "BUN", "Ca",
                "WBC", "CRP", "BNP", "Lactate", "Glucose", "HbA1c", "Cl"):
        assert abs(labs_base[key] - labs_ag[key]) < 1e-9, \
            f"AG axis should not affect {key} (base={labs_base[key]}, ag={labs_ag[key]})"
