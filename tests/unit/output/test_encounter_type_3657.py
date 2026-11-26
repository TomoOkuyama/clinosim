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


# Issue #3875: the visit type, not the SNOMED check-up term, names the visit.
def _type_concept(visit_type: str, country: str, dx: str = "I10", chief: str = "Follow-up: x") -> dict:
    resource = _build_encounter(
        {"encounter_id": "E1", "encounter_type": "outpatient", "chief_complaint": chief},
        "P1",
        primary_dx_code=dx,
        country=country,
        visit_type=visit_type,
    )
    return resource["type"][0]


@pytest.mark.parametrize("visit_type", ["chronic_followup", "chemo_visit", "post_discharge"])
def test_follow_up_visits_are_not_titled_periodic_health_check_ja(visit_type: str) -> None:
    concept = _type_concept(visit_type, "JP")
    assert "定期健診" not in concept["text"]
    assert concept["coding"][0]["code"] == CHECK_UP


def test_visit_type_texts_japanese() -> None:
    assert _type_concept("chronic_followup", "JP")["text"] == "慢性疾患フォローアップ外来"
    assert _type_concept("chemo_visit", "JP")["text"] == "化学療法外来"
    assert _type_concept("post_discharge", "JP")["text"] == "退院後外来"


def test_periodic_health_check_keeps_the_name() -> None:
    concept = _type_concept("pediatric_visit", "JP", dx="Z00.121", chief="Well-child visit")
    assert concept["text"] == "定期健診"
    assert concept["coding"][0]["code"] == CHECK_UP


def test_unknown_visit_type_gets_a_neutral_text() -> None:
    for vt in ("", "something_new"):
        assert "定期健診" not in _type_concept(vt, "JP")["text"]


def test_english_text_per_visit_type_and_no_japanese_in_us() -> None:
    concept = _type_concept("chemo_visit", "US")
    assert concept["text"] == "Chemotherapy visit"
    assert concept["coding"][0]["display"] == "Encounter for check up"
    assert concept["coding"][0]["code"] == CHECK_UP


def test_vaccination_and_consultation_keep_their_own_text() -> None:
    assert _type_concept("chronic_followup", "JP", dx="Z23", chief="予防接種")["coding"][0]["code"] == PATIENT_INITIATED
