"""A child under 9 gets two first-season flu doses (Issue #3684)."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.locale.clinic_calendar import is_clinic_day
from clinosim.modules.immunization.engine import (
    add_first_season_flu_doses,
    dose_intervals_by_cvx,
    flu_season_of,
    generate_immunizations_for_country,
    load_schedule,
)
from clinosim.modules.immunization.enricher import _align_to_encounters
from clinosim.modules.immunization.visits import flu_season_months
from clinosim.types.encounter import ImmunizationRecord

pytestmark = pytest.mark.unit

_AS_OF = date(2026, 11, 22)
_FLU = {"158", "141"}


def _child(i: int, dob: date) -> SimpleNamespace:
    age = _AS_OF.year - dob.year - ((_AS_OF.month, _AS_OF.day) < (dob.month, dob.day))
    return SimpleNamespace(patient_id=f"POP-{i:06d}", date_of_birth=dob, age=age, sex="F")


def _flu(recs: list) -> list:
    return sorted(
        (r for r in recs if r.vaccine_cvx in _FLU and r.status == "completed"), key=lambda r: r.occurrence_date
    )


def _doses(i: int, dob: date, country: str = "US") -> list:
    patient = _child(i, dob)
    schedule = load_schedule("US")
    recs = generate_immunizations_for_country(country, patient, schedule, _AS_OF, np.random.default_rng(i))
    recs = add_first_season_flu_doses(recs, patient, schedule, _AS_OF, country)
    return _flu(recs)


def test_three_year_old_with_no_prior_dose_gets_two_doses_in_the_first_season() -> None:
    checked = 0
    for i in range(300):
        doses = _doses(i, date(2023, 6, 15))
        if not doses:
            continue
        first_season = [d for d in doses if flu_season_of(d.occurrence_date) == flu_season_of(doses[0].occurrence_date)]
        # a second dose may be missing only when no clinic day of the season is left before the as-of date
        if len(first_season) == 1:
            assert flu_season_of(doses[0].occurrence_date) == flu_season_of(_AS_OF)
            continue
        assert len(first_season) == 2
        a, b = first_season
        assert (b.occurrence_date - a.occurrence_date).days >= 28
        assert (a.dose_number, b.dose_number) == (1, 2)
        assert is_clinic_day(b.occurrence_date, "US") and b.occurrence_date <= _AS_OF
        assert b.lot_number
        checked += 1
    assert checked > 50


def test_later_seasons_are_single_doses() -> None:
    for i in range(100):
        doses = _doses(i, date(2022, 6, 15))
        later = [d for d in doses if flu_season_of(d.occurrence_date) != flu_season_of(doses[0].occurrence_date)]
        assert all(d.dose_number is None for d in later)


def test_nine_year_old_gets_one_dose_per_season() -> None:
    for i in range(100):
        doses = _doses(i, date(2017, 3, 1))
        seasons = [flu_season_of(d.occurrence_date) for d in doses]
        assert len(seasons) == len(set(seasons))
        assert all(d.dose_number is None for d in doses)


def test_child_whose_first_season_is_outside_the_retained_history_is_left_alone() -> None:
    """An 8-year-old's first season is beyond the 5-year retention window: earlier doses are unknown."""
    for i in range(100):
        doses = _doses(i, date(2018, 6, 15))
        seasons = [flu_season_of(d.occurrence_date) for d in doses]
        assert len(seasons) == len(set(seasons))


def test_a_child_with_two_doses_already_gets_no_extra_one() -> None:
    schedule = load_schedule("US")
    patient = _child(1, date(2023, 6, 15))
    recs = [
        ImmunizationRecord(vaccine_cvx="158", occurrence_date=date(2025, 10, 1), dose_number=1),
        ImmunizationRecord(vaccine_cvx="158", occurrence_date=date(2025, 11, 5), dose_number=2),
    ]
    assert len(_flu(add_first_season_flu_doses(recs, patient, schedule, _AS_OF, "US"))) == 2


def test_the_interval_survives_snapping_to_visits() -> None:
    schedule = load_schedule("US")
    intervals = dose_intervals_by_cvx(schedule)
    assert intervals["158"][2].min_days == 28
    first = ImmunizationRecord(vaccine_cvx="158", occurrence_date=date(2025, 10, 1), dose_number=1)
    second = ImmunizationRecord(vaccine_cvx="158", occurrence_date=date(2025, 11, 5), dose_number=2)
    visits = [
        SimpleNamespace(encounter_id="E1", admission_datetime=datetime(2025, 10, 20, 10), encounter_type="outpatient"),
        SimpleNamespace(encounter_id="E2", admission_datetime=datetime(2025, 11, 2, 10), encounter_type="outpatient"),
    ]
    out = _align_to_encounters(
        [first, second],
        visits,
        flu_season_months(schedule),
        None,
        intervals,
        None,
        date(2023, 6, 15),
        None,
    )
    assert (out[1].occurrence_date - out[0].occurrence_date).days >= 28 or out[1].encounter_id == ""


def test_japan_schedule_is_unchanged() -> None:
    schedule = load_schedule("JP")
    patient = _child(1, date(2023, 6, 15))
    recs = [ImmunizationRecord(vaccine_cvx="150", occurrence_date=date(2025, 10, 1))]
    assert add_first_season_flu_doses(recs, patient, schedule, _AS_OF, "JP") == recs
