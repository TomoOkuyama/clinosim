"""A person keeps one marital status across records, and the emergency
contact agrees with it (Issue #3189).

The patient cache activates a ``PatientProfile`` per (person, year), and the
marital status was drawn from the activation stream at whatever position the
earlier draws of that year left it, so records of one person could carry
different statuses. It was also drawn independently of the emergency contact,
so a never-married person could name a spouse. The status is now drawn once
from a person-scoped sub-RNG out of the locale's census table, kept on the
``PersonRecord``, and the contact relationship is drawn conditional on it.
"""

from __future__ import annotations

import copy
from collections import Counter
from datetime import date

import pytest

from clinosim.age_bands import find_age_band
from clinosim.determinism import default_rng
from clinosim.locale.loader import load_demographics, load_marital_status
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _adult(age: int = 52, sex: str = "M", person_id: str = "POP-000042") -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH-42",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 3, 14),
        family_name="Tanaka",
        given_name="Hiroshi",
        phone_home="03-1234-5678",
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_same_person_gets_the_same_marital_status_in_every_record(country: str) -> None:
    demo = load_demographics(country)
    for i in range(20):
        person = _adult(age=25 + 3 * i, sex="MF"[i % 2], person_id=f"POP-{i:06d}")
        statuses = {activate_patient(person, default_rng(seed), demo).marital_status for seed in range(8)}
        assert len(statuses) == 1, (person.person_id, statuses)
        assert statuses <= {"S", "M", "W", "D"}


def test_status_does_not_depend_on_the_activation_stream() -> None:
    demo = load_demographics("US")
    a = activate_patient(_adult(), default_rng(1), demo)
    b = activate_patient(_adult(), default_rng(2), demo)
    assert a.marital_status == b.marital_status


def test_status_is_kept_on_the_person_record_and_survives_ageing() -> None:
    demo = load_demographics("JP")
    person = _adult(age=29)
    first = activate_patient(person, default_rng(3), demo).marital_status
    assert person.marital_status == first
    person.age += 1  # the yearly aging pass crosses an age band
    assert activate_patient(person, default_rng(4), demo).marital_status == first


def test_a_minor_is_never_married_and_stores_nothing() -> None:
    demo = load_demographics("US")
    person = _adult(age=10)
    assert activate_patient(person, default_rng(3), demo).marital_status == "S"
    assert person.marital_status == ""


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("status", ["S", "D", "W"])
def test_no_spouse_contact_unless_married(country: str, status: str) -> None:
    demo = load_demographics(country)
    rels = Counter()
    for i in range(200):
        person = _adult(age=20 + (i % 70), person_id=f"POP-{i:06d}")
        person.marital_status = status
        rels[activate_patient(person, default_rng(i), demo).contact.emergency_contact_relationship] += 1
    assert "spouse" not in rels
    if status == "W":
        assert set(rels) <= {"child", "sibling"}


def test_married_people_still_name_a_spouse() -> None:
    demo = load_demographics("US")
    rels = Counter()
    for i in range(200):
        person = _adult(person_id=f"POP-{i:06d}")
        person.marital_status = "M"
        rels[activate_patient(person, default_rng(i), demo).contact.emergency_contact_relationship] += 1
    assert rels["spouse"] > 50


def test_other_draws_of_the_activation_stream_are_unchanged() -> None:
    """Whatever status the person holds, the activation stream makes the same
    draws, so every later field of the record is the same."""
    demo = load_demographics("US")
    profiles = []
    for status in ("S", "M", "W"):
        person = _adult()
        person.marital_status = status
        profiles.append(activate_patient(person, default_rng(7), demo))
    for field in ("insurance_type", "race", "ethnicity", "health_literacy"):
        assert len({getattr(p, field) for p in profiles}) == 1, field


@pytest.mark.parametrize("country", ["US", "JP"])
def test_draw_matches_the_census_table(country: str) -> None:
    """The marginal over many persons of one sex and age matches the table row."""
    from clinosim.modules.patient._marital import draw_marital_status

    table = load_marital_status(country)
    n = 4000
    for sex, age in (("M", 32), ("F", 47), ("F", 82)):
        row = table["distribution"][sex][find_age_band(table["distribution"][sex], age)]
        total = sum(row.values())
        drawn = Counter(draw_marital_status(f"POP-{i:06d}", "1950-01-01", age, sex, country) for i in range(n))
        for code, count in row.items():
            assert abs(drawn[code] / n - count / total) < 0.03, (sex, age, code)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_table_bands_cover_every_adult_age(country: str) -> None:
    table = load_marital_status(country)
    for sex in ("M", "F"):
        bands = table["distribution"][sex]
        for age in range(int(table["adult_age_min"]), 121):
            assert find_age_band(bands, age) is not None, (sex, age)
    for rows in table["emergency_contact"]["relationships"].values():
        for age in range(int(table["adult_age_min"]), 121):
            assert find_age_band(rows, age) is not None, age


def test_reactivation_reuses_contact_and_status() -> None:
    demo = load_demographics("US")
    fresh = _adult()
    seen = copy.deepcopy(fresh)
    first = activate_patient(seen, default_rng(99), demo)
    again = activate_patient(seen, default_rng(5), demo)
    assert (first.marital_status, first.contact.emergency_contact_relationship) == (
        again.marital_status,
        again.contact.emergency_contact_relationship,
    )
