"""Screening participation and flu vaccination come from the locale config (Issue #2245)."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.population.engine import PopulationRegistry, generate_healthcare_calendar
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _coverage(country: str, age: int, disease_id: str, n: int = 2000) -> float:
    reg = PopulationRegistry()
    for i in range(n):
        p = PersonRecord(
            person_id=f"POP-{i:06d}",
            household_id="HH-000001",
            age=age,
            sex="M",
            date_of_birth=date(2025 - age, 1, 1),
            chronic_conditions=[],
        )
        reg.persons[p.person_id] = p
    events = generate_healthcare_calendar(reg, year=2025, country=country, rng=np.random.default_rng(7))
    return len({e.person_id for e in events if e.disease_id == disease_id}) / n


def test_jp_screening_participation_matches_tokutei_kenshin() -> None:
    assert _coverage("JP", 55, "annual_health_screening") == pytest.approx(0.581, abs=0.03)


def test_us_flu_vaccination_65_plus_matches_nhis() -> None:
    assert _coverage("US", 70, "flu_vaccination") == pytest.approx(0.671, abs=0.03)


def test_unconfigured_screening_participation_keeps_everyone() -> None:
    assert _coverage("US", 55, "annual_health_screening") == 1.0
