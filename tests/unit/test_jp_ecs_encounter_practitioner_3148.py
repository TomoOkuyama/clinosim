"""JP Encounter and Practitioner declare the JP-CLINS eCS profiles they
conform to (Issue #3148)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process.profile import _apply_jp_clins_profile

pytestmark = pytest.mark.unit

_ENC_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Encounter_eCS"
_PRAC_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Practitioner_eCS"
_ACT = "http://terminology.hl7.org/CodeSystem/v3-ActCode"


def _encounter(**over: object) -> dict:
    enc = {
        "resourceType": "Encounter",
        "status": "finished",
        "class": {"system": _ACT, "code": "AMB", "display": "ambulatory"},
        "period": {"start": "2024-07-22T10:06:00+09:00", "end": "2024-07-22T10:18:00+09:00"},
    }
    enc.update(over)
    return enc


def _profiles(resource: dict) -> list[str]:
    _apply_jp_clins_profile(resource)
    return (resource.get("meta") or {}).get("profile", [])


def test_a_finished_ambulatory_encounter_declares_ecs() -> None:
    assert _ENC_ECS in _profiles(_encounter())


def test_an_inpatient_encounter_with_an_hl7_discharge_destination_does_not() -> None:
    # JP_Encounter_eCS requires a DPC discharge outcome (JP discharge-disposition
    # value set, required) whenever hospitalization is present.
    hosp = {
        "dischargeDisposition": {
            "coding": [{"system": "http://terminology.hl7.org/CodeSystem/discharge-disposition", "code": "home"}]
        }
    }
    enc = _encounter(
        **{"class": {"system": _ACT, "code": "IMP", "display": "inpatient encounter"}, "hospitalization": hosp}
    )
    assert _ENC_ECS not in _profiles(enc)


@pytest.mark.parametrize(
    "over",
    [
        {"status": "in-progress"},  # eCS fixes status to finished
        {"length": {"value": 12, "unit": "min", "system": "http://unitsofmeasure.org", "code": "min"}},  # fixed "d"
        {"hospitalization": {"reAdmission": {"text": "x"}}},  # dischargeDisposition min=1
        {"reasonCode": [{"coding": [{"system": "s", "code": "c"}]}]},  # text and display min=1
    ],
)
def test_a_non_conforming_encounter_does_not_declare_ecs(over: dict) -> None:
    assert _ENC_ECS not in _profiles(_encounter(**over))


def test_a_length_in_days_conforms() -> None:
    enc = _encounter(length={"value": 2.0, "unit": "d", "system": "http://unitsofmeasure.org", "code": "d"})
    assert _ENC_ECS in _profiles(enc)


def test_practitioner_declares_ecs_with_last_updated() -> None:
    prac = {
        "resourceType": "Practitioner",
        "meta": {"profile": ["http://jpfhir.jp/fhir/core/StructureDefinition/JP_Practitioner"]},
    }
    profiles = _profiles(prac)
    assert _PRAC_ECS in profiles
    assert prac["meta"]["lastUpdated"].endswith("+09:00")
