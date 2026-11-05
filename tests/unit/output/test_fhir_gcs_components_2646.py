"""Issue #2646: a GCS total carries its eye, verbal and motor components."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.observation.nursing import gcs_components
from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("total", range(3, 16))
def test_components_sum_to_the_total_and_stay_in_range(total: int) -> None:
    eye, verbal, motor = gcs_components(total)
    assert eye + verbal + motor == total
    assert 1 <= eye <= 4 and 1 <= verbal <= 5 and 1 <= motor <= 6


def test_motor_response_is_the_last_to_fall() -> None:
    assert gcs_components(15) == (4, 5, 6)
    assert gcs_components(14)[2] == 6 and gcs_components(13)[2] == 6


def test_the_observation_carries_the_components() -> None:
    ctx = SimpleNamespace(
        record={"encounters": [], "vital_signs": [{"timestamp": "2026-05-12T10:00:00", "gcs_score": 11}]},
        country="US",
        patient_id="POP-000001",
        primary_enc_id="ENC-001",
    )
    [obs] = [o for o in _bb_nursing_observations(ctx) if o["id"].startswith("gcs-")]
    comps = {c["code"]["coding"][0]["code"]: c["valueInteger"] for c in obs["component"]}
    assert set(comps) == {"9267-6", "9270-0", "9268-4"}
    assert sum(comps.values()) == obs["valueInteger"] == 11


def test_each_component_is_named() -> None:
    from clinosim.codes.loinc import loinc_coding

    for code, name in (("9267-6", "eye opening"), ("9270-0", "verbal"), ("9268-4", "motor")):
        assert loinc_coding(code, "en")["display"] == f"Glasgow coma score {name}"
