"""Encounter.length in the unit the applied JP-CLINS profile fixes (Issue #3158)."""

from __future__ import annotations

import copy

import pytest

from clinosim.modules.output.fhir_r4.encounters.encounter import _compute_encounter_length
from clinosim.modules.output.fhir_r4.post_process.profile import (
    _apply_jp_clins_profile,
    _apply_length_unit,
    _jp_clins_element_rules,
)

pytestmark = pytest.mark.unit

_ENC_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Encounter_eCS"
_ACT = "http://terminology.hl7.org/CodeSystem/v3-ActCode"


def _encounter(start: str, end: str, code: str = "AMB") -> dict:
    return {
        "resourceType": "Encounter",
        "status": "finished",
        "class": {"system": _ACT, "code": code, "display": "ambulatory"},
        "period": {"start": start, "end": end},
        "length": _compute_encounter_length(start, end),
    }


def test_the_length_unit_rule_is_profile_data() -> None:
    # JP_Encounter_eCS fixes Encounter.length.code to "d" and .unit to "日".
    rules = _jp_clins_element_rules()["Encounter"]
    assert (rules["length_unit"], rules["length_unit_display"]) == ("d", "日")


def test_a_sub_day_visit_omits_length_under_the_days_rule() -> None:
    enc = _encounter("2024-07-22T10:06:00+09:00", "2024-07-22T10:18:00+09:00")
    assert enc["length"]["code"] == "min"
    _apply_length_unit(enc, "d", "日")
    assert "length" not in enc
    assert enc["period"]["end"] == "2024-07-22T10:18:00+09:00"


def test_a_multi_day_stay_states_length_in_days() -> None:
    enc = _encounter("2024-09-10T11:38:00+09:00", "2024-09-18T10:38:00+09:00", "IMP")
    _apply_length_unit(enc, "d", "日")
    assert enc["length"] == {"value": 7.96, "unit": "日", "system": "http://unitsofmeasure.org", "code": "d"}


def test_a_length_in_another_unit_of_a_day_or_more_is_converted() -> None:
    enc = _encounter("2024-07-22T10:00:00+09:00", "2024-07-23T22:00:00+09:00")
    enc["length"] = {"value": 2160, "unit": "min", "system": "http://unitsofmeasure.org", "code": "min"}
    _apply_length_unit(enc, "d", "日")
    assert enc["length"] == {"value": 1.5, "unit": "日", "system": "http://unitsofmeasure.org", "code": "d"}


def test_a_day_or_longer_outpatient_visit_declares_ecs_with_length_in_days() -> None:
    enc = _encounter("2024-07-22T10:00:00+09:00", "2024-07-23T22:00:00+09:00")
    _apply_jp_clins_profile(enc, "JP")
    assert _ENC_ECS in enc["meta"]["profile"]
    assert (enc["length"]["value"], enc["length"]["unit"], enc["length"]["code"]) == (1.5, "日", "d")


def test_a_finished_outpatient_visit_declares_ecs_without_a_minutes_length() -> None:
    enc = _encounter("2024-07-22T10:06:00+09:00", "2024-07-22T10:18:00+09:00")
    _apply_jp_clins_profile(enc, "JP")
    assert _ENC_ECS in enc["meta"]["profile"]
    assert "length" not in enc


def test_an_encounter_that_cannot_declare_ecs_keeps_its_length() -> None:
    # An ED visit with hospitalization stays on JP Core; its minutes length is untouched.
    enc = _encounter("2024-07-22T10:06:00+09:00", "2024-07-22T13:06:00+09:00", "EMER")
    enc["hospitalization"] = {"dischargeDisposition": {"text": "home"}}
    before = copy.deepcopy(enc["length"])
    _apply_jp_clins_profile(enc, "JP")
    assert enc["length"] == before
    assert _ENC_ECS not in (enc.get("meta") or {}).get("profile", [])
