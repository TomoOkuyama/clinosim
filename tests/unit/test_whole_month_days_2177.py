"""Event days cover the whole month, not days 1-27 (Issue #2177)."""

from __future__ import annotations

from collections import Counter
from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules._shared import random_day_of_month

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("year", "month", "last"), [(2024, 2, 29), (2025, 2, 28), (2025, 4, 30), (2025, 12, 31)])
def test_random_day_of_month_covers_every_day(year: int, month: int, last: int) -> None:
    rng = np.random.default_rng(0)
    days = {random_day_of_month(rng, year, month) for _ in range(3000)}
    assert days == set(range(1, last + 1))


def test_pediatric_visits_can_fall_after_the_27th() -> None:
    from clinosim.modules.pediatric.calendar import generate_pediatric_events

    days: Counter[int] = Counter()
    for i in range(400):
        person = SimpleNamespace(person_id=f"P{i}", age=0, date_of_birth=date(2025, 1, 1), care_seeking_threshold=0.0)
        for ev in generate_pediatric_events(person, 2025, np.random.default_rng(i)):
            days[ev.timestamp.day] += 1
    assert sum(days[d] for d in (28, 29, 30, 31)) > 0


def test_monthly_life_events_stay_in_their_month_and_reach_its_end() -> None:
    from clinosim.modules.population.engine import generate_monthly_events, generate_population

    reg = generate_population(3000, "US", np.random.default_rng(1))
    days = Counter()
    for month in (1, 3):
        for ev in generate_monthly_events(reg, 2025, month, np.random.default_rng(month), country="US", master_seed=1):
            assert (ev.timestamp.year, ev.timestamp.month) == (2025, month)
            days[ev.timestamp.day] += 1
    assert days[29] + days[30] + days[31] > 0
