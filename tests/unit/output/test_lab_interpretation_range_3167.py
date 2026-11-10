"""A JP-CLINS lab result's H / L / N interpretation has the one reference
range and the quantity value it was judged on (Issue #3167).

JP-CLINS ``JP_Observation_LabResult_eCS`` (R06042H / L / N,
``check-interpretationH`` / ``L`` / ``N``): an ``H`` / ``L`` / ``N``
interpretation needs exactly one ``referenceRange`` and a quantity value.
PT-INR on warfarin is judged against the therapeutic range, so the eCS
result keeps that range alone. A qualitative result that nothing judged
(urinalysis, no flag and no range) states no interpretation rather than an
unsupported ``N``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.builder import _finalize_resource
from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

pytestmark = pytest.mark.unit

_V3 = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
_ECS = "http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS"
_WARFARIN = [SimpleNamespace(drug_name="Warfarin")]


def _obs(lab_name: str, value: object, unit: str, country: str, flag: str | None = None, meds: object = None) -> dict:
    order = {
        "display_name": lab_name,
        "order_code": lab_name,
        "encounter_id": "E1",
        "ordered_datetime": "2026-04-01T09:30:00",
    }
    result = {
        "lab_name": lab_name,
        "value": value,
        "unit": unit,
        "flag": flag,
        "result_datetime": "2026-04-01T10:00:00",
    }
    obs = _build_lab_observation(
        order, result, "P1", 0, country, patient_sex="M", encounter_id="E1", patient_medications=meds, patient_age=60
    )
    assert obs is not None
    _finalize_resource(obs, country, {})
    return obs


def _codes(obs: dict) -> list[str]:
    return [c["code"] for i in obs.get("interpretation", []) for c in i["coding"] if c["system"] == _V3]


def _meets_ecs_interpretation_rules(obs: dict) -> bool:
    ranges = obs.get("referenceRange", [])
    value = (obs.get("valueQuantity") or {}).get("value")
    for code in set(_codes(obs)) & {"H", "L", "N"}:
        if len(ranges) != 1 or value is None:
            return False
        low, high = (ranges[0].get(k, {}).get("value") for k in ("low", "high"))
        if code == "H" and not (high is not None and value >= high):
            return False
        if code == "L" and not (low is not None and value <= low):
            return False
        if code == "N" and not ((low is None or value >= low) and (high is None or value <= high)):
            return False
    return True


@pytest.mark.parametrize(("value", "expected"), [(2.4, "N"), (3.6, "H"), (1.4, "L")])
def test_jp_inr_on_warfarin_keeps_the_therapeutic_range_it_was_judged_on(value: float, expected: str) -> None:
    obs = _obs("PT_INR", value, "", "JP", meds=_WARFARIN)
    assert _ECS in obs["meta"]["profile"]
    assert _codes(obs) == [expected]
    assert [r["type"]["coding"][0]["code"] for r in obs["referenceRange"]] == ["therapeutic"]
    assert _meets_ecs_interpretation_rules(obs)


def test_jp_inr_without_warfarin_keeps_its_normal_range() -> None:
    obs = _obs("PT_INR", 1.0, "", "JP")
    assert len(obs["referenceRange"]) == 1
    assert "type" not in obs["referenceRange"][0]
    assert _meets_ecs_interpretation_rules(obs)


def test_us_inr_on_warfarin_keeps_both_ranges() -> None:
    obs = _obs("PT_INR", 2.4, "", "US", meds=_WARFARIN)
    assert len(obs["referenceRange"]) == 2


@pytest.mark.parametrize("country", ["JP", "US"])
@pytest.mark.parametrize("value", ["normal", "2+ leukocytes, trace blood"])
def test_an_unflagged_qualitative_result_states_no_interpretation(country: str, value: str) -> None:
    # Nothing judged the reading (no flag, no range): no "N" is asserted.
    obs = _obs("Urinalysis", value, "", country)
    assert "valueQuantity" not in obs
    assert "interpretation" not in obs
    assert _meets_ecs_interpretation_rules(obs)


def test_a_flagged_qualitative_result_keeps_its_flag_outside_jp_clins() -> None:
    obs = _obs("Urinalysis", "2+ leukocytes", "", "US", flag="H")
    assert _codes(obs) == ["H"]
