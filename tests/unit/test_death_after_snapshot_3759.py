"""A death after the snapshot is not known to the record (Issue #3759).

A stay whose simulated death falls after the snapshot date stays in progress:
the patient is alive in the record (no death date, no death flag) and nothing
dated after the snapshot is kept. A death inside the window is unchanged.
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
from clinosim.modules.population.engine import LifeEvent, PopulationRegistry
from clinosim.modules.population.vital_status import known_death_date, sync_profile_death_dates
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.enrichers import register_builtin_enrichers
from clinosim.simulator.inpatient import _simulate_patient
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import EncounterStatus
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DISEASE = "bacterial_pneumonia"
_EVENT_DATE = datetime(2026, 5, 24)
_DEATH_DATE = _EVENT_DATE.date() + timedelta(days=3)


def _stay(snapshot: date) -> CIFPatientRecord:
    config = SimulatorConfig(random_seed=7, country="US", snapshot_date=snapshot.isoformat())
    rng = determinism.default_rng(7)
    healthcare = load_healthcare_config("US")
    roster = generate_roster(config.hospital_scale, "US", rng)
    demo = load_demographics("US")
    register_builtin_enrichers()
    person = PersonRecord(
        person_id="POP-T3759",
        household_id="HH-T3759",
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
        population_death_date=_DEATH_DATE,
    )


def test_a_death_after_the_snapshot_leaves_the_patient_alive_and_the_stay_in_progress() -> None:
    snapshot = _DEATH_DATE - timedelta(days=1)
    record = _stay(snapshot)
    enc = record.encounters[0]
    assert not record.deceased
    assert record.death_day is None
    assert record.patient.date_of_death is None
    assert record.patient.death_datetime is None
    assert enc.status == EncounterStatus.IN_PROGRESS
    assert enc.discharge_datetime is None
    assert enc.discharge_disposition == ""
    cutoff = datetime.combine(snapshot, datetime.max.time())
    assert all(v.timestamp <= cutoff for v in record.vital_signs)
    assert all(r.result_datetime <= cutoff for r in record.lab_results)


def test_a_death_inside_the_window_still_ends_the_stay_as_expired() -> None:
    record = _stay(_DEATH_DATE + timedelta(days=5))
    enc = record.encounters[0]
    assert record.deceased
    assert enc.status == EncounterStatus.COMPLETED
    assert enc.discharge_disposition == DischargeDisposition.EXP
    assert enc.discharge_datetime.date() == _DEATH_DATE
    assert record.patient.date_of_death == _DEATH_DATE


def test_the_snapshot_day_itself_is_inside_the_window() -> None:
    record = _stay(_DEATH_DATE)
    assert record.deceased
    assert record.encounters[0].discharge_datetime.date() == _DEATH_DATE


def test_the_death_cutoff_applies_to_every_place() -> None:
    person = PersonRecord(person_id="P1", household_id="H1", age=70, sex="F", date_of_birth=date(1954, 3, 1))
    person.record_death(date(2026, 12, 1), "hospital")
    assert known_death_date(person, date(2026, 11, 22)) is None
    assert known_death_date(person, date(2026, 12, 1)) == date(2026, 12, 1)
    reg = PopulationRegistry()
    reg.persons["P1"] = person
    rec = CIFPatientRecord(patient=PatientProfile(patient_id="P1"))
    sync_profile_death_dates([rec], reg, as_of=date(2026, 11, 22))
    assert rec.patient.date_of_death is None
    assert rec.patient.death_datetime is None
