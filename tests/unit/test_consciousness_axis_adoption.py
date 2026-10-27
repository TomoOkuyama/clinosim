"""AVPU follows the consciousness_impairment axis (#2058)."""

from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.vitals_pipeline import _loc_for
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def _avpu(impairment: float, disease_id: str = "hemorrhagic_stroke", n: int = 400) -> Counter:
    rng = np.random.default_rng(7)
    state = PhysiologicalState(consciousness_impairment=impairment)
    return Counter(_loc_for(state, disease_id, 0, rng) for _ in range(n))


def test_unimpaired_neuro_patient_is_alert() -> None:
    # The admission-day random A/V/P draw for hemorrhagic stroke / SDH is
    # replaced by the state axis: no impairment, normal perfusion -> Alert.
    assert _avpu(0.0) == Counter({"A": 400})


def test_avpu_worsens_with_impairment() -> None:
    mild, moderate, deep = _avpu(0.25), _avpu(0.55), _avpu(0.85)
    assert mild["V"] > mild["P"] + mild["U"]
    assert moderate["P"] > moderate["A"]
    assert deep["U"] > deep["V"] + deep["A"]
    # bedside variability: a fixed impairment does not give one fixed AVPU
    assert len(moderate) >= 2


@pytest.mark.parametrize(
    "disease_id",
    [
        "hemorrhagic_stroke",
        "subdural_hematoma",
        "cerebral_infarction",
        "liver_cirrhosis_decompensated",
        "sepsis",
        "diabetic_ketoacidosis",
    ],
)
def test_impairing_diseases_scale_with_severity(disease_id: str) -> None:
    impact = load_disease_protocol(disease_id).initial_state_impact
    assert 0 < impact["moderate"]["consciousness_impairment"] < impact["severe"]["consciousness_impairment"] <= 1


@pytest.mark.parametrize(
    ("disease_id", "complication"),
    [
        ("hemorrhagic_stroke", "brain_herniation"),
        ("subdural_hematoma", "cerebral_herniation"),
        ("liver_cirrhosis_decompensated", "hepatic_encephalopathy_worsening"),
        ("acute_kidney_injury", "uremic_encephalopathy"),
        ("alcohol_withdrawal", "delirium_tremens"),
        ("bacterial_pneumonia", "delirium"),
    ],
)
def test_encephalopathic_complications_impair_consciousness(disease_id: str, complication: str) -> None:
    comp = next(c for c in load_disease_protocol(disease_id).complications if c["name"] == complication)
    assert comp["state_impact"]["consciousness_impairment"] > 0
