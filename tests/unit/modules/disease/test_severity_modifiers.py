"""FP-SEV-MODEL Task 2: modifier-condition vocabulary + person evaluation."""

from types import SimpleNamespace

import pytest

from clinosim.modules.disease.severity import (
    EVALUABLE_CONDITIONS,
    KNOWN_MODIFIER_CONDITIONS,
    RESERVED_INTRINSIC_CONDITIONS,
    _apply_modifiers,
    _evaluate_condition,
)

pytestmark = pytest.mark.unit


def _person(**kw):
    base = dict(
        age=60,
        sex="M",
        chronic_conditions=[],
        current_medications=[],
        bmi=22.0,
        smoking_status="never",
        alcohol_use="none",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_vocabulary_partition():
    assert EVALUABLE_CONDITIONS.isdisjoint(RESERVED_INTRINSIC_CONDITIONS)
    assert KNOWN_MODIFIER_CONDITIONS == EVALUABLE_CONDITIONS | RESERVED_INTRINSIC_CONDITIONS


@pytest.mark.parametrize(
    "cond,person_kw,expected",
    [
        ("age_over_75", dict(age=80), True),
        ("age_over_75", dict(age=70), False),
        ("age_over_65", dict(age=66), True),
        ("diabetes", dict(chronic_conditions=["E11"]), True),
        ("diabetes", dict(chronic_conditions=[]), False),
        ("heart_failure", dict(chronic_conditions=["I50"]), True),
        ("CKD", dict(chronic_conditions=["N18"]), True),
        ("COPD", dict(chronic_conditions=["J44"]), True),
        ("obesity", dict(bmi=32.0), True),
        ("smoking_current", dict(smoking_status="current"), True),
    ],
)
def test_evaluable_conditions(cond, person_kw, expected):
    assert _evaluate_condition(cond, _person(**person_kw)) is expected


def test_reserved_intrinsic_never_fires():
    assert "anterior_wall_MI" in RESERVED_INTRINSIC_CONDITIONS
    assert _evaluate_condition("anterior_wall_MI", _person()) is False


def test_apply_modifiers_shifts_named_category():
    dist = {"mild": 0.0, "moderate": 0.65, "severe": 0.35}
    mods = [{"condition": "age_over_75", "moderate_multiplier": 0.8, "severe_multiplier": 1.5}]
    out = _apply_modifiers(dist, mods, _person(age=80))
    assert out["severe"] == pytest.approx(0.35 * 1.5)
    assert out["moderate"] == pytest.approx(0.65 * 0.8)
    assert out["mild"] == 0.0


def test_apply_modifiers_inactive_condition_is_noop():
    dist = {"mild": 0.1, "moderate": 0.6, "severe": 0.3}
    mods = [{"condition": "age_over_75", "severe_multiplier": 2.0}]
    out = _apply_modifiers(dist, mods, _person(age=50))
    assert out == dist
