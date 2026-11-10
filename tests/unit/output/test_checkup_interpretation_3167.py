"""A health-checkup result's interpretation agrees with its reference range
(JP-CLINS ``check-interpretationH`` / ``N``; Issue #3167).

JP-CLINS ``JP_Observation_LabResult_eCS`` requires an ``H`` result to carry
exactly one reference range whose ``high`` the value reaches, and an ``N``
result to lie within the range's bounds. The checkup criterion
(保健指導判定値, ``reference_range_lab.yaml`` ``checkup_ranges``) is the
range: its ``high`` is "H at or above this value".
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import checkup_criterion
from clinosim.modules.output.fhir_r4.labs.observations import _build_lab_observation

pytestmark = pytest.mark.unit

_V3 = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"


def _checkup_obs(lab_name: str, value: float, unit: str, flag: str | None) -> dict:
    criterion = checkup_criterion(lab_name, "JP")
    assert criterion is not None
    order = {
        "order_id": "o1",
        "display_name": lab_name,
        "ordered_datetime": "2026-08-03T09:30:00",
        "clinical_intent": "health_checkup",
    }
    result = {
        "lab_name": lab_name,
        "value": value,
        "unit": unit,
        "flag": flag,
        "reference_range": criterion["text"],
        "result_datetime": "2026-08-03T10:00:00",
    }
    obs = _build_lab_observation(order, result, "P1", 0, "JP", encounter_id="E1")
    assert obs is not None
    return obs


def _interp(obs: dict) -> str:
    return next(c["code"] for i in obs["interpretation"] for c in i["coding"] if c["system"] == _V3)


def _satisfies_jp_clins(obs: dict) -> bool:
    """check-interpretationH / L / N of JP_Observation_LabResult_eCS."""
    code = _interp(obs)
    ranges = obs.get("referenceRange", [])
    value = obs.get("valueQuantity", {}).get("value")
    if len(ranges) != 1 or value is None:
        return False
    low = ranges[0].get("low", {}).get("value")
    high = ranges[0].get("high", {}).get("value")
    if code == "H":
        return high is not None and value >= high
    if code == "L":
        return low is not None and value <= low
    return (low is None or value >= low) and (high is None or value <= high)


@pytest.mark.parametrize(
    ("lab_name", "value", "unit", "flag"),
    [
        ("SBP", 142.0, "mm[Hg]", "H"),
        ("SBP", 130.0, "mm[Hg]", "H"),  # at the criterion: H (保健指導判定値以上)
        ("SBP", 118.0, "mm[Hg]", None),
        ("DBP", 88.0, "mm[Hg]", "H"),
        ("BMI", 27.3, "kg/m2", "H"),
        ("BMI", 17.9, "kg/m2", None),
        ("HbA1c", 6.1, "%", "H"),
        ("LDL", 120.0, "mg/dL", "H"),
        ("LDL", 98.0, "mg/dL", None),
    ],
)
def test_a_checkup_result_meets_the_interpretation_invariants(
    lab_name: str, value: float, unit: str, flag: str | None
) -> None:
    obs = _checkup_obs(lab_name, value, unit, flag)
    assert _satisfies_jp_clins(obs), obs["referenceRange"]


@pytest.mark.parametrize(("lab_name", "value", "unit"), [("SBP", 130.0, "mm[Hg]"), ("LDL", 120.0, "mg/dL")])
def test_the_stored_checkup_flag_is_kept_at_the_criterion(lab_name: str, value: float, unit: str) -> None:
    # The criterion is "H at or above"; FHIR keeps the CIF flag, it does not
    # re-judge the value as "above high" (which would say N at the boundary).
    assert _interp(_checkup_obs(lab_name, value, unit, "H")) == "H"


def test_the_checkup_range_states_the_criterion_from_yaml() -> None:
    criterion = checkup_criterion("SBP", "JP")
    assert criterion is not None
    (rng,) = _checkup_obs("SBP", 142.0, "mm[Hg]", "H")["referenceRange"]
    assert rng["text"] == criterion["text"]
    assert rng["high"]["value"] == criterion["high"]
    assert rng["high"]["code"] == criterion["unit"]


def test_a_country_without_checkup_criteria_has_none() -> None:
    assert checkup_criterion("SBP", "US") is None
    assert checkup_criterion("CRP", "JP") is None


@pytest.mark.parametrize("country", ["JP", "US"])
def test_a_lab_bmi_does_not_declare_the_vital_signs_profile(country: str) -> None:
    # The lab Observation's one ``laboratory`` category cannot meet the HL7
    # ``bmi`` profile's ``vital-signs`` category slice.
    order = {"order_id": "o1", "display_name": "BMI", "ordered_datetime": "2026-08-03T09:30:00"}
    result = {"lab_name": "BMI", "value": 23.6, "unit": "kg/m2", "result_datetime": "2026-08-03T10:00:00"}
    obs = _build_lab_observation(order, result, "P1", 0, country, encounter_id="E1")
    assert obs is not None
    assert "http://hl7.org/fhir/StructureDefinition/bmi" not in obs.get("meta", {}).get("profile", [])
