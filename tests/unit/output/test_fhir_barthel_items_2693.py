"""Issue #2693: the Barthel Index Observation carries its ten items."""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.modules.output.fhir_r4.procedures.nursing import barthel_components

pytestmark = pytest.mark.unit

_ADL = {
    "barthel_score": 65,
    "feeding": 10,
    "bathing": 0,
    "grooming": 5,
    "dressing": 5,
    "bowel_control": 10,
    "bladder_control": 5,
    "toilet_use": 5,
    "transfers": 10,
    "mobility": 10,
    "stairs": 5,
}


def test_ten_items_carry_their_answer_and_score() -> None:
    comps = barthel_components(_ADL, "en")
    assert [c["code"]["coding"][0]["code"] for c in comps] == [
        "83184-2",
        "83181-8",
        "96767-9",
        "83182-6",
        "96759-6",
        "96760-4",
        "83183-4",
        "83185-9",
        "83186-7",
        "96758-8",
    ]
    scores = [c["valueCodeableConcept"]["coding"][0]["extension"][0]["valueDecimal"] for c in comps]
    assert sum(scores) == _ADL["barthel_score"]
    feeding = comps[0]["valueCodeableConcept"]["coding"][0]
    assert feeding["code"] == "LA12302-8" and feeding["display"] == "Independent"


def test_an_item_outside_the_scale_drops_the_components() -> None:
    assert barthel_components({**_ADL, "bathing": 10}, "en") == []


@pytest.mark.parametrize("code", ["83184-2", "LA31630-9", "LA12304-4"])
def test_item_and_answer_codes_are_registered(code: str) -> None:
    assert code_lookup("loinc", code, "en") != code
    assert code_lookup("loinc", code, "ja") != code


@pytest.mark.parametrize("seed", range(30))
def test_generated_adl_items_are_on_the_barthel_scale(seed: int) -> None:
    from datetime import datetime

    import numpy as np

    from clinosim.simulator.vitals_pipeline import _generate_adl_assessment
    from clinosim.types.clinical import PhysiologicalState
    from clinosim.types.patient import PatientProfile

    adl = _generate_adl_assessment(
        PhysiologicalState(inflammation_level=0.4, perfusion_status=0.8, renal_function=0.7),
        PatientProfile(patient_id="P1", sex="F", age=82),
        0,
        datetime(2025, 3, 1, 10),
        np.random.default_rng(seed),
    )
    assert adl is not None
    d = adl.__dict__
    assert barthel_components(d, "en"), d
    assert adl.barthel_score % 5 == 0
