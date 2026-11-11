"""The resources a JP health-checkup report references conform to
JP-eCheckup 1.7.0 (Issue #3155): the checkup Encounter
(JP_Encounter_eCheckupGeneral), the two authors and the custodian
(JP_Practitioner_eCheckupGeneral / JP_Organization_eCheckupGeneral)."""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.documents.composition import _build_composition
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.output.fhir_r4.encounters.facility import _build_facility_bundle
from clinosim.modules.output.fhir_r4.post_process.profile import (
    _apply_jp_clins_profile,
    _encounter_satisfies_ecs,
)

pytestmark = pytest.mark.unit

_ENC_ECHECKUP = "http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Encounter_eCheckupGeneral"
_ENC_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Encounter_eCS"
_ENC_CATEGORY = "http://jpfhir.jp/fhir/eCheckup/CodeSystem/encounter-category"
_ACT = "http://terminology.hl7.org/CodeSystem/v3-ActCode"


def _checkup_enc() -> dict:
    return {
        "encounter_id": "CHK-P1-001",
        "encounter_type": "checkup",
        "status": "completed",
        "department_id": "health_checkup",
        "admission_datetime": "2026-08-03T09:00:00",
        "discharge_datetime": "2026-08-03T11:00:00",
        "priority": "R",
        "admit_source": "outp",
        "discharge_disposition": "home",
    }


def test_a_jp_checkup_encounter_is_an_echeckup_encounter() -> None:
    res = _build_encounter(_checkup_enc(), "P1", country="JP")
    # class is fixed (patternCoding) to encounter-category#checkup "健診".
    assert res["class"] == {"system": _ENC_CATEGORY, "code": "checkup", "display": "健診"}
    assert _ENC_ECHECKUP in res["meta"]["profile"]
    assert res["meta"]["lastUpdated"] == res["period"]["end"]
    # serviceProvider is the eCheckup institution (a department Organization
    # has partOf, which JP_Organization_eCheckupGeneral forbids).
    assert res["serviceProvider"] == {"reference": "Organization/hospital-main"}


def test_a_us_checkup_encounter_is_unchanged() -> None:
    res = _build_encounter(_checkup_enc(), "P1", country="US")
    assert (res["class"]["system"], res["class"]["code"]) == (_ACT, "AMB")
    assert "meta" not in res
    assert res["serviceProvider"] == {"reference": "Organization/dept-health-checkup"}


def test_a_jp_outpatient_encounter_keeps_its_v3_class() -> None:
    enc = {**_checkup_enc(), "encounter_type": "outpatient", "department_id": "internal_medicine"}
    res = _build_encounter(enc, "P1", country="JP")
    assert (res["class"]["system"], res["class"]["code"]) == (_ACT, "AMB")
    assert _ENC_ECHECKUP not in res["meta"]["profile"]


def test_a_checkup_encounter_does_not_declare_ecs() -> None:
    # JP_Encounter_eCS fixes class.system to v3-ActCode.
    res = _build_encounter(_checkup_enc(), "P1", country="JP")
    assert not _encounter_satisfies_ecs(res)
    _apply_jp_clins_profile(res, "JP")
    assert _ENC_ECS not in res["meta"]["profile"]


def test_the_hospital_address_has_a_postal_code() -> None:
    config = {"available_departments": [], "wards": {}, "resource_capacity": {"inpatient_beds": 1}}
    entries = _build_facility_bundle(config, "JP")["entry"]
    [hosp] = [e["resource"] for e in entries if e["resource"]["id"] == "hospital-main"]
    [address] = hosp["address"]
    assert re.fullmatch(r"\d{3}-\d{4}", address["postalCode"])
    assert address["text"]


def test_the_checkup_report_has_a_practitioner_and_an_organization_author() -> None:
    doc = {
        "document_id": "doc-CHK-P1-001",
        "loinc_code": "53576-5",
        "patient_id": "P1",
        "encounter_id": "CHK-P1-001",
        "author_practitioner_id": "DR-IM-002",
        "authored_datetime": "2026-08-03T11:00:00",
        "language": "ja",
        "format_type": "composition",
        "narrative": {"sections": {"body": "本文"}},
    }
    comp = _build_composition(doc, {"body": "本文"}, "ja", country="JP")
    assert [a["reference"] for a in comp["author"]] == ["Practitioner/DR-IM-002", "Organization/hospital-main"]
    assert comp["custodian"] == {"reference": "Organization/hospital-main"}
    # event.detail references the checkup Encounter, as the IG sample Bundle does.
    [event] = comp["event"]
    assert [d["reference"] for d in event["detail"]] == [comp["encounter"]["reference"]]


@pytest.mark.parametrize("checkup_result", [True, False])
def test_a_checkup_result_does_not_declare_the_ecs_lab_profile(checkup_result: bool) -> None:
    # JP_Observation_LabResult_eCS targets Observation.encounter at
    # JP_Encounter_eCS; a checkup result references the eCheckup encounter.
    lab_ecs = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS"
    profiles = ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult"]
    if checkup_result:
        profiles.append("http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Observation_eCheckupGeneral")
    obs = {
        "resourceType": "Observation",
        "id": "lab-1",
        "meta": {"profile": list(profiles)},
        "category": [{"coding": [{"code": "laboratory"}]}],
    }
    _apply_jp_clins_profile(obs, "JP")
    assert (lab_ecs in obs["meta"]["profile"]) is not checkup_result
