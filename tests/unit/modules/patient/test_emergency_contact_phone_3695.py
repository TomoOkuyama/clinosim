"""An adult's emergency contact has a phone of their own (Issue #3695).

The contact used to carry the patient's own home or mobile number, so the
person to be reached was "reachable" only on the patient's phone. The number
is now drawn from a person-scoped stream (hash of the person id, birth date
and a salt) in the country's mobile format, so it is stable per person and
touches no existing RNG stream.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from clinosim.determinism import default_rng
from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.seeding import emergency_contact_phone_seed
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_FORMAT = {"US": re.compile(r"^\(\d{3}\) \d{3}-\d{4}$"), "JP": re.compile(r"^0[5789]0-\d{4}-\d{4}$")}


def _adult(age: int = 52, person_id: str = "POP-000042", mobile: str = "090-1111-2222") -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH-42",
        age=age,
        sex="M",
        date_of_birth=date(2026 - age, 3, 14),
        family_name="Tanaka",
        given_name="Hiroshi",
        phone_home="03-1234-5678",
        phone_mobile=mobile,
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_adult_contact_phone_is_not_the_patients_and_is_in_locale_format(country: str) -> None:
    demo = load_demographics(country)
    patient = activate_patient(_adult(), default_rng(1), demo)
    phone = patient.contact.emergency_contact_phone
    assert patient.contact.emergency_contact_name
    assert phone
    assert phone not in {patient.contact.phone_home, patient.contact.phone_mobile}
    assert _FORMAT[country].match(phone), phone


@pytest.mark.parametrize("country", ["US", "JP"])
def test_contact_phone_is_stable_across_activations(country: str) -> None:
    demo = load_demographics(country)
    phones = {activate_patient(_adult(), default_rng(seed), demo).contact.emergency_contact_phone for seed in range(8)}
    assert len(phones) == 1


def test_contact_phone_differs_between_people() -> None:
    demo = load_demographics("JP")
    phones = {
        activate_patient(_adult(person_id=f"POP-{i:06d}"), default_rng(1), demo).contact.emergency_contact_phone
        for i in range(20)
    }
    assert len(phones) > 10


def test_seed_is_person_scoped() -> None:
    assert emergency_contact_phone_seed("P1", "1970-01-01") == emergency_contact_phone_seed("P1", "1970-01-01")
    assert emergency_contact_phone_seed("P1", "1970-01-01") != emergency_contact_phone_seed("P2", "1970-01-01")


def test_minor_guardian_phone_unchanged() -> None:
    demo = load_demographics("JP")
    child = PersonRecord(
        person_id="POP-000007",
        household_id="HH-7",
        age=6,
        sex="F",
        date_of_birth=date(2020, 5, 1),
        family_name="Sato",
        given_name="Hana",
        guardian_contact_name="Sato Mika",
        guardian_contact_phone="090-9999-0000",
        guardian_contact_relationship="mother",
    )
    patient = activate_patient(child, default_rng(2), demo)
    assert patient.contact.emergency_contact_phone == "090-9999-0000"
