import pytest

from clinosim.modules.output.fhir_r4_adapter import BundleContext, _build_code_status

pytestmark = pytest.mark.integration


def _ctx(code="304253006", country="US"):
    return BundleContext(record={"code_status": code,
                                 "encounters": [{"encounter_id": "enc-1",
                                                 "admission_datetime": "2026-05-01T09:00:00"}]},
                         country=country, roster_map={}, hospital_config={}, patient_data={},
                         patient_id="pat-1", is_readmission=False, prior_encounter_id=None,
                         primary_dx_code="", admit_dx_code="", admit_dx_system="icd-10-cm",
                         primary_enc_id="enc-1", patient_sex="male")


def test_builds_observation():
    res = _build_code_status(_ctx())
    assert len(res) == 1
    o = res[0]
    assert o["resourceType"] == "Observation"
    assert o["status"] == "final"
    assert o["category"][0]["coding"][0]["code"] == "survey"
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "304253006"
    assert o["encounter"] == {"reference": "Encounter/enc-1"}


def test_empty_when_no_code_status():
    assert _build_code_status(_ctx(code="")) == []
