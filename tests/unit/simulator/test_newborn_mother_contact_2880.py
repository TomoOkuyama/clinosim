"""Every newborn keeps its mother as contact (Issue #2880).

The mother contact was built only on the birth-admission profile; a later
activation of the child from its PersonRecord had no guardian, so the FHIR
Patient of most newborns carried no contact. The US contact name was also
written family-first.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.simulator.perinatal import _newborn_contact_from_mother
from clinosim.types.patient import ContactInfo, PatientProfile, PersonName

pytestmark = pytest.mark.unit


def _mother() -> PatientProfile:
    m = PatientProfile(patient_id="POP-000001", sex="F")
    m.name = PersonName(family_name="Hsu", given_name="Karen")
    m.contact = ContactInfo(phone_home="(978) 235-1953", phone_mobile="(781) 529-8470")
    return m


def test_us_mother_contact_is_given_name_first() -> None:
    c = _newborn_contact_from_mother(_mother(), "US")
    assert c.emergency_contact_name == "Karen Hsu"
    assert c.emergency_contact_relationship == "MTH"


def test_jp_mother_contact_is_family_name_first() -> None:
    assert _newborn_contact_from_mother(_mother(), "JP").emergency_contact_name == "Hsu Karen"


def test_later_activation_of_a_child_keeps_the_guardian() -> None:
    from clinosim.determinism import default_rng
    from clinosim.locale.loader import load_demographics
    from clinosim.modules.patient.activator import activate_patient
    from clinosim.types.population import PersonRecord

    person = PersonRecord(
        person_id="POP-000001-BABY",
        household_id="HH-1",
        age=1,
        sex="M",
        date_of_birth=date(2024, 12, 20),
        guardian_contact_name="Karen Hsu",
        guardian_contact_phone="(781) 529-8470",
        guardian_contact_relationship="MTH",
    )
    patient = activate_patient(person, default_rng(1), load_demographics("US"))
    assert patient.contact.emergency_contact_name == "Karen Hsu"
    assert patient.contact.emergency_contact_relationship == "MTH"
