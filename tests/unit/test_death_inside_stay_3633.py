"""A population death date never falls inside a survivor inpatient stay (Issue #3633).

The community death date is drawn before the stays are simulated. A stay that
runs through that date either ends as an in-hospital death on that date
(``population_death_date`` forces the death in the daily loop) or, for a stay
without a modelled death course, the death moves to after the discharge.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from clinosim import determinism
from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.countries import lang_for
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_demographics
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.healthcare_system.loader import load_healthcare_config
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import LifeEvent
from clinosim.modules.population.vital_status import defer_death_past_stay
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.enrichers import register_builtin_enrichers
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DISEASE = "bacterial_pneumonia"
_EVENT_DATE = datetime(2026, 5, 24)


def _stay(population_death_date: date | None) -> CIFPatientRecord:
    config = SimulatorConfig(random_seed=7, country="US")
    rng = determinism.default_rng(7)
    healthcare = load_healthcare_config("US")
    roster = generate_roster(config.hospital_scale, "US", rng)
    demo = load_demographics("US")
    register_builtin_enrichers()
    person = PersonRecord(
        person_id="POP-T3633",
        household_id="HH-T3633",
        age=78,
        sex="M",
        date_of_birth=date(1948, 1, 1),
        family_name=t("module_text.test_family", lang_for("US")),
        given_name=t("module_text.test_given", lang_for("US"), n=1),
    )
    patient = activate_patient(person, rng, demo)
    event = LifeEvent(
        person_id=patient.patient_id,
        event_type="forced",
        timestamp=_EVENT_DATE,
        severity=0.5,
        disease_id=_DISEASE,
        requires_hospital=True,
        condition_type="known_disease",
    )
    return _simulate_patient(
        patient,
        event,
        _DISEASE,
        load_disease_protocol(_DISEASE),
        healthcare,
        roster,
        config,
        determinism.default_rng(11),
        population_death_date=population_death_date,
    )


def test_a_stay_without_a_population_death_is_a_survivor_stay_longer_than_three_days() -> None:
    record = _stay(None)
    assert not record.deceased
    assert record.encounters[0].discharge_datetime.date() > _EVENT_DATE.date() + timedelta(days=3)


def test_a_death_date_inside_the_stay_makes_it_an_in_hospital_death_on_that_date() -> None:
    death_date = _EVENT_DATE.date() + timedelta(days=3)
    record = _stay(death_date)
    enc = record.encounters[0]
    assert record.deceased
    assert enc.discharge_disposition == DischargeDisposition.EXP
    assert enc.discharge_datetime.date() == death_date
    assert record.death_day == (death_date - enc.admission_datetime.date()).days
    died_at = enc.discharge_datetime
    assert all(v.timestamp <= died_at for v in record.vital_signs)
    assert all(m.scheduled_datetime <= died_at for m in record.medication_administrations)
    assert all(r.result_datetime <= died_at for r in record.lab_results)


def test_a_death_date_after_the_stay_leaves_the_stay_alone() -> None:
    survivor = _stay(None)
    discharge = survivor.encounters[0].discharge_datetime.date()
    record = _stay(discharge + timedelta(days=1))
    assert not record.deceased
    assert record.encounters[0].discharge_datetime == survivor.encounters[0].discharge_datetime


def _survivor_record(admit: datetime, discharge: datetime) -> CIFPatientRecord:
    enc = Encounter(
        encounter_id="ENC-T3633",
        patient_id="P1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=admit,
        discharge_datetime=discharge,
        discharge_disposition=DischargeDisposition.HOME,
    )
    return CIFPatientRecord(patient=PatientProfile(patient_id="P1"), encounters=[enc])


def _person() -> PersonRecord:
    return PersonRecord(person_id="P1", household_id="H1", age=70, sex="F", date_of_birth=date(1954, 3, 1))


def test_a_stay_without_a_death_course_moves_the_death_after_the_discharge() -> None:
    person = _person()
    person.record_death(date(2026, 5, 27), "community")
    record = _survivor_record(datetime(2026, 5, 24, 8, 44), datetime(2026, 6, 11, 10, 44))
    assert defer_death_past_stay(person, record, master_seed=500) is True
    assert person.date_of_death is not None
    assert person.date_of_death > date(2026, 6, 11)
    assert person.death_place == "community"
    # Deterministic for the same seed and person.
    again = _person()
    again.record_death(date(2026, 5, 27), "community")
    defer_death_past_stay(again, record, master_seed=500)
    assert again.date_of_death == person.date_of_death


def test_a_death_outside_the_stay_is_not_moved() -> None:
    record = _survivor_record(datetime(2026, 5, 24, 8, 44), datetime(2026, 6, 11, 10, 44))
    for dod in (date(2026, 5, 20), date(2026, 6, 11), date(2026, 8, 1), None):
        person = _person()
        if dod is not None:
            person.record_death(dod, "community")
        assert defer_death_past_stay(person, record, master_seed=500) is False
        assert person.date_of_death == dod
