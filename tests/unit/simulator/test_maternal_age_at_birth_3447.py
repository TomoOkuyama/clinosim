"""The newborn's recorded maternal age is the mother's age on the birth date (Issue #3447)."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.simulator.perinatal import _birth_data


class _Mother:
    def __init__(self, dob: date | None, stored_age: int) -> None:
        self.date_of_birth = dob
        self.age = stored_age
        self.chronic_conditions: list = []
        self.state_periods: list = []


@pytest.mark.unit
def test_maternal_age_uses_age_at_delivery_not_stored_age():
    mother = _Mother(date(1997, 3, 5), 27)
    data = _birth_data(mother, datetime(2026, 5, 22, 10, 0), False)
    assert data["maternal_age"] == 29


@pytest.mark.unit
def test_maternal_age_birthday_boundary():
    mother = _Mother(date(1997, 5, 23), 28)
    assert _birth_data(mother, datetime(2026, 5, 22, 23, 0), False)["maternal_age"] == 28
    assert _birth_data(mother, datetime(2026, 5, 23, 1, 0), False)["maternal_age"] == 29


@pytest.mark.unit
def test_maternal_age_falls_back_to_stored_age_without_dob():
    mother = _Mother(None, 31)
    assert _birth_data(mother, datetime(2026, 5, 22), True)["maternal_age"] == 31
