"""Medication hold rules come from one source (Issue #2296)."""

from __future__ import annotations

import pytest

from clinosim.simulator import discharge_rx, medication_pipeline
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("drug", "vitals", "reason"),
    [
        ("Amlodipine 5mg", BaselineVitals(systolic_bp=85), "SBP < 90"),
        ("Candesartan 8mg", BaselineVitals(systolic_bp=88), "SBP < 90"),
        ("Carvedilol 2.5mg", BaselineVitals(heart_rate=45), "HR < 50"),
        ("Amlodipine 5mg", BaselineVitals(systolic_bp=120), None),
        ("Metformin 500mg", BaselineVitals(systolic_bp=85), None),
    ],
)
def test_mar_vital_sign_holds_come_from_chronic_medications(
    drug: str, vitals: BaselineVitals, reason: str | None
) -> None:
    assert medication_pipeline.mar_vital_hold_reason(drug, vitals) == reason


def test_admission_and_discharge_share_the_renal_drug_list() -> None:
    rules = medication_pipeline.renal_medication_rules()
    assert discharge_rx.renal_hold_drugs() == frozenset(rules)
    assert rules["celecoxib"] == "hold" and rules["ibuprofen"] == "hold"
    assert rules["enoxaparin"] == "reduce" and rules["enalapril"] == "reduce"


def test_metformin_admission_threshold_is_the_yaml_value() -> None:
    assert medication_pipeline.metformin_admission_hold_threshold() == 0.4
