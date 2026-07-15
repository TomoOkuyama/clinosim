"""Unit tests for clinical course engine."""

import numpy as np
import pytest

from clinosim.modules.clinical_course.engine import (
    _FALLBACK_PROBABILITIES,
    _evaluate_risk_condition,
    _interpolate,
    evaluate_complications,
    get_daily_directive,
    select_archetype,
)
from clinosim.types.patient import PatientPhysiologicalProfile


@pytest.fixture
def normal_profile():
    return PatientPhysiologicalProfile()


@pytest.fixture
def rng():
    return np.random.default_rng(42)


@pytest.mark.unit
class TestSelectArchetype:
    def test_returns_valid_archetype(self, normal_profile, rng):
        result = select_archetype("moderate", normal_profile, rng)
        assert result in _FALLBACK_PROBABILITIES

    def test_severe_favors_deterioration(self, rng):
        profile = PatientPhysiologicalProfile()
        counts: dict[str, int] = {}
        for _ in range(1000):
            a = select_archetype("severe", profile, rng)
            counts[a] = counts.get(a, 0) + 1
        assert counts.get("gradual_deterioration", 0) > 30
        assert counts.get("sudden_deterioration", 0) > 10

    def test_mild_favors_smooth(self, rng):
        profile = PatientPhysiologicalProfile()
        counts: dict[str, int] = {}
        for _ in range(1000):
            a = select_archetype("mild", profile, rng)
            counts[a] = counts.get(a, 0) + 1
        assert counts.get("smooth_recovery", 0) > 500

    def test_low_immune_reactivity_increases_resistance(self, rng):
        # FP-YAML-2b: the immune_reactivity -> treatment_resistant heuristic moved from
        # a hardcoded rule to the disease YAML archetype_modifiers block. Exercise the
        # same clinical intent through the new YAML-driven path.
        mods = [
            {"condition": "immune_reactivity < 0.3", "effect": {"treatment_resistant": 0.10, "smooth_recovery": -0.10}}
        ]
        low = PatientPhysiologicalProfile(immune_reactivity=0.2)
        counts: dict[str, int] = {}
        for _ in range(1000):
            a = select_archetype("moderate", low, rng, protocol_modifiers=mods, patient=None)
            counts[a] = counts.get(a, 0) + 1
        normal = PatientPhysiologicalProfile(immune_reactivity=0.5)
        normal_counts: dict[str, int] = {}
        rng2 = np.random.default_rng(42)
        for _ in range(1000):
            a = select_archetype("moderate", normal, rng2, protocol_modifiers=mods, patient=None)
            normal_counts[a] = normal_counts.get(a, 0) + 1
        assert counts.get("treatment_resistant", 0) > normal_counts.get("treatment_resistant", 0)

    def test_yaml_archetypes_used_when_provided(self, normal_profile, rng):
        yaml_archs = {
            "custom_arch": {"probability": 0.99},
            "rare_arch": {"probability": 0.01},
        }
        counts: dict[str, int] = {}
        for _ in range(100):
            a = select_archetype("moderate", normal_profile, rng, protocol_archetypes=yaml_archs)
            counts[a] = counts.get(a, 0) + 1
        assert counts.get("custom_arch", 0) > 80


@pytest.mark.unit
class TestGetDailyDirective:
    def test_smooth_recovery_day0_rises(self, normal_profile):
        d = get_daily_directive("smooth_recovery", 0, normal_profile)
        assert d.changes["inflammation_level"] > 0

    def test_smooth_recovery_day7_declines(self, normal_profile):
        d = get_daily_directive("smooth_recovery", 7, normal_profile)
        assert d.changes["inflammation_level"] < 0

    def test_sudden_deterioration_day2_spike(self, normal_profile):
        d = get_daily_directive("sudden_deterioration", 2, normal_profile)
        assert d.changes["inflammation_level"] > 0.2

    def test_treatment_resistant_day3_still_high(self, normal_profile):
        d = get_daily_directive("treatment_resistant", 3, normal_profile)
        assert d.changes["inflammation_level"] > 0

    def test_electrolyte_axes_in_trajectory_are_applied(self, normal_profile):
        """A course_archetype trajectory may drive sodium_status / anion_gap_status.

        Regression guard for the recognized-var list drift: these bipolar axes
        exist on ClinicalState and in _variable_range, but were missing from the
        get_daily_directive iteration list, so a trajectory referencing them was
        silently dropped. HF fluid overload / GI acidosis evolving over days is
        the realistic use case.
        """
        archs = {
            "electrolyte_shift": {
                "probability": 1.0,
                "trajectory": {
                    "sodium_status": {0: -0.2, 5: -0.4},
                    "anion_gap_status": {0: 0.1, 5: 0.5},
                },
            }
        }
        d = get_daily_directive("electrolyte_shift", 5, normal_profile, protocol_archetypes=archs)
        assert "sodium_status" in d.changes
        assert "anion_gap_status" in d.changes

    def test_all_fallback_archetypes_produce_directives(self, normal_profile):
        for name in _FALLBACK_PROBABILITIES:
            d = get_daily_directive(name, 5, normal_profile)
            assert "inflammation_level" in d.changes
            assert name in d.reason and "day5" in d.reason

    def test_yaml_trajectory_used(self, normal_profile):
        yaml_archs = {
            "custom": {
                "trajectory": {
                    "inflammation_level": {0: -0.50, 7: -0.10},
                },
            },
        }
        d = get_daily_directive("custom", 0, normal_profile, protocol_archetypes=yaml_archs)
        assert d.changes["inflammation_level"] < 0  # custom trajectory


@pytest.mark.unit
class TestComplications:
    def test_complication_triggers(self):
        rng = np.random.default_rng(0)

        class MockState:
            renal_function = 0.3
            volume_status = -0.4
            perfusion_status = 0.6

        class MockPatient:
            age = 80
            physiological_profile = PatientPhysiologicalProfile(delirium_susceptibility=0.5)

        complications = [
            {
                "name": "aki",
                "probability_per_day": 0.99,  # almost certain for testing
                "onset_day_range": [1, 5],
                "risk_factors": [{"condition": "renal_function < 0.5", "multiplier": 2.0}],
                "state_impact": {"renal_function": -0.15},
            }
        ]

        triggered = evaluate_complications(3, MockState(), MockPatient(), complications, set(), rng)
        assert len(triggered) == 1
        assert triggered[0]["name"] == "aki"

    def test_complication_respects_onset_window(self):
        rng = np.random.default_rng(0)

        class MockState:
            pass

        class MockPatient:
            age = 50

        complications = [
            {
                "name": "late_comp",
                "probability_per_day": 1.0,
                "onset_day_range": [10, 20],
            }
        ]

        # Day 3: outside window
        triggered = evaluate_complications(3, MockState(), MockPatient(), complications, set(), rng)
        assert len(triggered) == 0

        # Day 15: inside window
        triggered = evaluate_complications(15, MockState(), MockPatient(), complications, set(), rng)
        assert len(triggered) == 1

    def test_severity_severe_condition_applies_multiplier_when_severe(self):
        rng = np.random.default_rng(0)

        class MockState:
            pass

        class MockPatient:
            age = 50

        complications = [
            {
                "name": "severe_only_comp",
                "probability_per_day": 0.5,
                "onset_day_range": [1, 5],
                "risk_factors": [{"condition": "severity_severe", "multiplier": 2.0}],
            }
        ]

        # 0.5 * 2.0 = 1.0 -> rng.random() (always < 1.0) guarantees a fire,
        # independent of the specific draw, when severity="severe".
        triggered = evaluate_complications(
            3,
            MockState(),
            MockPatient(),
            complications,
            set(),
            rng,
            severity="severe",
        )
        assert len(triggered) == 1

    def test_severity_severe_condition_not_applied_when_not_severe(self):
        rng = np.random.default_rng(0)

        class MockState:
            pass

        class MockPatient:
            age = 50

        complications = [
            {
                "name": "severe_only_comp",
                "probability_per_day": 0.0,
                "onset_day_range": [1, 5],
                "risk_factors": [{"condition": "severity_severe", "multiplier": 2.0}],
            }
        ]

        # Base probability is 0.0; the multiplier must NOT apply when
        # severity != "severe", so prob stays 0.0 and never fires.
        triggered = evaluate_complications(
            3,
            MockState(),
            MockPatient(),
            complications,
            set(),
            rng,
            severity="moderate",
        )
        assert len(triggered) == 0


@pytest.mark.unit
class TestInterpolation:
    def test_exact_day(self):
        trajectory = {0: 0.10, 3: -0.08, 7: -0.06}
        assert _interpolate(trajectory, 0) == pytest.approx(0.10)
        assert _interpolate(trajectory, 3) == pytest.approx(-0.08)

    def test_between_days(self):
        trajectory = {0: 0.10, 2: -0.10}
        result = _interpolate(trajectory, 1)
        assert result == pytest.approx(0.0, abs=0.01)

    def test_before_first_day(self):
        trajectory = {2: 0.05, 5: -0.03}
        assert _interpolate(trajectory, 0) == pytest.approx(0.05)

    def test_after_last_day(self):
        trajectory = {0: 0.10, 7: -0.05, 14: -0.02}
        assert _interpolate(trajectory, 20) == pytest.approx(-0.02)


@pytest.mark.unit
class TestEvaluateRiskConditionSeverity:
    def test_severity_severe_matches_severe(self):
        assert _evaluate_risk_condition("severity_severe", None, None, 1, "severe") is True

    def test_severity_severe_does_not_match_moderate_or_mild(self):
        assert _evaluate_risk_condition("severity_severe", None, None, 1, "moderate") is False
        assert _evaluate_risk_condition("severity_severe", None, None, 1, "mild") is False
