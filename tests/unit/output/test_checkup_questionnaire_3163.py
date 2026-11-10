"""The health-checkup questionnaire as JP-eCheckup Observations (Issue #3163).

Item and answer codes per 厚生労働省 付属２ XML用特定健診項目情報 Ver.4 and the
JP-eCheckup 1.7.0 CodeSystems; answers derived from the record, no draws."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.documents.composition import (
    _build_encounter_resource_index,
    _derive_section_entries,
)
from clinosim.modules.output.fhir_r4.labs.checkup_questionnaire import (
    checkup_questionnaire_observations,
)

pytestmark = pytest.mark.unit

_ITEM = "urn:oid:1.2.392.200119.6.1005"
_YES_NO = "urn:oid:1.2.392.200119.6.2003"
_SMOKING = "urn:oid:1.2.392.200119.6.24060"
_SMOKING_LATE = "urn:oid:1.2.392.200119.6.19120"
_PROFILE = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Observation_eCheckupGeneral"
_JP_CATEGORY = "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"


def _record(checkup_type: str = "occupational", **patient: object) -> dict:
    pt = {
        "patient_id": "P1",
        "chronic_conditions": [],
        "current_medications": [],
        "smoking_status": "never",
    }
    pt.update(patient)
    return {
        "patient": pt,
        "encounters": [
            {
                "encounter_id": "CHK-P1-001",
                "encounter_type": "checkup",
                "admission_datetime": "2026-08-03T09:00:00",
                "attending_physician_id": "DR-IM-005",
            }
        ],
        "documents": [
            {"task_type": "health_checkup_report", "encounter_id": "CHK-P1-001", "checkup_type": checkup_type}
        ],
    }


def _answers(record: dict) -> dict[str, tuple[str, str]]:
    out = {}
    for obs in checkup_questionnaire_observations(record, "JP"):
        [coding] = obs["code"]["coding"]
        assert coding["system"] == _ITEM
        [value] = obs["valueCodeableConcept"]["coding"]
        out[coding["code"]] = (value["system"], value["code"])
    return out


def test_a_record_without_findings_answers_no_and_never_smoked() -> None:
    assert _answers(_record()) == {
        "9N701000000000011": (_YES_NO, "2"),
        "9N706000000000011": (_YES_NO, "2"),
        "9N711000000000011": (_YES_NO, "2"),
        "9N716000000000011": (_YES_NO, "2"),
        "9N721000000000011": (_YES_NO, "2"),
        "9N726000000000011": (_YES_NO, "2"),
        "9N736000000000011": (_SMOKING, "3"),
    }


@pytest.mark.parametrize(
    ("drug", "item"),
    [
        ("amlodipine", "9N701000000000011"),
        ("hydrochlorothiazide", "9N701000000000011"),
        ("metformin", "9N706000000000011"),
        ("insulin_glargine", "9N706000000000011"),
        ("atorvastatin", "9N711000000000011"),
        ("ezetimibe", "9N711000000000011"),
    ],
)
def test_a_current_medication_answers_its_item_yes(drug: str, item: str) -> None:
    answers = _answers(_record(current_medications=[{"drug_name": drug, "drug_id": drug}]))
    assert answers[item] == (_YES_NO, "1")
    assert [k for k, v in answers.items() if v == (_YES_NO, "1")] == [item]


def test_a_loop_diuretic_is_not_a_blood_pressure_drug() -> None:
    answers = _answers(_record(current_medications=[{"drug_name": "furosemide", "drug_id": "furosemide"}]))
    assert answers["9N701000000000011"] == (_YES_NO, "2")


@pytest.mark.parametrize(("conditions", "expected"), [([], "2"), ([{"code": "E11.9"}], "1")])
def test_an_sglt2_inhibitor_counts_as_a_glucose_drug_only_with_diabetes(conditions: list, expected: str) -> None:
    record = _record(
        current_medications=[{"drug_name": "dapagliflozin", "drug_id": "dapagliflozin"}],
        chronic_conditions=conditions,
    )
    assert _answers(record)["9N706000000000011"] == (_YES_NO, expected)


@pytest.mark.parametrize(
    ("code", "item"),
    [
        ("I63.9", "9N716000000000011"),
        ("I69.3", "9N716000000000011"),
        ("I25.10", "9N721000000000011"),
        ("I48", "9N721000000000011"),
        ("N18.3", "9N726000000000011"),
    ],
)
def test_a_chronic_condition_answers_its_history_item_yes(code: str, item: str) -> None:
    answers = _answers(_record(chronic_conditions=[{"code": code, "onset_date": "2020-01-01"}]))
    assert answers[item] == (_YES_NO, "1")


def test_a_condition_that_began_after_the_checkup_is_not_history() -> None:
    answers = _answers(_record(chronic_conditions=[{"code": "I63.9", "onset_date": "2026-09-01"}]))
    assert answers["9N716000000000011"] == (_YES_NO, "2")


@pytest.mark.parametrize(("status", "code"), [("current", "1"), ("former", "2"), ("never", "3")])
def test_smoking_status_answers_the_smoking_item(status: str, code: str) -> None:
    assert _answers(_record(smoking_status=status))["9N736000000000011"] == (_SMOKING, code)


def test_an_unknown_smoking_status_omits_the_item() -> None:
    assert "9N736000000000011" not in _answers(_record(smoking_status=""))


@pytest.mark.parametrize(("status", "code"), [("current", "1"), ("never", "2"), ("former", "3")])
def test_the_regional_union_report_asks_the_late_stage_elderly_smoking_item(status: str, code: str) -> None:
    assert _answers(_record("regional_union", smoking_status=status)) == {"9N943000000000011": (_SMOKING_LATE, code)}


def test_a_questionnaire_observation_has_the_sample_report_shape() -> None:
    [obs, *_] = checkup_questionnaire_observations(_record(), "JP")
    assert obs["resourceType"] == "Observation"
    assert obs["status"] == "final"
    assert obs["meta"]["profile"] == [_PROFILE]
    # social-history (JP output normalizes the category to JP_SimpleObservationCategory_CS).
    assert [c["code"] for cat in obs["category"] for c in cat["coding"]] == ["social-history"]
    assert obs["code"]["coding"][0]["display"] == "服薬1(血圧)"
    assert obs["valueCodeableConcept"]["coding"][0]["display"] == "いいえ"
    assert obs["subject"]["reference"].startswith("Patient/")
    assert obs["encounter"]["reference"].startswith("Encounter/")
    assert obs["effectiveDateTime"] == "2026-08-03T09:00:00"
    assert obs["performer"] == [{"reference": "Practitioner/DR-IM-005"}]


def test_a_us_record_has_no_questionnaire() -> None:
    assert checkup_questionnaire_observations(_record(), "US") == []


def test_a_record_without_a_checkup_has_no_questionnaire() -> None:
    record = _record()
    record["encounters"][0]["encounter_type"] = "outpatient"
    assert checkup_questionnaire_observations(record, "JP") == []


def test_the_report_sections_split_results_and_questionnaire() -> None:
    questionnaire = checkup_questionnaire_observations(_record(), "JP")
    result = {
        "resourceType": "Observation",
        "id": "lab-1",
        "meta": {"profile": [_PROFILE]},
        "category": [{"coding": [{"system": _JP_CATEGORY, "code": "laboratory"}]}],
        "encounter": questionnaire[0]["encounter"],
    }
    index = _build_encounter_resource_index([{"resource": r} for r in [result, *questionnaire]])
    enc = questionnaire[0]["encounter"]["reference"].split("/")[1]
    results = [e["reference"] for e in _derive_section_entries("checkup_lab_results", enc, index)]
    answers = [e["reference"] for e in _derive_section_entries("checkup_questionnaire", enc, index)]
    assert results == ["Observation/lab-1"]
    assert answers == [f"Observation/{o['id']}" for o in questionnaire]
