"""Encounter.type of vaccination and sick-child visits (Issue #3657)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

pytestmark = pytest.mark.unit

PATIENT_INITIATED, CHECK_UP, CONSULTATION = "270427003", "185349003", "11429006"


def _type_code(enc: dict, country: str = "US", dx: str = "", visit_condition_id: str = "") -> str:
    base = {"encounter_id": "E1", "encounter_type": "outpatient"}
    resource = _build_encounter(
        {**base, **enc}, "P1", primary_dx_code=dx, country=country, visit_condition_id=visit_condition_id
    )
    return resource["type"][0]["coding"][0]["code"]


def test_vaccination_visit_english_and_japanese_is_patient_initiated() -> None:
    assert _type_code({"chief_complaint": "Vaccination visit"}, dx="Z23") == PATIENT_INITIATED
    assert _type_code({"chief_complaint": "Vaccination visit", "chief_complaint_ja": "予防接種"}, "JP", "Z25.1") == (
        PATIENT_INITIATED
    )
    assert _type_code({"chief_complaint_ja": "予防接種"}, "JP") == PATIENT_INITIATED


def test_vaccination_reason_code_alone_is_patient_initiated() -> None:
    assert _type_code({"chief_complaint": "Influenza vaccine"}, dx="Z23") == PATIENT_INITIATED
    assert _type_code({"admission_diagnosis_code": "Z24.6"}, "JP", dx="Z24.6") == PATIENT_INITIATED


@pytest.mark.parametrize(
    "condition", ["pediatric_uri", "pediatric_otitis_media", "pediatric_bronchiolitis", "pediatric_injury"]
)
def test_acute_illness_visit_is_a_consultation(condition: str) -> None:
    assert _type_code({"chief_complaint": "Cough"}, dx="J06.9", visit_condition_id=condition) == CONSULTATION
    assert _type_code({"chief_complaint_ja": "咳"}, "JP", dx="J06.9", visit_condition_id=condition) == CONSULTATION


def test_chronic_follow_up_and_well_child_keep_check_up() -> None:
    assert _type_code({"chief_complaint": "Follow-up: hypertension"}, dx="I10") == CHECK_UP
    assert _type_code({"chief_complaint": "Routine visit"}, dx="I10", visit_condition_id="I10") == CHECK_UP
    assert _type_code({"chief_complaint": "Well-child visit"}, dx="Z00.121", visit_condition_id="well_child_early") == (
        CHECK_UP
    )


def test_screening_keeps_patient_initiated() -> None:
    assert _type_code({"chief_complaint": "Health screening"}, dx="Z00.0") == PATIENT_INITIATED
    assert _type_code({"chief_complaint": "健康診断"}, "JP") == PATIENT_INITIATED
