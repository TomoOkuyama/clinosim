"""Screening and vaccination do not require a chronic follow-up condition (Issue #2195)."""

from __future__ import annotations

from collections import Counter
from datetime import date

import numpy as np
import pytest

from clinosim.modules.population.engine import PopulationRegistry, generate_healthcare_calendar
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _calendar(age: int, sex: str, n: int = 200) -> Counter:
    reg = PopulationRegistry()
    for i in range(n):
        p = PersonRecord(
            person_id=f"POP-{i:06d}",
            household_id="HH-000001",
            age=age,
            sex=sex,
            date_of_birth=date(2024 - age, 1, 1),
            chronic_conditions=[],
        )
        reg.persons[p.person_id] = p
    events = generate_healthcare_calendar(reg, year=2024, country="US", rng=np.random.default_rng(7))
    return Counter(e.disease_id for e in events)


def test_healthy_55_year_olds_get_screening_and_colonoscopy() -> None:
    counts = _calendar(55, "F")
    assert counts["annual_health_screening"] > 0
    assert counts["colonoscopy_screening"] > 0
    assert counts["mammography_screening"] > 0


def test_healthy_70_year_olds_get_flu_vaccination() -> None:
    assert _calendar(70, "M")["flu_vaccination"] > 0


def test_healthy_people_get_no_chronic_visits_or_retinopathy_screening() -> None:
    counts = _calendar(55, "M")
    assert counts["diabetic_retinopathy_screening"] == 0
    assert not any(k and k[0].isupper() and k[1:3].isdigit() for k in counts)  # no ICD-keyed chronic visits
