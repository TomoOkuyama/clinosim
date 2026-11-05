"""Issue #2660: a negative culture's organism result is coded, not free text."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology
from clinosim.modules.output.fhir_r4.lib.context import BundleContext

pytestmark = pytest.mark.unit


def _ctx(country: str) -> BundleContext:
    culture = {
        "encounter_id": "E1",
        "specimen": "blood",
        "test_loinc": "600-7",
        "collected_datetime": "2025-11-19T10:47:00",
        "reported_datetime": "2025-11-24T09:00:00",
        "growth": False,
        "organism_snomed": "",
        "susceptibilities": [],
    }
    return BundleContext(
        record={"orders": [], "microbiology": [culture]},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="E1",
        patient_sex="M",
    )


@pytest.mark.parametrize(("country", "text"), [("US", "No growth"), ("JP", "発育なし")])
def test_a_negative_culture_is_coded_no_growth(country: str, text: str) -> None:
    org = next(r for r in _bb_microbiology(_ctx(country)) if r["resourceType"] == "Observation")
    assert "valueString" not in org
    [coding] = org["valueCodeableConcept"]["coding"]
    assert (coding["system"], coding["code"], coding["display"]) == ("http://snomed.info/sct", "264868006", "No growth")
    assert org["valueCodeableConcept"]["text"] == text
