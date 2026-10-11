"""Newborn → PersonRecord registration — Issue #1564 Phase 1 scaffold.

Covers `clinosim.modules.population.newborn.register_newborn` and the
new `PopulationRegistry.initial_person_ids` snapshot that distinguishes
mid-simulation additions (newborns) from the initial cohort.

Scope: this scaffold does NOT yet activate pediatric calendar visits
for the registered newborn — those come in a follow-up PR. The tests
below only cover the registration itself.
"""

from __future__ import annotations

from datetime import date

from clinosim.modules.population.engine import Household, PopulationRegistry
from clinosim.modules.population.newborn import newborn_sub_seed, register_newborn
from clinosim.types.patient import (
    Address,
    ChronicCondition,
    ContactInfo,
    PatientProfile,
    PersonName,
)
from clinosim.types.population import PersonRecord


def _mother(hh_id: str = "HH-1") -> PersonRecord:
    return PersonRecord(
        person_id="PT-MOM-001",
        household_id=hh_id,
        age=32,
        sex="F",
        date_of_birth=date(1994, 3, 15),
        family_name="Yamada",
        given_name="Hanako",
        postal_code="100-0001",
        state="Tokyo",
        city="Chiyoda",
        address_line="1-1-1 Nagatacho",
        phone_home="03-1234-5678",
    )


def _registry_with_mother(mother: PersonRecord) -> PopulationRegistry:
    hh = Household(household_id=mother.household_id, members=[mother])
    reg = PopulationRegistry(
        households=[hh],
        persons={mother.person_id: mother},
    )
    # Simulate what `generate_initial_population` does at its tail.
    reg.initial_person_ids = set(reg.persons.keys())
    return reg


def _newborn_profile(mother: PersonRecord, pid: str = "PT-MOM-001-BABY-01") -> PatientProfile:
    return PatientProfile(
        patient_id=pid,
        household_id=mother.household_id,
        name=PersonName(family_name=mother.family_name, given_name=""),
        age=0,
        sex="M",
        date_of_birth=date(2026, 5, 20),
        height_cm=50.0,
        weight_kg=3.2,
        bmi=12.8,
        address=Address(
            postal_code=mother.postal_code,
            state=mother.state,
            city=mother.city,
            line1=mother.address_line,
            country="JP",
        ),
        contact=ContactInfo(phone_home=mother.phone_home),
        blood_type="A",
        rh_factor="+",
        occupation="infant",
        chronic_conditions=[],
    )


def test_register_newborn_inserts_into_registry_persons() -> None:
    mother = _mother()
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    record = register_newborn(reg, mother, newborn)

    assert record.person_id == newborn.patient_id
    assert reg.persons[newborn.patient_id] is record
    assert record.age == 0
    assert record.date_of_birth == date(2026, 5, 20)


def test_register_newborn_joins_mother_household() -> None:
    mother = _mother()
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    record = register_newborn(reg, mother, newborn)

    assert record.household_id == mother.household_id
    # Mother + newborn now in the household
    hh = reg.households[0]
    assert mother in hh.members
    assert record in hh.members


def test_register_newborn_is_idempotent() -> None:
    mother = _mother()
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    first = register_newborn(reg, mother, newborn)
    second = register_newborn(reg, mother, newborn)

    assert first is second
    # Household still has exactly one entry for the newborn.
    hh = reg.households[0]
    assert sum(1 for m in hh.members if m.person_id == newborn.patient_id) == 1


def test_register_newborn_not_in_initial_person_ids() -> None:
    """Newborns must stay outside `initial_person_ids` so downstream
    iteration can treat them as a separate RNG stream."""
    mother = _mother()
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    register_newborn(reg, mother, newborn)

    assert mother.person_id in reg.initial_person_ids
    assert newborn.patient_id not in reg.initial_person_ids


def test_register_newborn_without_matching_household_still_registers() -> None:
    """Household resolution failure must not block registry insertion."""
    mother = _mother(hh_id="HH-ORPHANED")
    # Registry has mother in persons but no matching Household.
    reg = PopulationRegistry(persons={mother.person_id: mother})
    reg.initial_person_ids = set(reg.persons.keys())
    newborn = _newborn_profile(mother)

    record = register_newborn(reg, mother, newborn)

    assert record.person_id in reg.persons
    # No household entries exist to join; must not raise.
    assert reg.households == []


def test_register_newborn_carries_perinatal_conditions() -> None:
    mother = _mother()
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)
    newborn.chronic_conditions = [
        ChronicCondition(code="P59.9", system="icd-10-cm", severity="mild"),
    ]

    record = register_newborn(reg, mother, newborn)

    assert record.chronic_conditions == ["P59.9"]


def test_newborn_sub_seed_is_deterministic() -> None:
    assert newborn_sub_seed("PT-X-BABY-01") == newborn_sub_seed("PT-X-BABY-01")
    # Different ids produce different seeds (collision would be a surprise).
    assert newborn_sub_seed("PT-X-BABY-01") != newborn_sub_seed("PT-X-BABY-02")


def test_initial_person_ids_snapshot_default_empty() -> None:
    """A freshly-constructed registry has an empty snapshot — the
    population generator fills it in at the end of initial sampling."""
    reg = PopulationRegistry()
    assert reg.initial_person_ids == set()
    assert "PT-ANY" not in reg.initial_person_ids
