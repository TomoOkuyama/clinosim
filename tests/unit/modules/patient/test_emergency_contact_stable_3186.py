"""A person keeps one emergency contact across records (Issue #3186).

The patient cache activates a ``PatientProfile`` per (person, year), and the
emergency contact was drawn from the activation stream at whatever position
the earlier draws (chronic conditions, stages, ...) left it, so two records of
one person could name different contacts (a spouse in one, a child in the
next). The contact is now chosen once, from a person-scoped sub-RNG, and kept
on the ``PersonRecord``.
"""

from __future__ import annotations

import copy
from datetime import date

import pytest

from clinosim.determinism import default_rng
from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _adult(age: int = 52, person_id: str = "POP-000042") -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH-42",
        age=age,
        sex="M",
        date_of_birth=date(2026 - age, 3, 14),
        family_name="Tanaka",
        given_name="Hiroshi",
        phone_home="03-1234-5678",
    )


def _contact(patient) -> tuple[str, str, str]:
    c = patient.contact
    return (c.emergency_contact_name, c.emergency_contact_relationship, c.emergency_contact_phone)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_same_person_gets_the_same_emergency_contact_in_every_record(country: str) -> None:
    demo = load_demographics(country)
    person = _adult()
    contacts = {_contact(activate_patient(person, default_rng(seed), demo)) for seed in range(12)}
    assert len(contacts) == 1
    name, rel, phone = next(iter(contacts))
    assert name and rel and phone == "03-1234-5678"


def test_contact_does_not_depend_on_the_activation_stream() -> None:
    """Two fresh copies of one person activated from different streams agree."""
    demo = load_demographics("US")
    a = activate_patient(_adult(), default_rng(1), demo)
    b = activate_patient(_adult(), default_rng(2), demo)
    assert _contact(a) == _contact(b)


def test_crossing_into_the_elderly_band_keeps_the_contact() -> None:
    demo = load_demographics("US")
    person = _adult(age=74)  # the last age of the locale's 18-74 contact band
    first = _contact(activate_patient(person, default_rng(5), demo))
    person.age += 1  # the yearly aging pass
    assert _contact(activate_patient(person, default_rng(5), demo)) == first


def test_other_draws_of_the_activation_stream_are_unchanged() -> None:
    """A re-activation that reuses the stored contact consumes the same draws
    from the activation stream as the first one, so every later field matches."""
    demo = load_demographics("US")
    fresh = _adult()
    seen = copy.deepcopy(fresh)
    activate_patient(seen, default_rng(99), demo)  # stores the contact
    a = activate_patient(fresh, default_rng(7), demo)
    b = activate_patient(seen, default_rng(7), demo)
    for field in ("marital_status", "insurance_type", "race", "ethnicity", "health_literacy"):
        assert getattr(a, field) == getattr(b, field), field


def test_contact_is_kept_on_the_person_record() -> None:
    demo = load_demographics("JP")
    person = _adult()
    patient = activate_patient(person, default_rng(3), demo)
    assert person.emergency_contact_name == patient.contact.emergency_contact_name
    assert person.emergency_contact_relationship == patient.contact.emergency_contact_relationship


def test_a_minor_without_a_guardian_gets_no_contact_and_stores_none() -> None:
    demo = load_demographics("US")
    person = _adult(age=10)
    patient = activate_patient(person, default_rng(3), demo)
    assert _contact(patient)[:2] == ("", "")
    assert person.emergency_contact_relationship == ""
