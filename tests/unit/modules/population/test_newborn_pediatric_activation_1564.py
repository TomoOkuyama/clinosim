"""Newborn pediatric calendar activation — Issue #1564 Phase 1 follow-up.

Covers the activation half of Phase 1: a newborn registered mid-sim via
``register_newborn`` must participate in the pediatric calendar for
years from their birth year onward, and must NOT fire events for years
before their birth year.

Phase 1 scaffold (previous PR) added registry membership. This PR adds
the pre-birth filters that make the calendar emit sensibly:

* ``PersonRecord.is_alive_at(when)`` now returns False when ``when`` is
  before ``date_of_birth``.
* ``generate_pediatric_events`` short-circuits with no events and no
  RNG draw when the computed age for that cal_year is negative.

The initial cohort's RNG streams are unaffected: ``spawn(N+K)`` returns
the same first N streams as ``spawn(N)``, so adding newborns to the
registry at the end preserves byte-identity for every pre-existing
person.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.pediatric.calendar import generate_pediatric_events
from clinosim.modules.population.engine import Household, PopulationRegistry
from clinosim.modules.population.newborn import register_newborn
from clinosim.types.patient import (
    Address,
    ContactInfo,
    PatientProfile,
    PersonName,
)
from clinosim.types.population import PersonRecord


def _mother() -> PersonRecord:
    return PersonRecord(
        person_id="PT-MOM-002",
        household_id="HH-NB-1",
        age=30,
        sex="F",
        date_of_birth=date(1996, 1, 1),
    )


def _registry() -> PopulationRegistry:
    mother = _mother()
    hh = Household(household_id=mother.household_id, members=[mother])
    reg = PopulationRegistry(
        households=[hh],
        persons={mother.person_id: mother},
    )
    reg.initial_person_ids = set(reg.persons.keys())
    return reg


def _newborn_profile(mother: PersonRecord, delivery_date: date) -> PatientProfile:
    return PatientProfile(
        patient_id=f"{mother.person_id}-BABY-01",
        household_id=mother.household_id,
        name=PersonName(family_name="Smith", given_name=""),
        age=0,
        sex="F",
        date_of_birth=delivery_date,
        height_cm=50.0,
        weight_kg=3.2,
        bmi=12.8,
        address=Address(country="US"),
        contact=ContactInfo(),
        occupation="infant",
    )


# --- is_alive_at pre-birth guard --------------------------------------


def test_is_alive_at_returns_false_before_birth() -> None:
    """A date before `date_of_birth` must count as not-alive."""
    p = PersonRecord(
        person_id="PT-X",
        household_id="HH-X",
        age=0,
        sex="M",
        date_of_birth=date(2025, 6, 15),
    )
    # Before birth → False
    assert p.is_alive_at(date(2025, 6, 14)) is False
    assert p.is_alive_at(date(2024, 12, 31)) is False
    # On and after birth → True
    assert p.is_alive_at(date(2025, 6, 15)) is True
    assert p.is_alive_at(date(2026, 1, 1)) is True


def test_is_alive_at_still_respects_death_date() -> None:
    """Pre-birth guard must not affect the existing death-date logic."""
    p = PersonRecord(
        person_id="PT-Y",
        household_id="HH-Y",
        age=50,
        sex="F",
        date_of_birth=date(1975, 1, 1),
        date_of_death=date(2030, 5, 10),
    )
    assert p.is_alive_at(date(2030, 5, 9)) is True
    assert p.is_alive_at(date(2030, 5, 10)) is False
    assert p.is_alive_at(date(2029, 1, 1)) is True
    assert p.is_alive_at(date(1974, 1, 1)) is False  # also pre-birth


# --- generate_pediatric_events age<0 short-circuit --------------------


def test_pediatric_events_empty_for_pre_birth_year_no_rng_draw() -> None:
    """A newborn born in 2025 must not consume RNG for cal_year 2023."""
    newborn_person = PersonRecord(
        person_id="PT-BABY-1",
        household_id="HH-NB-1",
        age=0,
        sex="M",
        date_of_birth=date(2025, 6, 1),
    )
    # A stub schedule with a well-child entry for age 0.
    schedule = {
        "infant": {
            "age_min": 0,
            "age_max": 1,
            "visits_per_year": [6, 7, 8],
            "disease_id": "well_child_infant",
        }
    }

    # Pre-birth year: no events, RNG not consumed.
    prng = np.random.default_rng(42)
    before = prng.bit_generator.state
    events = generate_pediatric_events(newborn_person, 2023, prng, schedule=schedule)
    after = prng.bit_generator.state
    assert events == []
    assert before == after, "pre-birth short-circuit must not touch the per-person rng"


def test_pediatric_events_fire_in_birth_year_and_after() -> None:
    """A newborn born in 2025 participates for 2025, 2026, etc."""
    newborn_person = PersonRecord(
        person_id="PT-BABY-2",
        household_id="HH-NB-1",
        age=0,
        sex="M",
        date_of_birth=date(2025, 6, 1),
        # care_seeking_threshold is low so the Bernoulli typically passes.
        care_seeking_threshold=0.05,
    )
    schedule = {
        "infant": {
            "age_min": 0,
            "age_max": 1,
            "visits_per_year": [6, 7, 8],
            "disease_id": "well_child_infant",
        },
        "toddler": {
            "age_min": 1,
            "age_max": 3,
            "visits_per_year": [2, 3, 4],
            "disease_id": "well_child_toddler",
        },
    }
    # Birth year (age=0): well-child infant visits.
    events_birth = generate_pediatric_events(
        newborn_person,
        2025,
        np.random.default_rng(1),
        schedule=schedule,
    )
    assert len(events_birth) >= 1
    assert all(e.disease_id == "well_child_infant" for e in events_birth)

    # Age 2 (cal_year=2027): toddler visits.
    events_toddler = generate_pediatric_events(
        newborn_person,
        2027,
        np.random.default_rng(1),
        schedule=schedule,
    )
    assert len(events_toddler) >= 1
    assert all(e.disease_id == "well_child_toddler" for e in events_toddler)


# --- End-to-end: register_newborn → pediatric calendar visibility -----


def test_registered_newborn_is_iterated_after_initial_cohort() -> None:
    """`registry.persons.values()` must yield the mother first, then the
    newborn — the dict-insertion order that `generate_healthcare_calendar`
    depends on for per-position RNG spawning."""
    reg = _registry()
    mother = reg.persons["PT-MOM-002"]
    newborn = _newborn_profile(mother, delivery_date=date(2025, 6, 1))
    register_newborn(reg, mother, newborn)

    pids = list(reg.persons.keys())
    assert pids[0] == mother.person_id
    assert pids[-1] == newborn.patient_id


def test_spawn_shape_preserves_initial_cohort_rng() -> None:
    """`rng.spawn(N+K)` must return the same first N streams as
    `rng.spawn(N)` so adding newborns at the end of the registry does
    not shift the initial cohort's per-person streams."""
    seed = 20260601
    rng = np.random.default_rng(seed)
    r_initial_only = rng.spawn(3)
    rng = np.random.default_rng(seed)
    r_with_newborns = rng.spawn(5)
    for i in range(3):
        a = r_initial_only[i].random(5)
        b = r_with_newborns[i].random(5)
        assert np.array_equal(a, b), f"stream {i} drifted when registry grew"
