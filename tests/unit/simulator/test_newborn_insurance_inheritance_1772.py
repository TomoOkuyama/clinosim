"""Issue #1772: US-cohort newborns inherit JP `NHI_employee` insurance.

The audit at p=10000 5y US cohort found **392 / 489 `-BABY` patients
(80%)** had `insurance_type = "NHI_employee"` even though their
mothers carried US insurance types (`private_employer`, `medicaid`,
`uninsured`, …).

Root cause: the `PatientProfile` dataclass defaults
`insurance_type` to the JP sentinel `"NHI_employee"`. `_build_newborn_patient`
in `clinosim/simulator/perinatal.py` never set the field, so every
newborn inherited the dataclass default. The locale-separation
contract (US / JP cohorts should never share insurance strings) was
violated.

Fix: forward `mother.insurance_type` on construction, same pattern
as the race / ethnicity inheritance in #1751.
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.simulator.perinatal import _build_newborn_patient
from clinosim.types.patient import PatientProfile, PersonName


def _mother(insurance_type: str = "private_employer") -> PatientProfile:
    return PatientProfile(
        patient_id="POP-000001",
        name=PersonName(family_name="Doe", given_name="Jane"),
        sex="F",
        age=30,
        date_of_birth="1996-01-01",
        race="white",
        ethnicity="not_hispanic",
        insurance_type=insurance_type,
        preferred_language="en-US",
    )


@pytest.mark.parametrize(
    "insurance_type",
    [
        "private_employer",
        "medicaid",
        "medicaid_chip",
        "medicare",
        "medicare_plus_private",
        "uninsured",
        "self_pay",
        "NHI_employee",  # JP cohort
        "NHI_national",  # JP cohort
    ],
)
def test_newborn_inherits_insurance_type(insurance_type: str) -> None:
    """Every newborn must carry the mother's `insurance_type` verbatim —
    locale-agnostic — so US-cohort babies don't fall through to the
    JP dataclass default (Issue #1772)."""
    mother = _mother(insurance_type=insurance_type)
    newborn = _build_newborn_patient(
        mother=mother,
        delivery_date=date(2024, 6, 15),
        sex="M",
        country="US" if insurance_type.startswith(("private", "medic", "self", "uninsur")) else "JP",
    )
    assert newborn.insurance_type == insurance_type, (
        f"Newborn insurance_type {newborn.insurance_type!r} does not match "
        f"mother {insurance_type!r} — Issue #1772 regression"
    )


def test_newborn_insurance_does_not_fall_back_to_jp_default() -> None:
    """A US mother with `insurance_type = 'private_employer'` must NOT
    produce a baby with `insurance_type = 'NHI_employee'` — the JP
    dataclass default must not leak into the US cohort."""
    mother = _mother(insurance_type="private_employer")
    newborn = _build_newborn_patient(
        mother=mother,
        delivery_date=date(2024, 6, 15),
        sex="F",
        country="US",
    )
    assert newborn.insurance_type != "NHI_employee"
    assert newborn.insurance_type == "private_employer"
