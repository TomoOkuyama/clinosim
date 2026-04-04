"""Unit tests for clinical course engine."""

import numpy as np
import pytest

from clinosim.modules.clinical_course.engine import (
    ARCHETYPES,
    get_daily_directive,
    select_archetype,
    _interpolate,
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
        assert result in ARCHETYPES

    def test_severe_favors_deterioration(self, rng):
        profile = PatientPhysiologicalProfile()
        counts: dict[str, int] = {}
        for _ in range(1000):
            a = select_archetype("severe", profile, rng)
            counts[a] = counts.get(a, 0) + 1
        # Deterioration archetypes should be more common in severe
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
        profile = PatientPhysiologicalProfile(immune_reactivity=0.2)
        counts: dict[str, int] = {}
        for _ in range(1000):
            a = select_archetype("moderate", profile, rng)
            counts[a] = counts.get(a, 0) + 1
        normal_profile = PatientPhysiologicalProfile(immune_reactivity=0.5)
        normal_counts: dict[str, int] = {}
        rng2 = np.random.default_rng(42)
        for _ in range(1000):
            a = select_archetype("moderate", normal_profile, rng2)
            normal_counts[a] = normal_counts.get(a, 0) + 1
        assert counts.get("treatment_resistant", 0) > normal_counts.get("treatment_resistant", 0)


@pytest.mark.unit
class TestGetDailyDirective:
    def test_smooth_recovery_day0_rises(self, normal_profile):
        d = get_daily_directive("smooth_recovery", 0, normal_profile)
        assert d.changes["inflammation_level"] > 0  # initial rise

    def test_smooth_recovery_day7_declines(self, normal_profile):
        d = get_daily_directive("smooth_recovery", 7, normal_profile)
        assert d.changes["inflammation_level"] < 0  # declining

    def test_sudden_deterioration_day2_spike(self, normal_profile):
        d = get_daily_directive("sudden_deterioration", 2, normal_profile)
        assert d.changes["inflammation_level"] > 0.2  # major spike
        assert d.changes["perfusion_status"] < -0.2  # shock

    def test_treatment_resistant_day3_still_high(self, normal_profile):
        d = get_daily_directive("treatment_resistant", 3, normal_profile)
        assert d.changes["inflammation_level"] > 0  # still worsening

    def test_all_archetypes_produce_directives(self, normal_profile):
        for name in ARCHETYPES:
            d = get_daily_directive(name, 5, normal_profile)
            assert "inflammation_level" in d.changes
            assert d.reason == f"{name}_day5"


@pytest.mark.unit
class TestInterpolation:
    def test_exact_day(self):
        trajectory = {0: 0.10, 3: -0.08, 7: -0.06}
        assert _interpolate(trajectory, 0) == pytest.approx(0.10)
        assert _interpolate(trajectory, 3) == pytest.approx(-0.08)

    def test_between_days(self):
        trajectory = {0: 0.10, 2: -0.10}
        result = _interpolate(trajectory, 1)
        assert result == pytest.approx(0.0, abs=0.01)  # midpoint

    def test_before_first_day(self):
        trajectory = {2: 0.05, 5: -0.03}
        assert _interpolate(trajectory, 0) == pytest.approx(0.05)

    def test_after_last_day(self):
        trajectory = {0: 0.10, 7: -0.05, 14: -0.02}
        assert _interpolate(trajectory, 20) == pytest.approx(-0.02)
