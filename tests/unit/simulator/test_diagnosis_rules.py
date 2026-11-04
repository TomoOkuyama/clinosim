"""The simulators' diagnosis-coding rule tables (Issue #2552)."""

from __future__ import annotations

import dataclasses

import pytest

from clinosim.modules.pediatric.calendar import load_pediatric_schedule
from clinosim.simulator import diagnosis_rules
from clinosim.simulator.diagnosis_rules import (
    LabFindingRule,
    UnknownConditionCodes,
    day1_imaging_findings,
    fallback_visit_code,
    lab_finding_rules,
    unknown_condition_codes,
    visit_purpose_code,
)


def test_pediatric_vaccination_visits_get_z23_and_other_pediatric_visits_z00() -> None:
    for entry in load_pediatric_schedule().values():
        visit = entry["disease_id"]
        expected = "Z23" if "immuniz" in visit or "vaccin" in visit else "Z00"
        assert visit_purpose_code("pediatric_visit", visit) == expected, visit
    assert visit_purpose_code("pediatric_visit", "pediatric_visit") == "Z00"


def test_screening_visits_default_to_general_examination_and_others_have_no_purpose_code() -> None:
    assert visit_purpose_code("health_screening", "flu_vaccination") == "Z00.0"
    assert visit_purpose_code("chronic_followup", "I10") == ""
    assert fallback_visit_code() == "Z09"


def test_unknown_fever_keeps_r50_9_and_other_patterns_r53_1_or_r68_8() -> None:
    assert unknown_condition_codes("fever_unknown") == UnknownConditionCodes("R50.9", "R50.9", "R50.9")
    for pattern in ("weight_loss_unexplained", "malaise_fatigue", "elevated_inflammatory_markers"):
        assert unknown_condition_codes(pattern) == UnknownConditionCodes("R53.1", "R53.1", "R68.8")


def test_differential_findings() -> None:
    assert lab_finding_rules() == {
        "CRP": LabFindingRule("crp_above_100", 100.0),
        "WBC": LabFindingRule("wbc_elevated", 15000.0),
    }
    assert day1_imaging_findings("bacterial_pneumonia") == ("chest_xray_consolidation", "procalcitonin_elevated")
    assert day1_imaging_findings("sepsis") == ()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"visit_fallback": "Z99.999X"}, "unregistered ICD-10 code Z99.999X"),
        ({"visit_codes": {("pediatric_visit", "no_such_visit"): "Z23"}}, "unknown pediatric visit no_such_visit"),
        (
            {"unknown_by_pattern": {"no_such_pattern": UnknownConditionCodes("R50.9", "R50.9", "R50.9")}},
            "unknown condition pattern no_such_pattern",
        ),
        ({"lab_findings": {"NoSuchLab": LabFindingRule("x", 1.0)}}, "unknown lab NoSuchLab"),
        ({"day1_imaging": {"no_such_disease": ("x",)}}, "unknown disease no_such_disease"),
    ],
)
def test_load_time_validation_rejects_unknown_codes_and_ids(change: dict, message: str) -> None:
    broken = dataclasses.replace(diagnosis_rules._rules(), **change)
    with pytest.raises(ValueError, match=message):
        diagnosis_rules._check(broken)
