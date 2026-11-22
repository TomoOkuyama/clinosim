"""The 1-month check of the pediatric calendar (Issue #3566)."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.pediatric.calendar import generate_pediatric_events, load_pediatric_schedule

pytestmark = pytest.mark.unit

_KEY = "pediatric:well_child_one_month"


def _baby(dob: date, pid: str = "p", threshold: float = 0.0) -> SimpleNamespace:
    return SimpleNamespace(person_id=pid, age=0, date_of_birth=dob, care_seeking_threshold=threshold)


def _all_events(baby: SimpleNamespace, schedule: dict | None = None) -> list:
    dob = baby.date_of_birth
    out: list = []
    for year in (dob.year, dob.year + 1):
        out += generate_pediatric_events(baby, year, np.random.default_rng(7), schedule, country="US")
    return out


def _dobs() -> list[date]:
    return [date(2025, 1, 1) + timedelta(days=d) for d in range(0, 365, 7)]


def test_every_attending_newborn_has_one_visit_between_day_21_and_45() -> None:
    for dob in _dobs():
        visits = [e for e in _all_events(_baby(dob)) if e.protocol_source == _KEY]
        assert len(visits) == 1, dob
        assert 21 <= (visits[0].timestamp - dob).days <= 45
        assert visits[0].disease_id == "well_child_infant"


def test_visit_day_spreads_over_the_window() -> None:
    days = {
        (e.timestamp - _dobs()[0]).days
        for i in range(200)
        for e in _all_events(_baby(_dobs()[0], pid=f"p{i}"))
        if e.protocol_source == _KEY
    }
    assert len(days) > 15 and min(days) >= 21 and max(days) <= 45


def test_attendance_follows_the_care_seeking_threshold() -> None:
    n = 400
    kept = sum(
        any(e.protocol_source == _KEY for e in _all_events(_baby(date(2025, 3, 1), pid=f"q{i}", threshold=0.3)))
        for i in range(n)
    )
    assert 0.6 * n < kept < 0.8 * n


def test_other_visits_are_unchanged_by_the_entry() -> None:
    full = load_pediatric_schedule()
    without = {k: v for k, v in full.items() if k != "well_child_one_month"}
    for dob in _dobs():
        baby = _baby(dob, threshold=0.2)
        a = [(e.disease_id, e.timestamp) for e in _all_events(baby, full) if e.protocol_source != _KEY]
        b = [(e.disease_id, e.timestamp) for e in _all_events(baby, without)]
        assert a == b


def test_the_one_month_visit_carries_its_own_label() -> None:
    from clinosim.simulator._setup import _pediatric_visit_reason

    one = _pediatric_visit_reason("well_child_infant", "well_child_one_month")
    routine = _pediatric_visit_reason("well_child_infant", "well_child_infant")
    assert one["ja"] == "1か月健診" and "1-month" in one["en"]
    assert routine["ja"] == "乳児健診"
    assert _pediatric_visit_reason("well_child_infant") == routine


def test_a_fixed_age_entry_cannot_be_a_vaccination_visit() -> None:
    from pydantic import ValidationError

    from clinosim.modules.pediatric.calendar import _Visit

    base = {"age_min": 0, "age_max": 1, "visits_per_year": [1], "encounter_type": "outpatient", "disease_id": "x"}
    _Visit.model_validate({**base, "fixed_age_days": {"min": 21, "max": 45}})
    with pytest.raises(ValidationError):
        _Visit.model_validate({**base, "fixed_age_days": {"min": 21, "max": 45}, "vaccination": True})
    with pytest.raises(ValidationError):
        _Visit.model_validate({**base, "fixed_age_days": {"min": 50, "max": 45}})
