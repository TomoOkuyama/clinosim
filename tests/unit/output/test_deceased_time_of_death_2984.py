"""Issue #2984: ``Patient.deceasedDateTime`` carries the time of an in-hospital death.

An in-hospital death has a documented time: the expired encounter's
discharge. ``PersonRecord.record_death`` keeps it as ``death_datetime``,
``sync_profile_death_dates`` copies it to every profile, and the Patient
emitter writes it instead of the end-of-day fallback. A death known only by
date (a community death) keeps the end-of-day fallback.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.output.fhir_r4.demographics.patient import _build_patient
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.modules.population.vital_status import record_hospital_death, sync_profile_death_dates
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DEATH = datetime(2021, 11, 17, 0, 35)


def _person(pid: str = "P1") -> PersonRecord:
    return PersonRecord(person_id=pid, household_id="H1", age=80, sex="M", date_of_birth=date(1941, 2, 1))


def _expired_record(pid: str = "P1") -> CIFPatientRecord:
    enc = Encounter(
        encounter_id=f"ENC-{pid}",
        patient_id=pid,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2021, 11, 10, 14, 0),
        discharge_datetime=_DEATH,
        discharge_disposition=DischargeDisposition.EXP,
    )
    return CIFPatientRecord(patient=PatientProfile(patient_id=pid), encounters=[enc], deceased=True)


def test_record_hospital_death_keeps_the_time_of_death() -> None:
    p = _person()
    record_hospital_death(p, _expired_record())
    assert p.date_of_death == date(2021, 11, 17)
    assert p.death_datetime == _DEATH


def test_community_death_has_no_time_of_death() -> None:
    p = _person()
    p.record_death(date(2025, 6, 1), "community")
    assert p.death_datetime is None


def test_earlier_hospital_death_replaces_a_community_death_with_its_time() -> None:
    p = _person()
    p.record_death(date(2022, 3, 1), "community")
    record_hospital_death(p, _expired_record())
    assert (p.date_of_death, p.death_place, p.death_datetime) == (date(2021, 11, 17), "hospital", _DEATH)


def test_earlier_community_death_clears_a_later_hospital_time() -> None:
    p = _person()
    record_hospital_death(p, _expired_record())
    p.record_death(date(2021, 11, 1), "community")
    assert (p.date_of_death, p.death_datetime) == (date(2021, 11, 1), None)


def test_sync_copies_the_time_of_death_to_every_profile() -> None:
    reg = PopulationRegistry()
    p = _person()
    reg.persons[p.person_id] = p
    rec = _expired_record()
    record_hospital_death(p, rec)
    early = CIFPatientRecord(patient=PatientProfile(patient_id="P1"))
    sync_profile_death_dates([early, rec], reg, as_of=date(2026, 11, 1))
    for r in (early, rec):
        assert r.patient.date_of_death == date(2021, 11, 17)
        assert r.patient.death_datetime == _DEATH


@pytest.mark.parametrize(("country", "expected"), [("US", "2021-11-17T00:35:00Z"), ("JP", "2021-11-17T00:35:00+09:00")])
def test_deceased_datetime_is_the_in_hospital_time_of_death(patient_dict_factory, country: str, expected: str) -> None:
    p = patient_dict_factory(date_of_death="2021-11-17", death_datetime="2021-11-17T00:35:00")
    assert _build_patient(p, country)["deceasedDateTime"] == expected


def test_death_known_by_date_alone_keeps_the_end_of_day_fallback(patient_dict_factory) -> None:
    p = patient_dict_factory(date_of_death="2025-06-15", death_datetime=None)
    assert _build_patient(p, "US")["deceasedDateTime"] == "2025-06-15T23:59:59Z"


def _bundle_record(**patient: object) -> dict:
    return {
        "patient": {"patient_id": "P1", "sex": "M", "date_of_birth": "1941-02-01", **patient},
        "deceased": True,
        "encounters": [
            {
                "encounter_id": "ENC-P1",
                "patient_id": "P1",
                "encounter_type": "inpatient",
                "admission_datetime": "2021-11-10T14:00:00",
                "discharge_datetime": "2021-11-17T00:35:00",
                "discharge_disposition": "exp",
            }
        ],
    }


def _resources(bundle: dict, rtype: str) -> list[dict]:
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == rtype]


@pytest.mark.parametrize(
    "patient",
    [
        {"date_of_death": "2021-11-17", "death_datetime": "2021-11-17T00:35:00"},
        {},  # legacy CIF: deceased flag only, the time comes from the expired encounter
    ],
)
def test_bundle_deceased_datetime_equals_the_death_encounter_end(patient: dict) -> None:
    from clinosim.modules.output.fhir_r4 import _build_bundle

    bundle = _build_bundle(_bundle_record(**patient), "US")
    (pat,) = _resources(bundle, "Patient")
    (enc,) = _resources(bundle, "Encounter")
    assert pat["deceasedDateTime"] == enc["period"]["end"] == "2021-11-17T00:35:00Z"
