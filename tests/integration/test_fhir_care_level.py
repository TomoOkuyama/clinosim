import pytest

from clinosim.modules.output._fhir_care_level import _bb_care_level
from clinosim.modules.output.fhir_common import BundleContext

pytestmark = pytest.mark.integration


def _ctx(code, country="JP"):
    return BundleContext(
        record={"care_level": code},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="p1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10",
        primary_enc_id="e1",
        patient_sex="female",
    )


def test_care_level_observation():
    o = _bb_care_level(_ctx("care3"))[0]
    assert o["resourceType"] == "Observation"
    assert o["category"][0]["coding"][0]["code"] == "social-history"
    vc = o["valueCodeableConcept"]["coding"][0]
    assert vc["code"] == "care3"
    assert vc["system"].startswith("http")
    assert o["id"] == "carelevel-p1"


def test_empty_when_no_care_level():
    assert _bb_care_level(_ctx("")) == []
