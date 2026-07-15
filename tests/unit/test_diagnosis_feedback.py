"""Unit tests for diagnosis-treatment feedback and natural recovery."""

import pytest

from clinosim.modules.clinical_course.engine import (
    apply_diagnosis_modifier,
    compute_diagnosis_effectiveness,
    natural_recovery_directive,
)
from clinosim.types.clinical import StateChangeDirective
from clinosim.types.patient import PatientPhysiologicalProfile


class TestDiagnosisEffectiveness:
    def test_correct_diagnosis_high_confidence(self):
        eff = compute_diagnosis_effectiveness("bacterial_pneumonia", "bacterial_pneumonia", 0.9, 3)
        assert eff >= 0.9

    def test_correct_diagnosis_low_confidence(self):
        eff = compute_diagnosis_effectiveness("bacterial_pneumonia", "bacterial_pneumonia", 0.3, 1)
        assert 0.5 < eff < 0.9

    def test_no_diagnosis_yet(self):
        eff = compute_diagnosis_effectiveness(None, "bacterial_pneumonia", 0.0, 0)
        assert 0.2 <= eff <= 0.4  # empiric therapy, moderate effectiveness

    def test_no_diagnosis_harder_disease_less_effective(self):
        eff_easy = compute_diagnosis_effectiveness(None, "test", 0.0, 0, diagnostic_difficulty=0.1)
        eff_hard = compute_diagnosis_effectiveness(None, "test", 0.0, 0, diagnostic_difficulty=0.8)
        assert eff_easy > eff_hard

    def test_wrong_diagnosis(self):
        eff = compute_diagnosis_effectiveness("heart_failure", "bacterial_pneumonia", 0.8, 3)
        assert eff < 0.25  # wrong treatment, low effectiveness

    def test_partial_match(self):
        # "bacterial_pneumonia" contains "pneumonia"
        eff = compute_diagnosis_effectiveness("pneumonia", "bacterial_pneumonia", 0.7, 2)
        assert eff > 0.5  # partial match counts as correct


class TestDiagnosisModifier:
    def test_full_effectiveness_passthrough(self):
        directive = StateChangeDirective(changes={"inflammation_level": -0.05, "renal_function": 0.02})
        result = apply_diagnosis_modifier(directive, 1.0)
        assert result is directive  # no modification

    def test_dampens_recovery_deltas(self):
        directive = StateChangeDirective(changes={"inflammation_level": -0.10, "renal_function": 0.05})
        result = apply_diagnosis_modifier(directive, 0.5)
        assert result.changes["inflammation_level"] == pytest.approx(-0.05)
        assert result.changes["renal_function"] == pytest.approx(0.025)

    def test_preserves_worsening_deltas(self):
        directive = StateChangeDirective(changes={"inflammation_level": 0.10, "renal_function": -0.05})
        result = apply_diagnosis_modifier(directive, 0.3)
        # Worsening should NOT be dampened
        assert result.changes["inflammation_level"] == pytest.approx(0.10)
        assert result.changes["renal_function"] == pytest.approx(-0.05)

    def test_zero_effectiveness(self):
        directive = StateChangeDirective(changes={"inflammation_level": -0.10, "perfusion_status": 0.05})
        result = apply_diagnosis_modifier(directive, 0.0)
        assert result.changes["inflammation_level"] == pytest.approx(0.0)
        assert result.changes["perfusion_status"] == pytest.approx(0.0)

    def test_volume_toward_zero_is_improvement(self):
        directive = StateChangeDirective(changes={"volume_status": -0.05})
        # Patient has positive volume (overloaded) — moving negative is improvement
        result = apply_diagnosis_modifier(directive, 0.5, current_volume=0.3)
        assert result.changes["volume_status"] == pytest.approx(-0.025)


class TestNaturalRecovery:
    def test_returns_negative_inflammation_delta(self):
        profile = PatientPhysiologicalProfile(immune_reactivity=0.5)
        d = natural_recovery_directive(3, "bacterial_pneumonia", "moderate", profile)
        assert d.changes["inflammation_level"] < 0

    def test_higher_immune_faster_recovery(self):
        low = PatientPhysiologicalProfile(immune_reactivity=0.2)
        high = PatientPhysiologicalProfile(immune_reactivity=0.8)
        d_low = natural_recovery_directive(3, "bacterial_pneumonia", "moderate", low)
        d_high = natural_recovery_directive(3, "bacterial_pneumonia", "moderate", high)
        assert d_high.changes["inflammation_level"] < d_low.changes["inflammation_level"]

    def test_severe_slower_natural_recovery(self):
        profile = PatientPhysiologicalProfile(immune_reactivity=0.5)
        d_mild = natural_recovery_directive(3, "test", "mild", profile)
        d_severe = natural_recovery_directive(3, "test", "severe", profile)
        assert abs(d_mild.changes["inflammation_level"]) > abs(d_severe.changes["inflammation_level"])

    def test_diminishes_over_time(self):
        profile = PatientPhysiologicalProfile(immune_reactivity=0.5)
        d_early = natural_recovery_directive(3, "test", "moderate", profile)
        d_late = natural_recovery_directive(10, "test", "moderate", profile)
        assert abs(d_early.changes["inflammation_level"]) > abs(d_late.changes["inflammation_level"])
