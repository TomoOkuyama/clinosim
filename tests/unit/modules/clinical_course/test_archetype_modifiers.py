"""FP-YAML-2b Task 1: archetype_modifiers condition evaluator + applier."""

from types import SimpleNamespace

import pytest

from clinosim.modules.clinical_course.engine import (
    ARCHETYPE_EXPRESSION_VARS,
    ARCHETYPE_RESERVED_CONDITIONS,
    _apply_archetype_modifiers,
    _eval_archetype_condition,
)

pytestmark = pytest.mark.unit


def _profile(immune=0.5, treat=1.0):
    return SimpleNamespace(immune_reactivity=immune, treatment_sensitivity=treat)


def _patient(age=60, chronic=None):
    return SimpleNamespace(
        age=age,
        chronic_conditions=chronic or [],
        current_medications=[],
        bmi=22.0,
        smoking_status="never",
        alcohol_use="none",
    )


def test_expression_vars_exposed():
    assert "age" in ARCHETYPE_EXPRESSION_VARS
    assert "immune_reactivity" in ARCHETYPE_EXPRESSION_VARS


@pytest.mark.parametrize(
    "cond,prof,pat,expected",
    [
        ("age >= 80", _profile(), _patient(age=82), True),
        ("age >= 80", _profile(), _patient(age=70), False),
        ("immune_reactivity < 0.3", _profile(immune=0.2), _patient(), True),
        ("immune_reactivity < 0.3", _profile(immune=0.5), _patient(), False),
        ("treatment_sensitivity > 1.2", _profile(treat=1.5), _patient(), True),
        ("diabetes", _profile(), _patient(chronic=["E11"]), True),
        ("diabetes", _profile(), _patient(chronic=[]), False),
    ],
)
def test_eval_condition(cond, prof, pat, expected):
    assert _eval_archetype_condition(cond, prof, pat) is expected


def test_reserved_intrinsic_and_unknown_return_false():
    assert "tpa_received" in ARCHETYPE_RESERVED_CONDITIONS
    assert _eval_archetype_condition("tpa_received", _profile(), _patient()) is False
    assert _eval_archetype_condition("prior_dka_episodes >= 2", _profile(), _patient()) is False


def test_apply_modifiers_shifts_probs():
    probs = {"smooth_recovery": 0.55, "treatment_resistant": 0.08, "gradual_deterioration": 0.05}
    mods = [
        {
            "condition": "age >= 80",
            "effect": {"gradual_deterioration": 0.08, "smooth_recovery": -0.12},
        }
    ]
    out = _apply_archetype_modifiers(dict(probs), mods, _profile(), _patient(age=85))
    assert out["gradual_deterioration"] == pytest.approx(0.05 + 0.08)
    assert out["smooth_recovery"] == pytest.approx(0.55 - 0.12)


def test_apply_modifiers_inactive_noop():
    probs = {"smooth_recovery": 0.55, "gradual_deterioration": 0.05}
    mods = [{"condition": "age >= 80", "effect": {"gradual_deterioration": 0.08}}]
    assert _apply_archetype_modifiers(dict(probs), mods, _profile(), _patient(age=50)) == probs
