"""Carvedilol is prescribed in a strength each country has (Issue #2612)."""

from __future__ import annotations

import pytest

from clinosim.modules.patient.activator import _derive_home_medications
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit


def _carvedilol_doses(country: str) -> set[str]:
    doses: set[str] = set()
    for i in range(40):
        meds = _derive_home_medications(
            [ChronicCondition(code="I50", system="icd-10-cm")], country=country, patient_id=f"pt-hf-{i}"
        )
        doses |= {m.dose for m in meds if (m.drug_name or "").lower() == "carvedilol"}
    return doses


@pytest.mark.parametrize(("country", "dose"), [("US", "3.125mg"), ("JP", "2.5mg")])
def test_heart_failure_carvedilol_strength(country: str, dose: str) -> None:
    assert _carvedilol_doses(country) == {dose}


def test_the_same_patients_get_carvedilol_in_both_countries() -> None:
    """One entry per country: the draw that picks carvedilol is unchanged."""

    def picked(country: str) -> list[bool]:
        return [
            any(
                (m.drug_name or "").lower() == "carvedilol"
                for m in _derive_home_medications(
                    [ChronicCondition(code="I50", system="icd-10-cm")], country=country, patient_id=f"pt-hf-{i}"
                )
            )
            for i in range(40)
        ]

    assert picked("US") == picked("JP")
