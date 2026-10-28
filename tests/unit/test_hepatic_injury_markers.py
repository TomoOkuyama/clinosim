"""Liver injury markers follow hepatic injury, not the age-reduced reserve (Issue #2125)."""

from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.clinical import PhysiologicalState

pytestmark = pytest.mark.unit


def _labs(hepatic: float) -> dict[str, float]:
    return derive_lab_values(PhysiologicalState(patient_id="P", hepatic_function=hepatic), "M", 75)


@pytest.mark.parametrize("hepatic", [1.0, 0.95, 0.82, 0.72])
def test_normal_reserve_keeps_liver_tests_in_range(hepatic: float) -> None:
    # 0.82 = median reserve at 75 (Beta(30, 2) minus the age penalty); 0.72 ~ 5th percentile at 90.
    labs = _labs(hepatic)
    assert labs["AST"] <= 40 and labs["ALT"] <= 45
    assert labs["T_Bil"] <= 1.2 and labs["ALP"] <= 130 and labs["LDH"] <= 250


def test_hepatic_injury_still_raises_enzymes() -> None:
    severe = _labs(0.15)  # decompensated cirrhosis
    assert severe["AST"] > 300 and severe["T_Bil"] > 8
    assert _labs(0.55)["AST"] > 80
    assert _labs(0.4)["AST"] > _labs(0.55)["AST"] > _labs(0.7)["AST"]


def _state(code: str, score: float, reserve: float = 0.88):
    from clinosim.modules.physiology.engine import initialize_state
    from clinosim.types.patient import ChronicCondition, PatientPhysiologicalProfile

    profile = PatientPhysiologicalProfile(hepatic_reserve=reserve)
    return initialize_state(profile, [ChronicCondition(code=code, severity_score=score)] if code else [], "P")


@pytest.mark.parametrize("code", ["K76.0", "F10.20"])
def test_fatty_liver_and_alcohol_raise_transaminases_when_advanced(code: str) -> None:
    mild = derive_lab_values(_state(code, 0.15), "M", 55)
    advanced = derive_lab_values(_state(code, 0.35), "M", 55)
    assert mild["ALT"] <= 45 and mild["AST"] <= 40
    assert advanced["ALT"] > 56 and advanced["AST"] > 40
    assert derive_lab_values(_state("", 0.0), "M", 55)["ALT"] <= 45
