"""Complications use the state axes as risk factors where the mechanism applies (#2094)."""

from __future__ import annotations

import pytest

from clinosim.modules.clinical_course.engine import _evaluate_risk_condition
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("disease_id", "complication", "axis"),
    [
        ("alcohol_withdrawal", "delirium_tremens", "sympathetic_activation"),
        ("alcohol_withdrawal", "withdrawal_seizure", "sympathetic_activation"),
        ("hemorrhagic_stroke", "aspiration_pneumonia", "consciousness_impairment"),
        ("cerebral_infarction", "aspiration_pneumonia", "consciousness_impairment"),
        ("hip_fracture", "postoperative_delirium", "pain_level"),
        ("bacterial_pneumonia", "delirium", "oxygenation_impairment"),
    ],
)
def test_axis_risk_factor_present_and_fires(disease_id: str, complication: str, axis: str) -> None:
    comp = next(c for c in load_disease_protocol(disease_id).complications if c["name"] == complication)
    factors = [rf for rf in comp["risk_factors"] if rf["condition"].startswith(axis)]
    assert factors and factors[0]["multiplier"] > 1
    high = PhysiologicalState(**{axis: 0.9})
    assert _evaluate_risk_condition(factors[0]["condition"], high, PatientProfile(), 2, "moderate")
    assert not _evaluate_risk_condition(factors[0]["condition"], PhysiologicalState(), PatientProfile(), 2, "moderate")
