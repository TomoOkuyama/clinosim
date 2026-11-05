"""Issue #2647: a Braden total carries its six subscale items."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.codes.loinc import loinc_coding
from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

pytestmark = pytest.mark.unit

_ITEMS = {"38222-6": 3, "38229-1": 4, "38223-4": 2, "38224-2": 2, "38225-9": 3, "38226-7": 2}


def test_the_braden_observation_carries_its_items() -> None:
    nra = {
        "date": "2026-05-12",
        "braden_total": 16,
        "braden_sensory": 3,
        "braden_moisture": 4,
        "braden_activity": 2,
        "braden_mobility": 2,
        "braden_nutrition": 3,
        "braden_friction": 2,
        "morse_total": 35,
        "fall_risk_level": "moderate",
    }
    ctx = SimpleNamespace(
        record={"encounters": [], "nursing_risk_assessments": [nra]},
        country="US",
        patient_id="POP-000001",
        primary_enc_id="ENC-001",
    )
    [obs] = [o for o in _bb_nursing_observations(ctx) if o["code"]["coding"][0]["code"] == "38227-5"]
    items = {c["code"]["coding"][0]["code"]: c["valueInteger"] for c in obs["component"]}
    assert items == _ITEMS
    assert sum(items.values()) == obs["valueInteger"]


@pytest.mark.parametrize("code", sorted(_ITEMS))
def test_each_item_is_named(code: str) -> None:
    assert "Braden scale" in loinc_coding(code, "en")["display"]
