"""ED conditions set the state axes that define their presentation (#2078)."""

from __future__ import annotations

import pytest

from clinosim.modules.encounter.protocol import load_encounter_condition

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("condition_id", "axis"),
    [
        ("anxiety_panic_attack", "sympathetic_activation"),
        ("urinary_retention", "pain_level"),
        ("urinary_retention", "sympathetic_activation"),
        ("eye_foreign_body", "pain_level"),
        ("animal_bite", "pain_level"),
        ("traffic_accident_minor", "pain_level"),
        ("concussion", "consciousness_impairment"),
        ("viral_gastroenteritis", "pain_level"),
        ("food_poisoning", "pain_level"),
        ("uti_uncomplicated", "pain_level"),
    ],
)
def test_condition_sets_axis_by_severity(condition_id: str, axis: str) -> None:
    impact = load_encounter_condition(condition_id)["initial_state_impact"]
    levels = [impact[sev][axis] for sev in ("mild", "moderate", "severe")]
    assert 0 < levels[0] < levels[1] < levels[2] <= 1
