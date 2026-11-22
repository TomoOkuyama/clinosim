"""The emergency contact has a sex, a specific relationship and name parts (Issue #3599)."""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.determinism import default_rng
from clinosim.locale.loader import load_demographics
from clinosim.modules.output.fhir_r4.demographics.related_person import _build_emergency_contact_related_person
from clinosim.modules.patient.activator import activate_patient
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_ROLES = {
    "parent": {"M": "FTH", "F": "MTH"},
    "sibling": {"M": "BRO", "F": "SIS"},
    "child": {"M": "SON", "F": "DAU"},
    "spouse": {"M": "HUSB", "F": "WIFE"},
}


def _adult(i: int, sex: str, age: int) -> PersonRecord:
    return PersonRecord(
        person_id=f"POP-{i:06d}",
        household_id=f"HH-{i}",
        age=age,
        sex=sex,
        date_of_birth=date(2026 - age, 3, 14),
        family_name="Tanaka",
        given_name="Hiroshi",
        phone_home="03-1234-5678",
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_contact_has_sex_specific_role_and_name_parts(country: str) -> None:
    demo = load_demographics(country)
    seen: set[str] = set()
    for i in range(300):
        person = _adult(i, "M" if i % 2 else "F", 30 + i % 55)
        c = activate_patient(person, default_rng(i), demo).contact
        if not c.emergency_contact_relationship:
            continue
        assert c.emergency_contact_sex in ("M", "F")
        assert c.emergency_contact_role == _ROLES[c.emergency_contact_relationship][c.emergency_contact_sex]
        assert c.emergency_contact_family_name and c.emergency_contact_given_name
        assert c.emergency_contact_family_name in c.emergency_contact_name
        assert c.emergency_contact_given_name in c.emergency_contact_name
        if c.emergency_contact_relationship == "spouse":
            assert c.emergency_contact_sex != person.sex
        seen.add(c.emergency_contact_role)
    assert {"FTH", "MTH", "BRO", "SIS", "SON", "DAU"} <= seen
    assert seen & {"HUSB", "WIFE"}


def test_related_person_emits_gender_role_and_name_parts() -> None:
    p = {
        "patient_id": "POP-1",
        "contact": {
            "emergency_contact_name": "花子 山田",
            "emergency_contact_phone": "090",
            "emergency_contact_relationship": "child",
            "emergency_contact_sex": "F",
            "emergency_contact_role": "DAU",
            "emergency_contact_family_name": "山田",
            "emergency_contact_given_name": "花子",
        },
    }
    rp = _build_emergency_contact_related_person(p, "JP")
    assert rp is not None
    assert rp["gender"] == "female"
    assert rp["relationship"][1]["coding"][0]["code"] == "DAU"
    assert rp["name"] == [{"text": "花子 山田", "family": "山田", "given": ["花子"]}]


def test_newborn_guardian_is_the_mother() -> None:
    from clinosim.simulator.perinatal import _newborn_contact_from_mother
    from clinosim.types.patient import ContactInfo

    class _Mother:
        name = type("N", (), {"family_name": "Smith", "given_name": "Karen", "phonetic": None})()
        contact = ContactInfo(phone_mobile="555-0100")

    c = _newborn_contact_from_mother(_Mother(), "US")  # type: ignore[arg-type]
    assert (c.emergency_contact_sex, c.emergency_contact_role) == ("F", "MTH")
    assert (c.emergency_contact_family_name, c.emergency_contact_given_name) == ("Smith", "Karen")
