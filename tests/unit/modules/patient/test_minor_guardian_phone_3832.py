"""A minor's parent contact has a phone of its own (Issue #3832).

The contact used to copy the child's own home or mobile number, which most
children do not have, so the RelatedPerson came out without a telecom. The
number is now drawn from a dedicated person-scoped stream in the country's
mobile format.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from clinosim.determinism import default_rng
from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.seeding import guardian_contact_phone_seed
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_FORMAT = {"US": re.compile(r"^\(\d{3}\) \d{3}-\d{4}$"), "JP": re.compile(r"^0[5789]0-\d{4}-\d{4}$")}


def _child(person_id: str = "POP-000262", home: str = "", mobile: str = "") -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH-1",
        age=5,
        sex="F",
        date_of_birth=date(2021, 3, 14),
        family_name="Griffin",
        given_name="Ava",
        phone_home=home,
        phone_mobile=mobile,
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_minor_without_own_phone_gets_guardian_phone(country: str) -> None:
    patient = activate_patient(_child(), default_rng(1), load_demographics(country))
    phone = patient.contact.emergency_contact_phone
    assert patient.contact.emergency_contact_name
    assert phone
    assert _FORMAT[country].match(phone), phone


@pytest.mark.parametrize("country", ["US", "JP"])
def test_guardian_phone_is_not_the_childs_own(country: str) -> None:
    child = _child(home="03-1234-5678", mobile="090-1111-2222")
    patient = activate_patient(child, default_rng(1), load_demographics(country))
    assert patient.contact.emergency_contact_phone not in {"03-1234-5678", "090-1111-2222"}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_guardian_phone_stable_across_activations(country: str) -> None:
    demo = load_demographics(country)
    phones = set()
    for seed in range(6):
        child = _child()
        phones.add(activate_patient(child, default_rng(seed), demo).contact.emergency_contact_phone)
    assert len(phones) == 1


def test_guardian_phone_draws_nothing_from_activation_stream() -> None:
    demo = load_demographics("US")
    a, b = default_rng(7), default_rng(7)
    activate_patient(_child(), a, demo)
    activate_patient(_child(home="(555) 010-0000"), b, demo)
    assert a.random() == b.random()


def test_seed_is_person_scoped_and_distinct_from_contact_seeds() -> None:
    from clinosim.seeding import emergency_contact_phone_seed, guardian_contact_seed

    assert guardian_contact_phone_seed("P1", "2020-01-01") == guardian_contact_phone_seed("P1", "2020-01-01")
    assert guardian_contact_phone_seed("P1", "2020-01-01") != guardian_contact_phone_seed("P2", "2020-01-01")
    assert guardian_contact_phone_seed("P1", "2020-01-01") != guardian_contact_seed("P1", "2020-01-01")
    assert guardian_contact_phone_seed("P1", "2020-01-01") != emergency_contact_phone_seed("P1", "2020-01-01")
