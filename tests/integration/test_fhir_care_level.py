import pytest

from clinosim.modules.output.fhir_r4.encounters.care_level import _bb_care_level
from clinosim.modules.output.fhir_r4.lib.common import BundleContext

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
    # Issue #854 Bucket A row 4 (PR-obs-standalone).
    from clinosim.modules.output.fhir_r4.encounters.care_level import _resolve_care_level_id

    assert o["id"] == _resolve_care_level_id("p1")


def test_care_level_observation_code_has_loinc():
    # Issue #733: Observation.code must carry a LOINC coding, not text-only.
    o = _bb_care_level(_ctx("care3"))[0]
    codings = o["code"].get("coding", [])
    assert len(codings) == 1, "expected exactly one LOINC coding"
    c = codings[0]
    assert c["system"] == "http://loinc.org"
    assert c["code"] == "80391-6"
    assert c["display"] == "Level of care [Type]"
    assert o["code"]["text"] == "要介護度"


def test_empty_when_no_care_level():
    assert _bb_care_level(_ctx("")) == []
