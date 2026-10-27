"""Painful conditions set the pain axis, and symptom axes settle under care (#2056)."""

from __future__ import annotations

import pytest

from clinosim.modules.clinical_course.engine import natural_recovery_directive
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.types.patient import PatientPhysiologicalProfile

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("disease_id", ["hip_fracture", "acute_appendicitis", "acute_pancreatitis", "acute_mi"])
def test_painful_admissions_set_pain_level(disease_id: str) -> None:
    impact = load_disease_protocol(disease_id).initial_state_impact
    levels = [impact[sev]["pain_level"] for sev in ("moderate", "severe")]
    assert 0 < levels[0] <= levels[1] <= 1


@pytest.mark.parametrize("condition_id", ["renal_colic", "shoulder_dislocation", "migraine", "ankle_sprain"])
def test_painful_ed_conditions_set_pain_level(condition_id: str) -> None:
    impact = load_encounter_condition(condition_id)["initial_state_impact"]
    levels = [impact[sev]["pain_level"] for sev in ("mild", "moderate", "severe")]
    assert 0 < levels[0] <= levels[1] <= levels[2] <= 1


def test_renal_colic_scores_as_severe_pain() -> None:
    impact = load_encounter_condition("renal_colic")["initial_state_impact"]
    assert impact["moderate"]["pain_level"] >= 0.7


def test_natural_recovery_lowers_every_symptom_axis() -> None:
    changes = natural_recovery_directive(1, "hip_fracture", "moderate", PatientPhysiologicalProfile()).changes
    for axis in ("pain_level", "sympathetic_activation", "oxygenation_impairment", "consciousness_impairment"):
        assert changes[axis] < 0
