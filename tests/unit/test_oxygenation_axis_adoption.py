"""Respiratory conditions set the oxygenation axis by severity (#2057)."""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.encounter.protocol import load_encounter_condition

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "disease_id",
    ["asthma_exacerbation", "copd_exacerbation", "bacterial_pneumonia", "aspiration_pneumonia", "pulmonary_embolism"],
)
def test_respiratory_admissions_impair_oxygenation_by_severity(disease_id: str) -> None:
    impact = load_disease_protocol(disease_id).initial_state_impact
    levels = [impact[sev]["oxygenation_impairment"] for sev in ("mild", "moderate", "severe")]
    assert 0 < levels[0] < levels[1] < levels[2] <= 0.6


@pytest.mark.parametrize("condition_id", ["asthma_attack_mild", "copd_exacerbation_ed"])
def test_ed_respiratory_conditions_impair_oxygenation(condition_id: str) -> None:
    impact = load_encounter_condition(condition_id)["initial_state_impact"]
    assert 0 < impact["mild"]["oxygenation_impairment"] < impact["severe"]["oxygenation_impairment"]
