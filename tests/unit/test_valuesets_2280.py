"""Shared value-set facility for code groups (Issue #2280)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.codes import match
from clinosim.codes.valuesets import (
    concept_group,
    group_names,
    has_condition,
    icd_base,
    iter_chronic_codes,
    normalize_icd,
)
from clinosim.modules.clinical_course._complication_risk_conditions import PATIENT_CONDITIONS
from clinosim.modules.disease.severity import EVALUABLE_CONDITIONS
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def test_normalisation() -> None:
    assert normalize_icd(" e11.9 ") == "E11.9"
    assert icd_base("E11.9") == "E11"
    assert icd_base("N18") == "N18"


def test_prefix_group_contains() -> None:
    vs = concept_group("dementia")
    assert vs.space == "internal" and vs.match == "prefix"
    assert vs.contains("F00") and vs.contains("g30.1") and not vs.contains("F32")


def test_unknown_group_raises() -> None:
    with pytest.raises(KeyError):
        concept_group("no_such_group")


def test_iter_chronic_codes_accepts_every_shape() -> None:
    items = ["E11.9", ChronicCondition(code="I10"), {"code": "N18"}, "", None]
    assert iter_chronic_codes(items) == ["E11.9", "I10", "N18"]
    person = SimpleNamespace(chronic_conditions=items)
    assert has_condition(person, "CKD")
    assert not has_condition(person, "COPD")


def test_severity_and_complication_tables_come_from_the_value_sets() -> None:
    internal = {n for n in group_names() if concept_group(n).space == "internal"}
    assert PATIENT_CONDITIONS == internal
    assert internal <= EVALUABLE_CONDITIONS


def test_match_module_is_the_shared_helper() -> None:
    assert match.has_icd_prefix([ChronicCondition(code="E11.9")], ("E11",))
