"""Susceptibility interpretation (S/I/R) display must resolve via
codes/data/hl7-observation-interpretation.yaml + code_lookup, not the
hardcoded _SUSCEPTIBILITY_DISPLAY dict (2026-07-02 grand design review,
display-dict migration).
"""

import pytest

from clinosim.codes import lookup
from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_microbiology import _bb_microbiology

pytestmark = pytest.mark.unit


def _ctx(country: str, susceptibilities: list[dict]) -> BundleContext:
    record = {
        "microbiology": [
            {
                "specimen": "blood",
                "test_loinc": "600-7",
                "growth": True,
                "organism_snomed": "3092008",
                "susceptibilities": susceptibilities,
            }
        ],
    }
    return BundleContext(
        record=record,
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


def _sus_displays(resources: list[dict]) -> list[str]:
    return [
        r["valueCodeableConcept"]["coding"][0]["display"]
        for r in resources
        if r.get("resourceType") == "Observation"
        and "valueCodeableConcept" in r
        and r["valueCodeableConcept"]["coding"][0].get("code") in ("S", "I", "R")
    ]


@pytest.mark.parametrize(
    "interp,en,ja",
    [
        ("S", "Susceptible", "感性"),
        ("I", "Intermediate", "中間"),
        ("R", "Resistant", "耐性"),
    ],
)
def test_susceptibility_display_us(interp, en, ja):
    resources = _bb_microbiology(_ctx("US", [{"antibiotic_loinc": "19000-9", "interpretation": interp}]))
    assert _sus_displays(resources) == [en]


@pytest.mark.parametrize(
    "interp,en,ja",
    [
        ("S", "Susceptible", "感性"),
        ("I", "Intermediate", "中間"),
        ("R", "Resistant", "耐性"),
    ],
)
def test_susceptibility_display_jp(interp, en, ja):
    """#321 session 61:JP output でも English display を emit する。
    v3-ObservationInterpretation は English-only CS(tx-server の JA
    display 未収録)。walker `_strip_japanese_display_on_english_only_
    systems` により JA display は削除されるので、builder が最初から
    English display を emit する方が pipeline 整合的。v6.1 で 162 件
    error(builder JA emit → walker strip → validator "display=0")。
    """
    resources = _bb_microbiology(_ctx("JP", [{"antibiotic_loinc": "19000-9", "interpretation": interp}]))
    assert _sus_displays(resources) == [en]


def test_yaml_matches_direct_lookup():
    assert lookup("hl7-observation-interpretation", "S", "en") == "Susceptible"
    assert lookup("hl7-observation-interpretation", "S", "ja") == "感性"
