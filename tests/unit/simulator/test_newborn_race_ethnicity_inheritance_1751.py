"""Issue #1751: newborn PatientProfile does not inherit race / ethnicity
from mother on `_build_newborn_patient`.

PR #1588 added mother→baby race / ethnicity inheritance to `PersonRecord`,
but `clinosim/simulator/perinatal.py::_build_newborn_patient` constructs
the baby's `PatientProfile` without forwarding those two fields. The
PatientProfile dataclass defaults both to `""`, so the delivery-day
encounter's Patient resource emits with empty race / ethnicity — 80%
of newborns in a p=10000 5y US cohort audit.

Fix: forward `race` + `ethnicity` from the mother on construction.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.simulator.perinatal import _build_newborn_patient
from clinosim.types.patient import PatientProfile, PersonName


def _mother(race: str = "white", ethnicity: str = "not_hispanic") -> PatientProfile:
    """Build a minimal mother PatientProfile with the given race / ethnicity."""
    return PatientProfile(
        patient_id="POP-000001",
        name=PersonName(family_name="Doe", given_name="Jane"),
        sex="F",
        age=30,
        date_of_birth="1996-01-01",
        race=race,
        ethnicity=ethnicity,
        preferred_language="en-US",
    )


@pytest.mark.parametrize(
    "race,ethnicity",
    [
        ("white", "not_hispanic"),
        ("black", "not_hispanic"),
        ("asian", "not_hispanic"),
        ("other", "hispanic"),
        ("native_american", "not_hispanic"),
    ],
)
def test_newborn_inherits_race_and_ethnicity(race: str, ethnicity: str) -> None:
    """Every newborn's PatientProfile must carry the mother's race +
    ethnicity so the US-Core-conformant Patient resource emits the
    `us-core-race` / `us-core-ethnicity` extensions on the delivery
    encounter (Issue #1751)."""
    mother = _mother(race=race, ethnicity=ethnicity)
    newborn = _build_newborn_patient(
        mother=mother,
        delivery_date=date(2024, 6, 15),
        sex="M",
        country="US",
    )
    assert newborn.race == race, f"newborn race {newborn.race!r} does not match mother {race!r}"
    assert newborn.ethnicity == ethnicity, (
        f"newborn ethnicity {newborn.ethnicity!r} does not match mother {ethnicity!r}"
    )


def test_newborn_empty_race_mother_yields_empty_race_baby() -> None:
    """If the mother has no race assigned (e.g. a non-US cohort or an
    older PersonRecord pre-#1588), the baby stays empty rather than
    picking a fabricated default. Fabrication would violate the
    `feedback_empty_vs_wrong_assertion` rule."""
    mother = _mother(race="", ethnicity="")
    newborn = _build_newborn_patient(
        mother=mother,
        delivery_date=date(2024, 6, 15),
        sex="F",
        country="US",
    )
    assert newborn.race == ""
    assert newborn.ethnicity == ""
