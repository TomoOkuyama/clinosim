"""One death record per person (Issue #2166).

A person's death is stored once, as ``PersonRecord.date_of_death`` plus
``death_place``. ``is_alive`` is derived from it, every death site goes
through ``record_death``, and patient profiles are synced to it.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.modules.population.vital_status import record_hospital_death, sync_profile_death_dates
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _person(pid: str = "P1") -> PersonRecord:
    return PersonRecord(person_id=pid, household_id="H1", age=70, sex="F", date_of_birth=date(1954, 3, 1))


def _expired_record(pid: str, admit: datetime, death: datetime) -> CIFPatientRecord:
    enc = Encounter(
        encounter_id=f"ENC-{pid}",
        patient_id=pid,
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=death,
        discharge_disposition=DischargeDisposition.EXP,
    )
    return CIFPatientRecord(patient=PatientProfile(patient_id=pid), encounters=[enc], deceased=True)


def test_new_person_is_alive_with_no_death_recorded() -> None:
    p = _person()
    assert p.is_alive
    assert p.date_of_death is None
    assert p.death_place is None


def test_record_death_sets_date_and_place() -> None:
    p = _person()
    p.record_death(date(2025, 4, 2), "hospital")
    assert not p.is_alive
    assert p.date_of_death == date(2025, 4, 2)
    assert p.death_place == "hospital"
    assert p.is_alive_at(date(2025, 4, 1))
    assert not p.is_alive_at(date(2025, 4, 2))


def test_record_death_keeps_the_earliest_death() -> None:
    p = _person()
    p.record_death(date(2026, 3, 2), "community")
    p.record_death(date(2025, 4, 2), "hospital")  # earlier: replaces
    p.record_death(date(2026, 1, 1), "community")  # later: ignored
    assert (p.date_of_death, p.death_place) == (date(2025, 4, 2), "hospital")


def test_record_death_rejects_unknown_place() -> None:
    with pytest.raises(ValueError):
        _person().record_death(date(2025, 1, 1), "home")


def test_is_alive_is_not_a_constructor_flag() -> None:
    with pytest.raises(TypeError):
        PersonRecord(  # type: ignore[call-arg]
            person_id="P1", household_id="H1", age=1, sex="M", date_of_birth=date(2024, 1, 1), is_alive=False
        )


def test_record_hospital_death_uses_the_expired_discharge_date() -> None:
    p = _person()
    p.record_death(date(2026, 3, 2), "community")  # pre-sampled later natural death
    rec = _expired_record("P1", datetime(2025, 4, 1, 9), datetime(2025, 4, 6, 3, 15))
    assert record_hospital_death(p, rec) == date(2025, 4, 6)
    assert (p.date_of_death, p.death_place) == (date(2025, 4, 6), "hospital")


def test_record_hospital_death_ignores_a_surviving_record() -> None:
    p = _person()
    rec = _expired_record("P1", datetime(2025, 4, 1, 9), datetime(2025, 4, 6, 3, 15))
    rec.deceased = False
    assert record_hospital_death(p, rec) is None
    assert p.is_alive


def test_sync_profile_death_dates_writes_every_record_of_the_person() -> None:
    reg = PopulationRegistry()
    p = _person()
    reg.persons[p.person_id] = p
    p.record_death(date(2025, 4, 6), "hospital")
    early = CIFPatientRecord(patient=PatientProfile(patient_id="P1"))  # visit before death, profile cached earlier
    stale = CIFPatientRecord(patient=PatientProfile(patient_id="P1", date_of_death=date(2026, 3, 2)))
    sync_profile_death_dates([early, stale], reg, as_of=date(2026, 12, 31))
    assert early.patient.date_of_death == date(2025, 4, 6)
    assert stale.patient.date_of_death == date(2025, 4, 6)


def test_sync_profile_death_dates_hides_deaths_after_the_cutoff() -> None:
    reg = PopulationRegistry()
    p = _person()
    reg.persons[p.person_id] = p
    p.record_death(date(2026, 6, 1), "community")
    rec = CIFPatientRecord(patient=PatientProfile(patient_id="P1", date_of_death=date(2026, 6, 1)))
    sync_profile_death_dates([rec], reg, as_of=date(2026, 3, 31))
    assert rec.patient.date_of_death is None


def test_death_counts_by_place_counts_deaths_inside_the_window() -> None:
    from clinosim.modules.population.vital_status import death_counts_by_place

    reg = PopulationRegistry()
    for pid, when, place in [
        ("A", date(2025, 1, 5), "hospital"),
        ("B", date(2025, 7, 1), "community"),
        ("C", date(2025, 8, 1), "community"),
        ("D", date(2027, 1, 1), "community"),  # after the window
        ("E", None, None),
    ]:
        p = _person(pid)
        if when is not None:
            p.record_death(when, place)
        reg.persons[pid] = p
    assert death_counts_by_place(reg, date(2025, 1, 1), date(2026, 12, 31)) == {"hospital": 1, "community": 2}


def test_run_beta_accepts_month_precision_time_range() -> None:
    """The end-of-run death sync must parse ``YYYY-MM`` bounds (test fixtures use them)."""
    from clinosim.simulator.engine import run_beta
    from clinosim.types.config import SimulatorConfig

    ds = run_beta(
        SimulatorConfig(country="US", catchment_population=50, random_seed=3, time_range=("2025-01", "2025-02"))
    )
    assert ds.metadata.country == "US"
