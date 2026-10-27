"""Pain scores reach FHIR as LOINC 72514-3 Observations (#2089)."""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import _build_vital_observations

pytestmark = pytest.mark.unit

_VS = {"timestamp": datetime(2026, 5, 1, 9, 0), "heart_rate": 88, "pain_score": 7, "measured_by": "NS-001"}


def _pain(entries: list[dict]) -> list[dict]:
    return [
        e["resource"]
        for e in entries
        if any(c.get("code") == "72514-3" for c in e["resource"].get("code", {}).get("coding", []))
    ]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_pain_score_emits_observation(country: str) -> None:
    entries = _build_vital_observations(dict(_VS), "P1", 3, country=country, encounter_id="E1")
    obs = _pain(entries)
    hr = next(e["resource"] for e in entries if e["resource"]["code"]["coding"][0]["code"] == "8867-4")
    assert len(obs) == 1
    o = obs[0]
    assert o["valueInteger"] == 7
    assert o["code"]["coding"][0]["display"] == "Pain severity - 0-10 verbal numeric rating [Score] - Reported"
    assert o["category"][0]["coding"][0]["code"] == "vital-signs"
    assert o["encounter"] == hr["encounter"]
    assert o["performer"][0]["reference"] == "Practitioner/NS-001"
    assert o["effectiveDateTime"].startswith("2026-05-01T09:00")


def test_pain_score_zero_is_emitted_and_missing_is_not() -> None:
    zero = _pain(_build_vital_observations({**_VS, "pain_score": 0}, "P1", 1, encounter_id="E1"))
    assert zero and zero[0]["valueInteger"] == 0
    assert not _pain(_build_vital_observations({**_VS, "pain_score": None}, "P1", 1, encounter_id="E1"))


def test_pain_observation_ids_are_unique_per_record() -> None:
    a = _pain(_build_vital_observations(dict(_VS), "P1", 1, encounter_id="E1"))[0]["id"]
    b = _pain(_build_vital_observations(dict(_VS), "P1", 2, encounter_id="E1"))[0]["id"]
    assert a != b
