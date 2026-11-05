"""Issue #2630: a child below working age has no occupation Observation."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import _build_occupation_observation
from clinosim.modules.population._identity import DEVELOPMENTAL_STAGES

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("stage", ["infant", "preschool", "elementary_student", "middle_school_student"])
def test_a_developmental_stage_is_not_an_occupation(stage: str) -> None:
    assert stage in DEVELOPMENTAL_STAGES
    assert _build_occupation_observation(stage, "P1", "US") is None


@pytest.mark.parametrize("occupation", ["office", "retired", "student", "high_school_student"])
def test_an_adult_or_student_occupation_is_kept(occupation: str) -> None:
    obs = _build_occupation_observation(occupation, "P1", "US")
    assert obs is not None and obs["valueCodeableConcept"]["coding"][0]["code"] == occupation
