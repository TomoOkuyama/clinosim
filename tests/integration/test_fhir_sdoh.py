import pytest

from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (
    _bb_alcohol_use,
    _bb_smoking_status,
)
from clinosim.modules.output.fhir_r4.lib.common import BundleContext

pytestmark = pytest.mark.integration


def _ctx(profile, country="US"):
    return BundleContext(
        record={},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data=profile,
        patient_id="p1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id="e1",
        patient_sex="male",
    )


def test_smoking_observation():
    o = _bb_smoking_status(_ctx({"smoking_status": "current"}))[0]
    assert o["resourceType"] == "Observation"
    assert o["code"]["coding"][0]["code"] == "72166-2"
    assert o["category"][0]["coding"][0]["code"] == "social-history"
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "449868002"
    # Issue #854 Bucket A row 4 (PR-obs-standalone): opaque id derived from
    # patient id via the shared resolver.
    from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (
        _resolve_smoking_status_id,
    )

    assert o["id"] == _resolve_smoking_status_id("p1")


def test_smoking_empty_when_missing():
    assert _bb_smoking_status(_ctx({})) == []


def test_alcohol_observation():
    o = _bb_alcohol_use(_ctx({"alcohol_use": "heavy"}))[0]
    assert o["code"]["coding"][0]["code"] == "11331-6"
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "86933000"
    # Issue #854 Bucket A row 4 (PR-obs-standalone).
    from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import (
        _resolve_alcohol_use_id,
    )

    assert o["id"] == _resolve_alcohol_use_id("p1")


def test_alcohol_none_still_emitted():
    o = _bb_alcohol_use(_ctx({"alcohol_use": "none"}))[0]
    assert o["valueCodeableConcept"]["coding"][0]["code"] == "105542008"
