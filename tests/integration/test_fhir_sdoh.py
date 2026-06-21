import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    BundleContext,
    _build_alcohol_use,
    _build_smoking_status,
)

pytestmark = pytest.mark.integration


def _ctx(profile, country="US"):
    return BundleContext(record={}, country=country, roster_map={}, hospital_config={},
                         patient_data=profile, patient_id="p1", is_readmission=False,
                         prior_encounter_id=None, primary_dx_code="", admit_dx_code="",
                         admit_dx_system="icd-10-cm", primary_enc_id="e1", patient_sex="male")


def test_smoking_observation():
    o = _build_smoking_status(_ctx({"smoking_status": "current"}))[0]
    assert o["resourceType"] == "Observation"
    assert o["code"]["coding"][0]["code"] == "72166-2"
    assert o["category"][0]["coding"][0]["code"] == "social-history"
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "449868002"
    assert o["id"] == "smoking-p1"


def test_smoking_empty_when_missing():
    assert _build_smoking_status(_ctx({})) == []


def test_alcohol_observation():
    o = _build_alcohol_use(_ctx({"alcohol_use": "heavy"}))[0]
    assert o["code"]["coding"][0]["code"] == "11331-6"
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "86933000"
    assert o["id"] == "alcohol-p1"


def test_alcohol_none_still_emitted():
    o = _build_alcohol_use(_ctx({"alcohol_use": "none"}))[0]
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "105542008"
