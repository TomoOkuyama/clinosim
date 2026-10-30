"""``PersonRecord.is_alive_at(t)`` (Issue #1114 C11g-2).

None death → always alive; a recorded death → alive strictly before it.
The pre-sampling enricher these tests used to cover was replaced by the
forward annual draw (Issue #2167, ``tests/unit/test_forward_mortality_2167.py``).
"""

from __future__ import annotations

from datetime import date

import pytest

from clinosim.types.population import PersonRecord


@pytest.mark.unit
class TestIsAliveAt:
    def _person(self, dod: date | None) -> PersonRecord:
        return PersonRecord(
            person_id="p1",
            household_id="h1",
            age=40,
            sex="M",
            date_of_birth=date(1985, 6, 15),
            date_of_death=dod,
        )

    def test_no_death_is_always_alive(self):
        # "Always alive" within the person's lifetime (date_of_birth onward)
        # when no death date is set. The pre-birth guard added in
        # Issue #1564 Phase 1 follow-up means a date before `date_of_birth`
        # is not alive; this test covers the live-window behaviour only.
        p = self._person(None)
        assert p.is_alive_at(date(1985, 6, 15)) is True  # birth day itself
        assert p.is_alive_at(date(2050, 12, 31)) is True

    def test_alive_strictly_before_death(self):
        p = self._person(date(2025, 6, 15))
        assert p.is_alive_at(date(2025, 6, 14)) is True

    def test_dead_on_death_date(self):
        p = self._person(date(2025, 6, 15))
        # Day-of-death: person is considered not-alive (matches actuarial convention).
        assert p.is_alive_at(date(2025, 6, 15)) is False

    def test_dead_after_death_date(self):
        p = self._person(date(2025, 6, 15))
        assert p.is_alive_at(date(2025, 6, 16)) is False
        assert p.is_alive_at(date(2030, 1, 1)) is False
