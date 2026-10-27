"""Disease YAMLs cover the state axes where the mechanism applies (#2079)."""

from __future__ import annotations

import pytest

from clinosim.modules.clinical_course._clinical_course_thresholds import SYMPTOM_AXIS_DAILY_RECOVERY
from clinosim.modules.disease.protocol import load_disease_protocol

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("disease_id", "axis"),
    [
        ("heart_failure_exacerbation", "oxygenation_impairment"),
        ("influenza", "oxygenation_impairment"),
        ("influenza", "pain_level"),
        ("traffic_accident_severe", "consciousness_impairment"),
        ("fall_from_height", "consciousness_impairment"),
    ],
)
def test_initial_impact_sets_axis(disease_id: str, axis: str) -> None:
    impact = load_disease_protocol(disease_id).initial_state_impact
    assert impact["severe"][axis] > impact["moderate"][axis] > 0


@pytest.mark.parametrize(
    ("disease_id", "axis"),
    [
        ("bacterial_pneumonia", "oxygenation_impairment"),
        ("aspiration_pneumonia", "oxygenation_impairment"),
        ("copd_exacerbation", "oxygenation_impairment"),
        ("asthma_exacerbation", "oxygenation_impairment"),
        ("influenza", "oxygenation_impairment"),
        ("heart_failure_exacerbation", "oxygenation_impairment"),
        ("sepsis", "oxygenation_impairment"),
        ("sepsis", "consciousness_impairment"),
        ("hemorrhagic_stroke", "consciousness_impairment"),
        ("subdural_hematoma", "consciousness_impairment"),
    ],
)
def test_deterioration_archetypes_worsen_axis(disease_id: str, axis: str) -> None:
    arches = load_disease_protocol(disease_id).course_archetypes
    for name in ("gradual_deterioration", "sudden_deterioration"):
        traj = arches[name]["trajectory"][axis]
        # net worsening: the peak daily delta exceeds the axis's daily recovery
        assert max(traj.values()) > SYMPTOM_AXIS_DAILY_RECOVERY[axis]
