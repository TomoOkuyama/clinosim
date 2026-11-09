"""Pediatric vaccination visits fall on a day a dose is due (Issue #2974).

A standalone immunization visit (``vaccination: true`` in
``pediatric_schedule.yaml``) is held inside a series dose window of the
country's immunization schedule that opens in the visit year, so the visit
binder (``immunization/visits.py``) always has a dose to give at it.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.immunization.engine import load_schedule
from clinosim.modules.pediatric.calendar import generate_pediatric_events, load_pediatric_schedule

pytestmark = pytest.mark.unit


def _person(dob: date) -> SimpleNamespace:
    return SimpleNamespace(person_id="P1", age=0, date_of_birth=dob, care_seeking_threshold=1e-9)


def _vaccination_ids() -> set[str]:
    return {e["disease_id"] for e in load_pediatric_schedule().values() if e.get("vaccination")}


def _windows(country: str, dob: date) -> list[tuple[date, date]]:
    return [
        (dob + timedelta(days=int(d["age_days_min"])), dob + timedelta(days=int(d["age_days_max"])))
        for v in load_schedule(country).values()
        if v.get("frequency") == "pediatric_series"
        for d in v.get("doses") or []
    ]


def _vaccination_events(country: str | None, dob: date, year: int, seed: int = 7) -> list:
    events = generate_pediatric_events(_person(dob), year, np.random.default_rng(seed), country=country)
    return [e for e in events if e.disease_id in _vaccination_ids()]


def test_the_three_immunization_visits_are_vaccination_visits() -> None:
    assert _vaccination_ids() == {"immunization_infant", "immunization_kindergarten", "immunization_adolescent"}


def test_adolescent_visit_waits_for_the_11_year_window() -> None:
    """Born 2015-08-15: the US adolescent doses open at ~11 y (2026-08), so the
    2026 visit is not held in June at 10 y 10 m."""
    dob = date(2015, 8, 15)
    events = _vaccination_events("US", dob, 2026)
    assert events
    for e in events:
        assert any(lo <= e.timestamp <= hi for lo, hi in _windows("US", dob))
        assert e.timestamp >= date(2026, 8, 1)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_vaccination_visit_is_inside_a_dose_window(country: str) -> None:
    for dob in [date(2008, 1, 1) + timedelta(days=37 * k) for k in range(180)]:
        for year in (2025, 2026):
            if year < dob.year:
                continue
            for e in _vaccination_events(country, dob, year, seed=dob.toordinal()):
                assert e.timestamp.year == year
                assert any(lo <= e.timestamp <= hi for lo, hi in _windows(country, dob)), (country, dob, e)


def test_no_visit_in_a_year_no_window_opens() -> None:
    """US kindergarten doses all open at 4 y: a child turning 5 in the year
    gets no kindergarten vaccination visit."""
    events = _vaccination_events("US", date(2021, 3, 1), 2026)
    assert not [e for e in events if e.disease_id == "immunization_kindergarten"]


def test_without_a_country_the_calendar_is_unchanged() -> None:
    dob = date(2015, 8, 15)
    events = _vaccination_events(None, dob, 2026)
    assert [e.timestamp.month for e in events] == [6]


def test_placement_draws_nothing() -> None:
    """The per-person stream ends in the same state with or without placement."""
    for dob in (date(2015, 8, 15), date(2021, 3, 1), date(2025, 11, 20)):
        a, b = np.random.default_rng(11), np.random.default_rng(11)
        generate_pediatric_events(_person(dob), 2026, a, country="US")
        generate_pediatric_events(_person(dob), 2026, b)
        assert a.random() == b.random()


@pytest.mark.parametrize("country", ["US", "JP"])
def test_two_visits_in_a_year_use_different_windows(country: str) -> None:
    """An infant's two catch-up visits in a year are held for different dose
    windows (by opening day), not both for the window that opens first, where
    the second visit would find every dose already given."""
    from itertools import permutations

    for dob in [date(2025, 8, 1) + timedelta(days=9 * k) for k in range(40)]:
        for seed in range(6):
            events = [e for e in _vaccination_events(country, dob, 2026, seed) if e.disease_id == "immunization_infant"]
            candidates = [
                {lo for lo, hi in _windows(country, dob) if lo.year == 2026 and lo <= e.timestamp <= hi} for e in events
            ]
            assert all(candidates)
            assert any(
                len(set(pick)) == len(pick)
                for pick in permutations([o for c in candidates for o in c], len(candidates))
                if all(p in c for p, c in zip(pick, candidates))
            ), (country, dob, seed, [e.timestamp for e in events])
