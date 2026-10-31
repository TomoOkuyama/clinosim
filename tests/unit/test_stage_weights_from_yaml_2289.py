"""Activation stage weights and labels come from the longitudinal stage YAMLs (Issue #2289)."""

from __future__ import annotations

import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.patient import _severity_activation as sa

pytestmark = pytest.mark.unit

_PAIRS = {
    ("N18_STAGES", "N18_STAGE_WEIGHTS"): "ckd_stage_n18",
    ("I50_STAGES", "I50_STAGE_WEIGHTS_DEFAULT"): "heart_failure_stage_i50",
    ("J44_STAGES", "J44_STAGE_WEIGHTS"): "copd_stage_j44",
    ("I25_STAGES", "I25_STAGE_WEIGHTS"): "ischemic_heart_stage_i25",
    ("F00_STAGES", "F00_STAGE_WEIGHTS"): "dementia_stage_f00",
    ("K70_STAGES", "K70_STAGE_WEIGHTS"): "alcoholic_liver_stage_k70",
    ("K74_STAGES", "K74_STAGE_WEIGHTS"): "fibrosis_liver_stage_k74",
    ("G20_STAGES", "G20_STAGE_WEIGHTS"): "parkinson_stage_g20",
    ("I48_STAGES", "I48_STAGE_WEIGHTS"): "atrial_fib_stage_i48",
    ("G35_STAGES", "G35_STAGE_WEIGHTS"): "multiple_sclerosis_stage_g35",
    ("I69_3_STAGES", "I69_3_STAGE_WEIGHTS"): "stroke_sequela_stage_i69_3",
    ("I69_3_STAGES", "I69_1_STAGE_WEIGHTS"): "stroke_sequela_stage_i69_1",
}


@pytest.mark.parametrize(("names", "attribute"), list(_PAIRS.items()), ids=lambda x: str(x))
def test_stage_table_equals_the_yaml_initial_distribution(names: tuple[str, str], attribute: str) -> None:
    dist = load_attribute_specs()[attribute].body.initial_distribution
    labels, weights = getattr(sa, names[0]), getattr(sa, names[1])
    assert dict(zip(labels, weights, strict=True)) == dict(dist)


def test_ckd_stage_severity_uses_the_stored_label() -> None:
    assert set(sa.STAGE_SEVERITY["N18"]) == set(sa.N18_STAGES)
    assert sa.STAGE_SEVERITY["N18"]["CKD G5"] == 0.90
