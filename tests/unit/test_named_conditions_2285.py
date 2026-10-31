"""Issue #2285: severity modifiers and complication risk factors resolve named
patient conditions through one table (the internal value sets)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.codes.valuesets import concept_group, has_condition, patient_condition_names
from clinosim.modules.clinical_course.engine import _evaluate_risk_condition
from clinosim.modules.disease.protocol import load_all_disease_protocols
from clinosim.modules.disease.severity import (
    EVALUABLE_CONDITIONS,
    RESERVED_INTRINSIC_CONDITIONS,
    _evaluate_condition,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def _person(*codes: str) -> SimpleNamespace:
    return SimpleNamespace(age=60, sex="M", bmi=24.0, smoking_status="never", chronic_conditions=list(codes))


def _patient(*codes: str) -> SimpleNamespace:
    return SimpleNamespace(
        age=60, sex="M", bmi=24.0, smoking_status="never", chronic_conditions=[ChronicCondition(code=c) for c in codes]
    )


def test_every_named_condition_in_the_disease_yamls_resolves_through_the_table() -> None:
    names = patient_condition_names()
    used: set[str] = set()
    for proto in load_all_disease_protocols().values():
        for mod in (proto.severity or {}).get("modifiers") or []:
            used.add(str(mod.get("condition", "")))
        for comp in proto.complications or []:
            for rf in comp.get("risk_factors") or []:
                used.add(str(rf.get("condition", "")))
    # Every name that looks up a value set is resolved through the shared table,
    # never through a module-local list.
    assert names <= EVALUABLE_CONDITIONS
    assert not (names & RESERVED_INTRINSIC_CONDITIONS)
    assert "immunosuppressed" in used & names


@pytest.mark.parametrize("name", sorted(patient_condition_names()))
def test_both_evaluators_agree_for_every_named_condition(name: str) -> None:
    member = concept_group(name).members[0]
    code = member if "." in member or len(member) > 1 else f"{member}50.9"
    state = PhysiologicalState()
    for codes, expected in (((code,), True), (("Z00.0",), False)):
        person, patient = _person(*codes), _patient(*codes)
        assert has_condition(person, name) is expected
        assert _evaluate_condition(name, person) is expected
        assert _evaluate_risk_condition(name, state, patient, day=1, severity="mild") is expected


def test_immunosuppressed_is_the_same_for_severity_and_complications() -> None:
    state = PhysiologicalState()
    for code in ("D84.9", "Z94.0", "B20"):
        assert _evaluate_condition("immunosuppressed", _person(code))
        assert _evaluate_risk_condition("immunosuppressed", state, _patient(code), day=1, severity="mild")
    assert not _evaluate_condition("immunosuppressed", _person("I10"))
    assert not _evaluate_risk_condition("immunosuppressed", state, _patient("I10"), day=1, severity="mild")
