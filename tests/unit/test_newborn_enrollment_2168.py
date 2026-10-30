"""Newborns join the simulated population at birth-stay discharge (Issue #2168)."""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.modules.immunization.enricher import _align_to_encounters
from clinosim.modules.population.engine import PopulationRegistry, generate_healthcare_calendar
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _newborn(dob: date, enrolled: date | None) -> PersonRecord:
    return PersonRecord(
        person_id="P-BABY",
        household_id="H",
        age=0,
        sex="F",
        date_of_birth=dob,
        enrolled_from=enrolled,
    )


def test_in_population_starts_at_enrollment_and_ends_at_death() -> None:
    nb = _newborn(date(2025, 3, 10), date(2025, 3, 13))
    assert not nb.in_population_at(date(2025, 3, 9))  # before birth
    assert not nb.in_population_at(date(2025, 3, 12))  # still in the birth stay
    assert nb.in_population_at(date(2025, 3, 13))
    nb.record_death(date(2025, 9, 1), "community")
    assert nb.in_population_at(date(2025, 8, 31))
    assert not nb.in_population_at(date(2025, 9, 1))


def test_initial_cohort_person_is_in_population_from_birth() -> None:
    p = PersonRecord(person_id="P1", household_id="H", age=40, sex="M", date_of_birth=date(1985, 1, 1))
    assert p.enrolled_from is None
    assert p.in_population_at(date(2025, 1, 1))


def test_in_population_during_covers_partial_years() -> None:
    nb = _newborn(date(2025, 10, 20), date(2025, 10, 23))
    assert nb.in_population_during(date(2025, 1, 1), date(2025, 12, 31))
    assert not nb.in_population_during(date(2024, 1, 1), date(2024, 12, 31))
    nb.record_death(date(2026, 2, 1), "community")
    assert nb.in_population_during(date(2026, 1, 1), date(2026, 12, 31))
    assert not nb.in_population_during(date(2027, 1, 1), date(2027, 12, 31))


def test_birth_year_calendar_includes_a_mid_year_newborn_after_enrollment() -> None:
    reg = PopulationRegistry()
    nb = _newborn(date(2025, 3, 10), date(2025, 3, 13))
    reg.persons[nb.person_id] = nb
    events = generate_healthcare_calendar(reg, 2025, "US", np.random.default_rng(0))
    mine = [e for e in events if e.person_id == nb.person_id]
    assert mine, "a newborn enrolled in March must get birth-year well-child events"


def test_immunization_inside_an_inpatient_stay_binds_to_that_stay() -> None:
    from types import SimpleNamespace

    birth = Encounter(
        encounter_id="ENC-BIRTH",
        patient_id="P-BABY",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 3, 10, 14, 0),
        discharge_datetime=datetime(2025, 3, 12, 10, 0),
    )
    clinic = Encounter(
        encounter_id="ENC-CLINIC",
        patient_id="P-BABY",
        encounter_type=EncounterType.OUTPATIENT,
        admission_datetime=datetime(2025, 3, 20, 10, 0),
        discharge_datetime=datetime(2025, 3, 20, 10, 20),
    )
    hepb = SimpleNamespace(occurrence_date=date(2025, 3, 10), encounter_id="")
    later = SimpleNamespace(occurrence_date=date(2025, 3, 25), encounter_id="")
    _align_to_encounters([hepb, later], [birth, clinic])
    assert (hepb.encounter_id, hepb.occurrence_date) == ("ENC-BIRTH", date(2025, 3, 10))
    assert later.encounter_id == "ENC-CLINIC"
