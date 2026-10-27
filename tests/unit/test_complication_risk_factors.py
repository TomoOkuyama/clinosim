"""Complication risk factors resolve against the patient, the state or a declared context (#2093)."""

from __future__ import annotations

import glob

import pytest
import yaml

from clinosim.modules.clinical_course._complication_risk_conditions import CONTEXT_CONDITIONS
from clinosim.modules.clinical_course.engine import _evaluate_risk_condition, is_supported_risk_condition
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit


def _patient(*codes: str, age: int = 85, sex: str = "F", bmi: float = 32.0) -> PatientProfile:
    return PatientProfile(age=age, sex=sex, bmi=bmi, chronic_conditions=[ChronicCondition(code=c) for c in codes])


def _ev(condition: str, patient: PatientProfile | None = None, state: PhysiologicalState | None = None) -> bool:
    return _evaluate_risk_condition(condition, state or PhysiologicalState(), patient or _patient(), 3, "moderate")


@pytest.mark.parametrize(
    ("condition", "code"),
    [("dementia", "F03.90"), ("diabetes", "E11.9"), ("CKD", "N18.4"), ("heart_failure", "I50.9"), ("COPD", "J44.9")],
)
def test_chronic_condition_factors_follow_the_problem_list(condition: str, code: str) -> None:
    assert _ev(condition, _patient(code))
    assert not _ev(condition, _patient("I10"))


def test_obesity_and_sex_factors() -> None:
    assert _ev("obesity", _patient(bmi=33.0)) and not _ev("obesity", _patient(bmi=24.0))
    assert _ev("female", _patient(sex="F")) and not _ev("female", _patient(sex="M"))


def test_state_derived_factors() -> None:
    drowsy = PhysiologicalState(consciousness_impairment=0.4)
    assert _ev("altered_consciousness", state=drowsy) and not _ev("altered_consciousness")
    assert _ev("severe_dehydration", state=PhysiologicalState(volume_status=-0.5))
    assert _ev("renal_impairment", state=PhysiologicalState(renal_function=0.4))


def test_generic_state_thresholds_cover_every_axis() -> None:
    state = PhysiologicalState(sympathetic_activation=0.6, coagulation_status=0.2)
    assert _ev("sympathetic_activation > 0.5", state=state)
    assert not _ev("sympathetic_activation > 0.7", state=state)
    assert _ev("coagulation_status < 0.4", state=state)


def test_every_yaml_risk_factor_is_supported_or_declared_context() -> None:
    unsupported = set()
    for path in glob.glob("clinosim/modules/disease/reference_data/*.yaml"):
        for comp in yaml.safe_load(open(path)).get("complications") or []:
            for rf in comp.get("risk_factors") or []:
                cond = rf.get("condition", "")
                if not is_supported_risk_condition(cond) and cond not in CONTEXT_CONDITIONS:
                    unsupported.add(cond)
    assert not unsupported, sorted(unsupported)


def test_context_conditions_do_not_overlap_supported_ones() -> None:
    assert not {c for c in CONTEXT_CONDITIONS if is_supported_risk_condition(c)}
