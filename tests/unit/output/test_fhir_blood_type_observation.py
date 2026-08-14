"""Unit tests for `labs/blood_type.py` — FHIR blood-type Observation builder.

Design rationale is captured in the module docstring; these tests pin the
resulting resource shape so it stays consistent with the JP hospital
practice: two Observations per patient (ABO group LOINC 883-9 + RhD
LOINC 10331-7), laboratory category, SNOMED CT valueCodeableConcept,
effectiveDateTime anchored to the earliest inpatient admission (or any
earliest encounter as fallback).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.blood_type import _bb_blood_type

pytestmark = pytest.mark.unit


def _ctx(
    patient_data: dict,
    country: str = "JP",
    encounters: list | None = None,
    patient_id: str = "POP-000001",
):
    return SimpleNamespace(
        record={"encounters": encounters or []},
        country=country,
        patient_data=patient_data,
        patient_id=patient_id,
        roster_map={},
        hospital_config={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="enc1",
        patient_sex="",
    )


@pytest.mark.parametrize(
    "abo,expected_snomed",
    [
        ("A", "112144000"),
        ("B", "165743006"),
        ("O", "165744000"),
        ("AB", "165742001"),
    ],
)
def test_abo_observation_shape(abo: str, expected_snomed: str):
    """Every ABO type maps to the canonical SNOMED CT finding concept."""
    ctx = _ctx({"blood_type": abo, "rh_factor": "+"})
    resources = _bb_blood_type(ctx)
    abo_obs = next(r for r in resources if "abo" in r["id"])
    assert abo_obs["resourceType"] == "Observation"
    assert abo_obs["code"]["coding"][0] == {
        "system": "http://loinc.org",
        "code": "883-9",
        "display": "ABO group [Type] in Blood",
    }
    assert abo_obs["valueCodeableConcept"]["coding"][0]["code"] == expected_snomed
    # Category is laboratory (not social-history)
    assert abo_obs["category"][0]["coding"][0]["code"] == "LAB"


@pytest.mark.parametrize(
    "rh,expected_snomed",
    [
        ("+", "165747007"),
        ("-", "165748002"),
        ("positive", "165747007"),
        ("negative", "165748002"),
    ],
)
def test_rh_observation_shape(rh: str, expected_snomed: str):
    """Every Rh factor value maps to the canonical SNOMED CT finding."""
    ctx = _ctx({"blood_type": "A", "rh_factor": rh})
    resources = _bb_blood_type(ctx)
    rh_obs = next(r for r in resources if "rh" in r["id"])
    assert rh_obs["code"]["coding"][0] == {
        "system": "http://loinc.org",
        "code": "10331-7",
        "display": "Rh [Type] in Blood",
    }
    assert rh_obs["valueCodeableConcept"]["coding"][0]["code"] == expected_snomed


def test_two_observations_per_patient():
    """One ABO + one RhD Observation per patient — no more, no less."""
    ctx = _ctx({"blood_type": "AB", "rh_factor": "+"})
    resources = _bb_blood_type(ctx)
    assert len(resources) == 2
    assert {r["id"] for r in resources} == {"blood-abo-POP-000001", "blood-rh-POP-000001"}


def test_effective_datetime_prefers_inpatient_admission():
    """When both inpatient + outpatient encounters exist, effectiveDateTime
    picks the earliest inpatient admission (Type & Screen order convention)."""
    ctx = _ctx(
        {"blood_type": "O", "rh_factor": "+"},
        encounters=[
            {"encounter_type": "outpatient", "admission_datetime": "2025-01-15T10:00:00"},
            {"encounter_type": "inpatient", "admission_datetime": "2025-06-20T18:00:00"},
        ],
    )
    resources = _bb_blood_type(ctx)
    for r in resources:
        assert r["effectiveDateTime"].startswith("2025-06-20T18:00:00")


def test_effective_datetime_falls_back_to_earliest_encounter():
    """No inpatient encounter → use earliest available encounter admission datetime."""
    ctx = _ctx(
        {"blood_type": "O", "rh_factor": "+"},
        encounters=[
            {"encounter_type": "outpatient", "admission_datetime": "2025-05-01T09:00:00"},
            {"encounter_type": "outpatient", "admission_datetime": "2025-02-15T09:00:00"},
        ],
    )
    resources = _bb_blood_type(ctx)
    for r in resources:
        assert r["effectiveDateTime"].startswith("2025-02-15T09:00:00")


def test_effective_datetime_absent_when_no_encounters():
    """No encounters → Observation is emitted without effectiveDateTime (spec-valid)."""
    ctx = _ctx({"blood_type": "O", "rh_factor": "+"}, encounters=[])
    resources = _bb_blood_type(ctx)
    for r in resources:
        assert "effectiveDateTime" not in r


def test_unknown_blood_type_yields_no_abo_observation():
    """Unrecognized ABO value → skip emission (no fabrication). RhD still
    emits when its value is recognized."""
    ctx = _ctx({"blood_type": "unknown", "rh_factor": "+"})
    resources = _bb_blood_type(ctx)
    assert not any("abo" in r["id"] for r in resources)
    assert any("rh" in r["id"] for r in resources)


def test_unknown_rh_yields_no_rh_observation():
    ctx = _ctx({"blood_type": "A", "rh_factor": ""})
    resources = _bb_blood_type(ctx)
    assert any("abo" in r["id"] for r in resources)
    assert not any("rh" in r["id"] for r in resources)


def test_jp_carries_labresult_profile():
    """JP output carries the JP_Observation_LabResult profile in meta."""
    ctx = _ctx({"blood_type": "A", "rh_factor": "+"}, country="JP")
    r = _bb_blood_type(ctx)[0]
    assert "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_LabResult" in r["meta"]["profile"]


def test_us_omits_jp_profile():
    """US output does NOT carry the JP profile."""
    ctx = _ctx({"blood_type": "A", "rh_factor": "+"}, country="US")
    r = _bb_blood_type(ctx)[0]
    assert "meta" not in r or "JP_Observation_LabResult" not in str(r.get("meta", {}))


def test_jp_text_is_japanese():
    ctx = _ctx({"blood_type": "A", "rh_factor": "+"}, country="JP")
    resources = _bb_blood_type(ctx)
    for r in resources:
        assert any(ord(ch) > 127 for ch in r["code"]["text"]), (
            f"JP code.text should carry JA characters, got: {r['code']['text']!r}"
        )


def test_us_text_is_english():
    ctx = _ctx({"blood_type": "A", "rh_factor": "+"}, country="US")
    resources = _bb_blood_type(ctx)
    for r in resources:
        assert all(ord(ch) < 128 for ch in r["code"]["text"]), (
            f"US code.text should be ASCII, got: {r['code']['text']!r}"
        )


def test_performer_from_earliest_encounter_attending():
    ctx = _ctx(
        {"blood_type": "A", "rh_factor": "+"},
        encounters=[
            {"attending_physician_id": "DR-IM-001", "admission_datetime": "2025-01-15T10:00:00"},
        ],
    )
    resources = _bb_blood_type(ctx)
    for r in resources:
        assert r["performer"] == [{"reference": "Practitioner/DR-IM-001"}]
