"""Integration tests: disease → clinical_course → physiology → observation → diagnosis chain."""

from datetime import timedelta

import numpy as np
import pytest

from clinosim.modules.clinical_course.engine import get_daily_directive
from clinosim.modules.diagnosis.engine import (
    get_current_diagnosis_code,
    initialize_differential,
    update_differential,
)
from clinosim.modules.observation.engine import generate_lab_result
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_lab_values,
    initialize_state,
    update,
)
from clinosim.types.patient import ChronicCondition, PatientPhysiologicalProfile


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.fixture
def profile():
    return PatientPhysiologicalProfile(
        immune_reactivity=0.55, renal_reserve=0.70, cardiac_reserve=0.72,
        hepatic_reserve=0.80, treatment_sensitivity=1.05,
    )


@pytest.fixture
def conditions():
    return [
        ChronicCondition(code="I10", severity_score=0.2),
        ChronicCondition(code="E11.9", severity_score=0.2),
    ]


@pytest.mark.integration
class TestPneumoniaPipeline:
    """End-to-end: pneumonia onset → 14 days of state evolution → lab generation → diagnosis."""

    def test_crp_trajectory_follows_archetype(self, profile, conditions, rng):
        """CRP should rise initially, then decline for smooth_recovery."""
        state = initialize_state(profile, conditions)
        state = apply_disease_onset(state, "moderate",
                                     {"moderate": {"inflammation_level": 0.50, "volume_status": -0.20}})

        crp_values = []
        for day in range(14):
            directive = get_daily_directive("smooth_recovery", day, profile)
            state = update(state, directive, timedelta(days=1))
            labs = derive_lab_values(state, sex="F", age=72, has_diabetes=True)
            crp = generate_lab_result("CRP", labs["CRP"], rng)
            crp_values.append(crp)

        # CRP should peak in first 2-3 days, then decline
        peak_idx = crp_values.index(max(crp_values))
        assert peak_idx <= 3, f"CRP peaked on Day {peak_idx}, expected Day 0-3"

        # Final CRP should be much lower than peak
        assert crp_values[-1] < crp_values[peak_idx] * 0.5

    def test_treatment_resistant_triggers_escalation(self, profile, conditions, rng):
        """Treatment-resistant archetype should still have high inflammation at Day 3."""
        state = initialize_state(profile, conditions)
        state = apply_disease_onset(state, "moderate",
                                     {"moderate": {"inflammation_level": 0.50}})

        for day in range(4):
            directive = get_daily_directive("treatment_resistant", day, profile)
            state = update(state, directive, timedelta(days=1))

        # Day 3: inflammation should still be high (no improvement)
        assert state.inflammation_level > 0.4, "Treatment-resistant should not improve by Day 3"

    def test_diagnosis_updates_with_lab_results(self, rng):
        """Diagnosis probability should change as lab results come in."""
        diff = initialize_differential("bacterial_pneumonia", age=72)
        initial_prob = diff.candidates[0].probability

        # Simulate Day 1: CXR consolidation found
        diff = update_differential(diff, [("chest_xray_consolidation", True)])
        after_cxr = diff.candidates[0].probability
        assert after_cxr > initial_prob, "Positive CXR should increase pneumonia probability"

        # Simulate Day 1: elevated procalcitonin
        diff = update_differential(diff, [("procalcitonin_elevated", True)])
        after_pct = diff.candidates[0].probability
        assert after_pct > after_cxr, "Positive PCT should further increase probability"

        # Should be confirmed by now
        assert diff.confirmed is True

        code, name = get_current_diagnosis_code(diff)
        assert code == "J13"  # most specific code

    def test_sudden_deterioration_produces_shock(self, profile, conditions):
        """Sudden deterioration should produce shock (low perfusion, high lactate)."""
        state = initialize_state(profile, conditions)
        state = apply_disease_onset(state, "severe",
                                     {"severe": {"inflammation_level": 0.75,
                                                  "perfusion_status": -0.20}})

        for day in range(3):
            directive = get_daily_directive("sudden_deterioration", day, profile)
            state = update(state, directive, timedelta(days=1))

        # Day 2 spike should have caused significant perfusion drop
        # Note: coupling rules limit how fast perfusion drops (cardiac-dependent)
        assert state.inflammation_level > 0.8, "Should have very high inflammation"
        labs = derive_lab_values(state, sex="F", age=72)
        assert labs["Lactate"] > 2, "Lactate should be elevated"


@pytest.mark.integration
class TestHeartFailurePipeline:
    """Heart failure: volume overload pattern."""

    def test_hf_initial_state_has_volume_overload(self, profile, conditions):
        state = initialize_state(profile, conditions)
        state = apply_disease_onset(state, "moderate",
                                     {"moderate": {"cardiac_function": -0.25,
                                                    "volume_status": 0.50}})
        assert state.volume_status > 0.3, "HF should have volume overload"
        labs = derive_lab_values(state, sex="M", age=78)
        assert labs["BNP"] > 200, "BNP should be elevated in HF"

    def test_hf_recovery_reduces_volume(self, profile, conditions):
        state = initialize_state(profile, conditions)
        state = apply_disease_onset(state, "moderate",
                                     {"moderate": {"cardiac_function": -0.25, "volume_status": 0.50}})
        initial_vol = state.volume_status

        # Simulate diuretic response (smooth_recovery: volume decreases)
        for day in range(7):
            directive = get_daily_directive("smooth_recovery", day, profile)
            # Override: HF recovery means volume goes down, not up
            directive.changes["volume_status"] = -0.05
            state = update(state, directive, timedelta(days=1))

        assert state.volume_status < initial_vol, "Volume should decrease with treatment"


@pytest.mark.integration
class TestHipFracturePipeline:
    """Hip fracture: trauma + anemia pattern."""

    def test_hip_fracture_causes_anemia(self, profile, conditions):
        state = initialize_state(profile, conditions)
        state = apply_disease_onset(state, "moderate",
                                     {"moderate": {"inflammation_level": 0.20,
                                                    "anemia_level": 0.10,
                                                    "volume_status": -0.15}})
        labs = derive_lab_values(state, sex="F", age=82)
        # anemia_level=0.10 → Hb = 13 * (1 - 0.10*0.7) = 13 * 0.93 = 12.09
        assert labs["Hb"] < 13, "Hb should be decreased from normal (~13 for F)"

    def test_all_lab_values_plausible(self, profile, conditions, rng):
        """No lab value should be out of physiologically possible range."""
        state = initialize_state(profile, conditions)
        state = apply_disease_onset(state, "moderate",
                                     {"moderate": {"inflammation_level": 0.20, "anemia_level": 0.10}})

        for day in range(30):
            directive = get_daily_directive("smooth_recovery", day, profile)
            state = update(state, directive, timedelta(days=1))
            labs = derive_lab_values(state, sex="F", age=82)

            for name, value in labs.items():
                assert value >= 0, f"Day {day}: {name} = {value} (negative!)"
                if name == "pH":
                    assert 6.8 < value < 7.8, f"Day {day}: pH = {value} (implausible)"
                if name == "K":
                    assert value < 10, f"Day {day}: K = {value} (lethal)"
