"""Issue #3658: a minor has a parent as emergency contact and is never "employed"."""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.determinism import default_rng
from clinosim.locale.loader import load_demographics, load_marital_status
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _person(i: int, age: int, sex: str = "F") -> PersonRecord:
    return PersonRecord(
        person_id=f"POP-{i:06d}",
        household_id=f"HH-{i}",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 3, 14),
        family_name="Tanaka",
        given_name="Hanako",
        phone_home="03-1234-5678",
    )


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize("age", [0, 3, 8, 14, 17])
def test_minor_has_a_parent_contact_with_sex_role_and_name(country: str, age: int) -> None:
    demo = load_demographics(country)
    for i in range(40):
        person = _person(i, age, "M" if i % 2 else "F")
        c = activate_patient(person, default_rng(i), demo).contact
        assert c.emergency_contact_relationship == "parent"
        assert c.emergency_contact_sex in ("M", "F")
        assert c.emergency_contact_role == {"M": "FTH", "F": "MTH"}[c.emergency_contact_sex]
        assert c.emergency_contact_name
        assert c.emergency_contact_family_name and c.emergency_contact_given_name
        # Issue #3832: the parent has a phone of their own, not the child's.
        assert c.emergency_contact_phone and c.emergency_contact_phone != "03-1234-5678"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_guardian_contact_is_stable_across_activations(country: str) -> None:
    demo = load_demographics(country)
    person = _person(7, 9)
    first = activate_patient(person, default_rng(1), demo).contact
    second = activate_patient(person, default_rng(99), demo).contact
    assert first.emergency_contact_name == second.emergency_contact_name
    assert first.emergency_contact_sex == second.emergency_contact_sex


def test_child_born_in_the_simulation_keeps_its_mother() -> None:
    person = _person(1, 0)
    person.guardian_contact_name = "Mary Tanaka"
    person.guardian_contact_phone = "555-0100"
    person.guardian_contact_relationship = "parent"
    person.guardian_contact_sex = "F"
    person.guardian_contact_role = "MTH"
    person.guardian_contact_family_name = "Tanaka"
    person.guardian_contact_given_name = "Mary"
    c = activate_patient(person, default_rng(1), load_demographics("US")).contact
    assert (c.emergency_contact_name, c.emergency_contact_role) == ("Mary Tanaka", "MTH")


@pytest.mark.parametrize("country", ["US", "JP"])
def test_adult_contact_is_unchanged_by_the_guardian_stream(country: str) -> None:
    demo = load_demographics(country)
    # The adult contact comes from the adult stream only: two persons that differ
    # only in the id of a minor sibling activate identically.
    a = activate_patient(_person(5, 45), default_rng(5), demo).contact
    b = activate_patient(_person(5, 45), default_rng(5), demo).contact
    assert a == b
    assert a.emergency_contact_name


@pytest.mark.parametrize("country", ["US", "JP"])
def test_minor_relationship_table_is_validated_data(country: str) -> None:
    table = load_marital_status(country)["emergency_contact"]["minor_relationships"]
    assert set(table) == {"parent"} and table["parent"] > 0


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(
    ("age", "expected"), [(0, ""), (2, ""), (5, ""), (6, "student"), (12, "student"), (17, "student")]
)
def test_minor_employment(country: str, age: int, expected: str) -> None:
    demo = load_demographics(country)
    status = activate_patient(_person(3, age), default_rng(3), demo).employment_status
    assert status == expected
    assert status != "employed"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_adult_employment_is_unchanged(country: str) -> None:
    demo = load_demographics(country)
    assert activate_patient(_person(3, 30), default_rng(3), demo).employment_status == "employed"
    assert activate_patient(_person(3, 70), default_rng(3), demo).employment_status == "retired"
