"""Questionnaire total scores (PHQ-9 / GAD-7 / C-SSRS) are survey Observations, not laboratory."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

pytestmark = pytest.mark.unit


def _build(lab_name: str, value: float, country: str = "US") -> dict:
    order = {"display_name": lab_name, "ordered_datetime": "2026-05-12T10:00:00"}
    result = {"lab_name": lab_name, "value": value, "unit": "", "result_datetime": "2026-05-12T10:30:00"}
    resource = _build_lab_observation(
        order, result, patient_id="POP-000002", index=1, country=country, patient_sex="F", encounter_id="ENC-001"
    )
    assert resource is not None
    return resource


def _category_codes(resource: dict) -> list[str]:
    return [c["code"] for cat in resource["category"] for c in cat["coding"]]


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("lab_name", ["PHQ-9", "GAD-7", "C-SSRS"])
def test_questionnaire_score_is_survey_category(lab_name: str, country: str) -> None:
    assert _category_codes(_build(lab_name, 12.0, country)) == ["survey"]


def test_blood_analyte_stays_laboratory() -> None:
    assert _category_codes(_build("Hb", 13.5)) == ["laboratory"]
