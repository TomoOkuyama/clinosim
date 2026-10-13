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
from clinosim.modules.population.newborn import register_newborn
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


def test_register_newborn_without_config_leaves_biology_fields_at_defaults() -> None:
    """Phase 1 contract preserved — callers that build a PatientProfile
    without a sim config (test fixtures) still get a valid PersonRecord
    whose biology fields are at their dataclass defaults. The Phase A
    biology init runs only when ``config`` is supplied."""
    mother = _mother()
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    record = register_newborn(reg, mother, newborn)

    # No config → no biology init → fields stay at dataclass defaults.
    assert record.allergies is None
    assert record.date_of_death is None


def test_register_newborn_with_config_attaches_nka_allergy_and_death_date() -> None:
    """Phase A (Issue #1581) biology init — a config-aware register
    call attaches the Phase-A invariants an age-0 initial-cohort citizen
    would have."""
    from types import SimpleNamespace

    mother = _mother()
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    config = SimpleNamespace(
        country="JP",
        random_seed=42,
        time_range=(date(2026, 1, 1), date(2036, 1, 1)),
        snapshot_date=None,
    )
    record = register_newborn(reg, mother, newborn, config=config)

    # NKA baseline allergy is non-None (every PERSON must have ≥1 allergy
    # record; NKA is the positive assertion). ``is_nka`` flag + SNOMED
    # 716186003 are the invariants the allergy enricher ships for initial-
    # cohort persons too.
    assert record.allergies is not None
    assert len(record.allergies) == 1
    assert record.allergies[0].is_nka is True
    # date_of_death is pre-sampled (may or may not fire in the window
    # depending on the per-person RNG draw; we only assert that the
    # biology init ran, not that this specific newborn dies). Either
    # way the attribute has a type-stable value.
    assert record.date_of_death is None or isinstance(record.date_of_death, date)
    # care_seeking_threshold is sampled from the locale pediatric band
    # (JP yaml: `age_conditional["0-14"] = 0.60`, sd 0.12, clamped to
    # the operational range). The important invariant is that the
    # threshold is NO LONGER the PersonRecord dataclass default of 0.3,
    # which is the adult-generator mean.
    assert record.care_seeking_threshold != 0.3
    # And it lands inside the operational clamp band.
    from clinosim.modules.population.engine import CARE_SEEKING_CLAMP_MAX, CARE_SEEKING_CLAMP_MIN

    assert CARE_SEEKING_CLAMP_MIN <= record.care_seeking_threshold <= CARE_SEEKING_CLAMP_MAX


def test_newborn_atopic_predisposition_default_non_atopic_mother() -> None:
    """Issue #1581 Phase C.2 — a non-atopic mother (no allergies, or
    only NKA / resolved records) produces a newborn with
    ``atopic_predisposition == 1.0`` (clinically neutral, equivalent
    to initial-cohort citizens)."""
    from clinosim.types.allergy import Allergy

    mother = _mother()
    # Mother with NKA only — not atopic.
    mother.allergies = [
        Allergy(
            allergy_id="ALG-NKA",
            allergen_code="716186003",
            category="",
            criticality="unable-to-assess",
            verification_status="confirmed",
            clinical_status="resolved",
            is_nka=True,
        )
    ]
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    record = register_newborn(reg, mother, newborn)
    assert record.atopic_predisposition == 1.0


def test_newborn_atopic_predisposition_raised_for_atopic_mother() -> None:
    """A mother with any real (non-NKA, non-resolved) allergy produces a
    newborn with ``atopic_predisposition == 2.0`` (single-atopic-parent
    OR per Bousquet 2008 Allergy)."""
    from clinosim.types.allergy import Allergy

    mother = _mother()
    mother.allergies = [
        Allergy(
            allergy_id="ALG-EGG",
            allergen_code="735038006",
            category="food",
            criticality="low",
            verification_status="confirmed",
            clinical_status="active",
        )
    ]
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    record = register_newborn(reg, mother, newborn)
    assert record.atopic_predisposition == 2.0


def test_newborn_atopic_predisposition_ignores_resolved_allergy() -> None:
    """A mother whose only allergy record has clinical_status=resolved
    (childhood food allergy that was outgrown) is not atopic. Multiplier
    stays at 1.0."""
    from clinosim.types.allergy import Allergy

    mother = _mother()
    mother.allergies = [
        Allergy(
            allergy_id="ALG-EGG-RESOLVED",
            allergen_code="735038006",
            category="food",
            criticality="low",
            verification_status="confirmed",
            clinical_status="resolved",
        )
    ]
    reg = _registry_with_mother(mother)
    newborn = _newborn_profile(mother)

    record = register_newborn(reg, mother, newborn)
    assert record.atopic_predisposition == 1.0


def test_register_newborn_with_config_is_deterministic() -> None:
    """Phase A biology init is driven by sub-seeds derived from the
    person_id, so two registrations of the same newborn (across runs
    with the same master seed) produce the same death-date decision."""
    from types import SimpleNamespace

    def _run() -> tuple[bool, object]:
        mother = _mother()
        reg = _registry_with_mother(mother)
        newborn = _newborn_profile(mother)
        config = SimpleNamespace(
            country="JP",
            random_seed=42,
            time_range=(date(2026, 1, 1), date(2036, 1, 1)),
            snapshot_date=None,
        )
        rec = register_newborn(reg, mother, newborn, config=config)
        return rec.allergies is not None, rec.date_of_death

    first = _run()
    second = _run()
    assert first == second


def test_initial_person_ids_snapshot_default_empty() -> None:
    """A freshly-constructed registry has an empty snapshot — the
    population generator fills it in at the end of initial sampling."""
    reg = PopulationRegistry()
    assert reg.initial_person_ids == set()
    assert "PT-ANY" not in reg.initial_person_ids
