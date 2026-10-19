"""BABY-ID mid-sim-birth patients land in CIF with newborn anthropometry
(``height_cm=50 w=3.2 bmi=12.8 age=0``) hardcoded by
``perinatal._build_newborn_patient``. Nothing advances those stored
scalars as sim time moves forward, so a baby born in sim year 1 and
written to CIF at sim year 5 still carries the newborn snapshot.

:func:`clinosim.modules.output.cif_writer._apply_baby_snapshot_anthropometry`
patches the stored CIF profile at write time with the growth-chart
median at ``snapshot_date`` so direct consumers of the CIF JSON see a
plausible age-matched profile.

Scope: ``patient_id`` ending in ``"-BABY"`` only. Non-BABY patients
(adults, pre-sim pediatric) are untouched — the audit's CRITICAL
finding is BABY-specific and non-BABY pediatric snapshot refresh is
deferred to a separate PR.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from clinosim.modules.output.cif_writer import (
    _apply_baby_snapshot_anthropometry,
    write_cif,
)
from clinosim.types.output import (
    CIFDataset,
    CIFMetadata,
    CIFPatientRecord,
    Encounter,
    PatientProfile,
)


def _baby_record(patient_id: str, dob: date, sex: str = "M") -> CIFPatientRecord:
    """Build a minimal BABY CIFPatientRecord carrying the newborn
    scalars that ``perinatal._build_newborn_patient`` hardcodes."""
    return CIFPatientRecord(
        patient=PatientProfile(
            patient_id=patient_id,
            age=0,
            sex=sex,
            date_of_birth=dob,
            height_cm=50.0,
            weight_kg=3.2,
            bmi=12.8,
        ),
        encounters=[
            Encounter(
                encounter_id=f"ENC-{patient_id}-001",
                encounter_type="inpatient",
                admission_datetime=datetime.combine(dob, datetime.min.time()),
            )
        ],
    )


def _write_and_read(record: CIFPatientRecord, tmp_path, snapshot_date: str, country: str = "US") -> dict:
    ds = CIFDataset(
        metadata=CIFMetadata(
            clinosim_version="test",
            random_seed=42,
            country=country,
            hospital_scale="medium",
            snapshot_date=snapshot_date,
            total_patients_generated=1,
            llm_mode="none",
        ),
        patients=[record],
        hospital_roster=[],
        hospital_config={},
    )
    write_cif(ds, str(tmp_path))
    enc_id = record.encounters[0].encounter_id
    path = tmp_path / "structural" / "patients" / f"{enc_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- helper direct


@pytest.mark.unit
def test_direct_newborn_at_snapshot_zero_keeps_newborn_values():
    """BABY born on snapshot date → age 0 → growth-chart row 0 (newborn
    median: US male h=74 w=9.6). The hardcoded 50/3.2/12.8 at birth is
    REPLACED by the growth-chart age-0 median, not left alone. This
    matches what a consumer would expect from "snapshot at age 0" ≡
    "p50 at age 0 per the CDC chart".

    Note: perinatal.py's birth-time 50/3.2/12.8 are WHO 0-month values
    whereas pediatric_growth.yaml ``US → male → 0`` is the 12-month
    CDC median (74/9.6). The two tables intentionally disagree because
    the yaml's age-0 row is the end-of-first-year value used by the
    FHIR anthropometric emit for pediatric aged < 24 months rounded to
    whole year 1. See the yaml's docstring block for ``pediatric_
    growth_infant`` vs ``pediatric_growth``.
    """
    patient_dict = {
        "patient_id": "POP-000054-BABY",
        "sex": "M",
        "age": 0,
        "date_of_birth": "2026-01-01",
        "height_cm": 50.0,
        "weight_kg": 3.2,
        "bmi": 12.8,
    }
    _apply_baby_snapshot_anthropometry(patient_dict, "2026-01-01", "US")
    assert patient_dict["age"] == 0
    # Growth-chart p50 at age 0: US male h=74, w=9.6, bmi≈17.5
    assert patient_dict["height_cm"] == 74.0
    assert patient_dict["weight_kg"] == 9.6
    assert patient_dict["bmi"] == pytest.approx(17.5, abs=0.1)


@pytest.mark.unit
def test_direct_baby_two_years_later_lands_on_age_two_median():
    """BABY born 2023-08-04, snapshot 2025-12-31 → age 2 (not 0).
    Growth-chart p50 at (US, male, 2): h=91, w=13.3, bmi≈16.1."""
    patient_dict = {
        "patient_id": "POP-000054-BABY",
        "sex": "M",
        "age": 0,
        "date_of_birth": "2023-08-04",
        "height_cm": 50.0,
        "weight_kg": 3.2,
        "bmi": 12.8,
    }
    _apply_baby_snapshot_anthropometry(patient_dict, "2025-12-31", "US")
    assert patient_dict["age"] == 2
    assert patient_dict["height_cm"] == 91.0
    assert patient_dict["weight_kg"] == 13.3
    assert patient_dict["bmi"] == pytest.approx(16.1, abs=0.1)


@pytest.mark.unit
def test_direct_jp_baby_at_three_years():
    """JP locale uses MHLW medians, which differ from CDC. BABY born
    2022-04-01, snapshot 2025-07-01 → age 3. MHLW p50 at (JP, female, 3):
    h=93.4, w=13.5."""
    patient_dict = {
        "patient_id": "POP-000010-BABY",
        "sex": "F",
        "age": 0,
        "date_of_birth": "2022-04-01",
        "height_cm": 49.1,
        "weight_kg": 3.2,
        "bmi": 13.3,
    }
    _apply_baby_snapshot_anthropometry(patient_dict, "2025-07-01", "JP")
    assert patient_dict["age"] == 3
    assert patient_dict["height_cm"] == 93.4
    assert patient_dict["weight_kg"] == 13.5


@pytest.mark.unit
def test_direct_non_baby_patient_untouched():
    """Adult patient (no -BABY suffix) must stay byte-identical — adult
    cohort byte-identity is the PR's scope-limit guarantee."""
    patient_dict = {
        "patient_id": "POP-000001",
        "sex": "M",
        "age": 40,
        "date_of_birth": "1985-06-01",
        "height_cm": 178.0,
        "weight_kg": 82.0,
        "bmi": 25.9,
    }
    snapshot = dict(patient_dict)
    _apply_baby_snapshot_anthropometry(patient_dict, "2025-12-31", "US")
    assert patient_dict == snapshot


@pytest.mark.unit
def test_direct_missing_snapshot_date_no_op():
    """Early-release CIF (snapshot_date=None) is a no-op — nothing to
    reproject against."""
    patient_dict = {
        "patient_id": "POP-000054-BABY",
        "sex": "M",
        "age": 0,
        "date_of_birth": "2023-08-04",
        "height_cm": 50.0,
        "weight_kg": 3.2,
        "bmi": 12.8,
    }
    snapshot = dict(patient_dict)
    _apply_baby_snapshot_anthropometry(patient_dict, None, "US")
    assert patient_dict == snapshot


@pytest.mark.unit
def test_direct_baby_aged_past_pediatric_upper_bound_updates_age_only():
    """Edge: a BABY born year 1 of a 20-year sim is 20 at snapshot —
    past the pediatric upper age (18). The adult sampling path never
    ran for this record so we don't have an adult h/w/bmi to project;
    update ``age`` only and leave anthropometry at the newborn values
    (clear data-quality marker, matches "nothing-to-project" semantics
    the direct-newborn and missing-snapshot cases already follow)."""
    patient_dict = {
        "patient_id": "POP-000054-BABY",
        "sex": "M",
        "age": 0,
        "date_of_birth": "2003-01-01",
        "height_cm": 50.0,
        "weight_kg": 3.2,
        "bmi": 12.8,
    }
    _apply_baby_snapshot_anthropometry(patient_dict, "2025-12-31", "US")
    assert patient_dict["age"] == 22
    assert patient_dict["height_cm"] == 50.0  # unchanged (no pediatric row)
    assert patient_dict["weight_kg"] == 3.2
    assert patient_dict["bmi"] == 12.8


# ------------------------------------------------- end-to-end via write_cif


@pytest.mark.unit
def test_write_cif_baby_profile_updated_on_disk(tmp_path):
    """E2E: a BABY record goes through write_cif → the on-disk JSON
    carries the updated age + anthropometry, not the birth values."""
    rec = _baby_record("POP-000054-BABY", date(2023, 8, 4))
    data = _write_and_read(rec, tmp_path, snapshot_date="2025-12-31", country="US")
    pat = data["patient"]
    assert pat["age"] == 2
    assert pat["height_cm"] == 91.0
    assert pat["weight_kg"] == 13.3


@pytest.mark.unit
def test_write_cif_adult_untouched_on_disk(tmp_path):
    """E2E byte-identity check: an adult record's on-disk profile fields
    are not perturbed by the BABY-snapshot pass."""
    adult = CIFPatientRecord(
        patient=PatientProfile(
            patient_id="POP-000001",
            age=40,
            sex="M",
            date_of_birth=date(1985, 6, 1),
            height_cm=178.3,
            weight_kg=82.1,
            bmi=25.84,
        ),
        encounters=[
            Encounter(
                encounter_id="ENC-POP-000001-001",
                encounter_type="outpatient",
                admission_datetime=datetime(2025, 6, 1, 10, 0),
            )
        ],
    )
    data = _write_and_read(adult, tmp_path, snapshot_date="2025-12-31")
    pat = data["patient"]
    assert pat["age"] == 40
    assert pat["height_cm"] == 178.3
    assert pat["weight_kg"] == 82.1
    assert pat["bmi"] == 25.84
