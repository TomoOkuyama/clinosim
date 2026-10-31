"""Diabetes membership is decided by one value set (Issue #2281)."""

from __future__ import annotations

import pytest

from clinosim.codes.valuesets import concept_group
from clinosim.modules.metabolic import engine as metabolic
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("code", "member"), [("E10.9", True), ("E11.9", True), ("E13.9", True), ("E15", False), ("E16.2", False)]
)
def test_diabetes_group(code: str, member: bool) -> None:
    assert concept_group("diabetes").contains(code) is member


@pytest.mark.parametrize("code", ["E10.9", "E11.9", "E13.9"])
def test_lab_generation_sites_see_every_diabetes_type(code: str) -> None:
    from clinosim.simulator.emergency import _has_diabetes as ed_dm
    from clinosim.simulator.outpatient import _has_diabetes as opd_dm

    patient = PatientProfile(chronic_conditions=[ChronicCondition(code=code)])
    assert ed_dm(patient) and opd_dm(patient)
    assert metabolic._has_diabetes([code])
