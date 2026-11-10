"""A finished JP inpatient Encounter that carries the DPC discharge outcome
declares JP_Encounter_eCS (Issue #3174)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.post_process.profile import (
    _apply_jp_clins_profile,
    _encounter_satisfies_ecs,
    _jp_clins_element_rules,
)

pytestmark = pytest.mark.unit

_ENC_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Encounter_eCS"
_ACT = "http://terminology.hl7.org/CodeSystem/v3-ActCode"
_DPC = "http://jpfhir.jp/fhir/Common/CodeSystem/discharge-disposition"
_HL7 = "http://terminology.hl7.org/CodeSystem/discharge-disposition"


def _coding(system: str, code: str, display: str = "傷病が治癒・軽快") -> dict:
    return {"coding": [{"system": system, "code": code, "display": display}], "text": display}


def _inpatient(status: str = "finished", disposition: dict | None = None, **over: object) -> dict:
    enc = {
        "resourceType": "Encounter",
        "status": status,
        "class": {"system": _ACT, "code": "IMP", "display": "inpatient encounter"},
        "period": {"start": "2024-09-10T11:38:00+09:00", "end": "2024-09-18T10:38:00+09:00"},
        "length": {"value": 11460, "unit": "min", "system": "http://unitsofmeasure.org", "code": "min"},
        "hospitalization": {"dischargeDisposition": disposition or _coding(_DPC, "1")},
    }
    enc.update(over)
    return enc


def _profiles(resource: dict) -> list[str]:
    _apply_jp_clins_profile(resource)
    return (resource.get("meta") or {}).get("profile", [])


def test_the_dpc_outcome_system_is_profile_data() -> None:
    # JP_Encounter_eCS binds dischargeDisposition (required) to the jpfhir
    # discharge-disposition value set.
    assert _jp_clins_element_rules()["Encounter"]["discharge_disposition_system"] == "jpfhir-discharge-disposition"


def test_a_finished_inpatient_stay_with_a_dpc_outcome_declares_ecs() -> None:
    enc = _inpatient()
    assert _ENC_ECS in _profiles(enc)
    # Length stated in days per the profile's fixed unit (Issue #3158).
    assert (enc["length"]["code"], enc["length"]["unit"]) == ("d", "日")


@pytest.mark.parametrize("code", ["1", "3", "4", "5", "6", "7", "9"])
def test_every_dpc_outcome_conforms(code: str) -> None:
    assert _ENC_ECS in _profiles(_inpatient(disposition=_coding(_DPC, code)))


def test_an_in_progress_stay_does_not_declare_ecs() -> None:
    enc = _inpatient(status="in-progress")
    enc.pop("length")
    assert _ENC_ECS not in _profiles(enc)


@pytest.mark.parametrize(
    "disposition",
    [
        _coding(_HL7, "home", "Home"),  # HL7 destination, not the DPC value set
        _coding(_DPC, "2"),  # not a code of the DPC value set
        {"text": "傷病が治癒・軽快"},  # dischargeDisposition.coding min=1
        {
            "coding": [
                {"system": _DPC, "code": "1"},
                {"system": _HL7, "code": "home"},
            ]
        },  # dischargeDisposition.coding max=1
    ],
)
def test_a_disposition_outside_the_dpc_value_set_does_not_declare_ecs(disposition: dict) -> None:
    enc = _inpatient(disposition=disposition)
    assert not _encounter_satisfies_ecs(enc)
    assert _ENC_ECS not in _profiles(enc)
    # The Encounter stays as it was (its minutes length is not converted).
    assert enc["length"]["code"] == "min"


def test_an_admit_source_without_a_coding_does_not_declare_ecs() -> None:
    # admitSource.coding min=1 (with system and code) when admitSource is present.
    enc = _inpatient()
    enc["hospitalization"]["admitSource"] = {"text": "外来から"}
    assert not _encounter_satisfies_ecs(enc)


def test_the_admit_source_fallback_carries_the_tho_display() -> None:
    # An eCS inpatient stay with no recorded admit source is coded HL7
    # admit-source "other"; HL7 Terminology (THO) CodeSystem admit-source 1.0.1
    # displays it "Other", and the validator rejects any other display.
    from clinosim.codes import display

    assert display("hl7-admit-source", "other", "en") == "Other"
