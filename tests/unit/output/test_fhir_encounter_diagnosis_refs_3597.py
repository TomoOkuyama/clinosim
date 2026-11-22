"""Issue #3597: every encounter-diagnosis Condition is referenced from its Encounter."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_conditions, _bb_encounters


def _ctx(country: str, *, dx: dict, chronic: list[dict] | None = None) -> BundleContext:
    enc = {
        "encounter_id": "ENC-1",
        "encounter_type": "inpatient",
        "status": "completed",
        "admission_datetime": "2026-05-12T08:00:00",
        "discharge_datetime": "2026-05-19T14:00:00",
        "attending_physician_id": "STAFF-001",
        "severity": "moderate",
    }
    patient = {"patient_id": "POP-1", "sex": "M", "chronic_conditions": chronic or []}
    record = {"patient": patient, "encounters": [enc], "clinical_diagnosis": dx, "deceased": False}
    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data=patient,
        patient_id="POP-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code=dx["discharge_diagnosis_code"],
        admit_dx_code=dx["admission_diagnosis_code"],
        admit_dx_system="icd-10-cm",
        primary_enc_id="ENC-1",
        patient_sex="M",
    )


def _encounter_dx_conditions(ctx: BundleContext) -> list[dict]:
    return [
        c
        for c in _bb_conditions(ctx)
        if any(x["code"] == "encounter-diagnosis" for cat in c["category"] for x in cat["coding"])
    ]


def _code(cond: dict) -> str:
    return cond["code"]["coding"][0]["code"]


SEPSIS_DX = {
    "admission_diagnosis_code": "A41.9",
    "discharge_diagnosis_code": "A41.9",
    "secondary_diagnosis_codes": ["R65.20", "J18.9", "F05"],
    "working_diagnoses": [{"disease_id": "N17.9", "source": "in_hospital_complication"}],
}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_encounter_diagnosis_condition_is_referenced(country: str) -> None:
    ctx = _ctx(country, dx=SEPSIS_DX, chronic=[{"code": "I10"}, {"code": "E11.9"}])
    (enc,) = [r for r in _bb_encounters(ctx) if r["resourceType"] == "Encounter"]
    refs = [d["condition"]["reference"].split("/")[-1] for d in enc["diagnosis"]]
    conds = _encounter_dx_conditions(ctx)
    assert {c["id"] for c in conds} <= set(refs)
    assert len(refs) == len(set(refs))
    assert len(conds) == len({_code(c) for c in conds}), "one Condition per code per encounter"
    ranks = [d["rank"] for d in enc["diagnosis"]]
    assert ranks == list(range(1, len(ranks) + 1))
    assert enc["diagnosis"][0]["use"]["coding"][0]["code"] == "DD"
    by_ref = {d["condition"]["reference"].split("/")[-1]: d for d in enc["diagnosis"]}
    secondary = [
        c for c in conds if _code(c) in {"R65.20", "R65.1", "J18.9", "F05", "N17.9"}
    ]  # R65.20 maps to R65.1 in JP
    assert len(secondary) == 4
    for c in secondary:
        d = by_ref[c["id"]]
        assert d["use"]["coding"][0]["code"] == "CM"
        assert d["rank"] > 1


def test_secondary_equal_to_the_principal_code_is_not_a_second_condition() -> None:
    dx = {**SEPSIS_DX, "working_diagnoses": [{"disease_id": "A41.9", "source": "in_hospital_complication"}]}
    ctx = _ctx("US", dx=dx)
    codes = [_code(c) for c in _encounter_dx_conditions(ctx)]
    assert codes.count("A41.9") == 1


def test_secondary_equal_to_the_admission_code_is_not_a_second_condition() -> None:
    dx = {
        "admission_diagnosis_code": "J18.9",
        "discharge_diagnosis_code": "A41.9",
        "secondary_diagnosis_codes": ["J18.9"],
        "working_diagnoses": [],
    }
    ctx = _ctx("US", dx=dx)
    codes = [_code(c) for c in _encounter_dx_conditions(ctx)]
    assert codes.count("J18.9") == 1
    (enc,) = [r for r in _bb_encounters(ctx) if r["resourceType"] == "Encounter"]
    refs = {d["condition"]["reference"].split("/")[-1] for d in enc["diagnosis"]}
    assert {c["id"] for c in _encounter_dx_conditions(ctx)} <= refs


def test_never_principal_discharge_keeps_the_admission_dx_first() -> None:
    dx = {
        "admission_diagnosis_code": "A41.9",
        "discharge_diagnosis_code": "R65.21",
        "secondary_diagnosis_codes": ["N17.9"],
        "working_diagnoses": [],
    }
    ctx = _ctx("US", dx=dx)
    (enc,) = [r for r in _bb_encounters(ctx) if r["resourceType"] == "Encounter"]
    roles = [d["use"]["coding"][0]["code"] for d in enc["diagnosis"]]
    assert roles[0] == "AD"
    assert [d["rank"] for d in enc["diagnosis"]] == list(range(1, len(roles) + 1))
    refs = {d["condition"]["reference"].split("/")[-1] for d in enc["diagnosis"]}
    assert {c["id"] for c in _encounter_dx_conditions(ctx)} <= refs


def test_medication_request_has_no_reason_reference_for_a_visit_reason_primary() -> None:
    """A Z-chapter visit-reason primary (screening colonoscopy) has no Condition,
    so a sedation MedicationRequest must not reference one."""
    from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_request
    from tests.unit.output.test_fhir_medication_opaque_id import _abx_order

    with_z = _build_medication_request(_abx_order(), "pt1", "US", "ENC-1", primary_dx_code="Z12.11")
    assert "reasonReference" not in with_z
    with_dx = _build_medication_request(_abx_order(), "pt1", "US", "ENC-1", primary_dx_code="A41.9")
    assert with_dx["reasonReference"]
