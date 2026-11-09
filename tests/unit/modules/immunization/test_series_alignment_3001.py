"""Issue #3001: aligning doses to nearby visits never puts two doses of one
series on one visit, and keeps each series' minimum interval between doses."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.immunization.engine import load_schedule, min_interval_days_by_cvx
from clinosim.modules.immunization.enricher import _align_to_encounters
from clinosim.types.encounter import ImmunizationRecord

pytestmark = pytest.mark.unit

_DTAP = "20"
_INTERVALS = {_DTAP: {2: (1, 28), 3: (2, 28), 4: (3, 182)}}  # dose -> (counted from dose, days)


def _enc(enc_id: str, day: date) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id=enc_id, admission_datetime=datetime(day.year, day.month, day.day, 10), encounter_type="outpatient"
    )


def _dose(n: int, day: date, cvx: str = _DTAP) -> ImmunizationRecord:
    return ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=day, dose_number=n)


def test_doses_1_and_2_near_one_visit_are_not_both_aligned_to_it() -> None:
    d1, d2 = _dose(1, date(2025, 3, 1)), _dose(2, date(2025, 5, 1))
    visit = _enc("enc-v", date(2025, 4, 1))
    _align_to_encounters([d1, d2], [visit], min_interval_by_cvx=_INTERVALS)
    assert d1.encounter_id == "enc-v" and d1.occurrence_date == date(2025, 4, 1)
    # Dose 2 may not join dose 1 there; with no other visit it keeps its own date.
    assert d2.encounter_id == "" and d2.occurrence_date == date(2025, 5, 1)


def test_one_dose_per_series_per_day_even_without_interval_data() -> None:
    d1, d2 = _dose(1, date(2025, 3, 1)), _dose(2, date(2025, 5, 1))
    _align_to_encounters([d1, d2], [_enc("enc-v", date(2025, 4, 1))])
    assert (d1.occurrence_date, d2.occurrence_date) != (date(2025, 4, 1), date(2025, 4, 1))


def test_a_dose_is_not_aligned_closer_than_the_minimum_interval() -> None:
    d1 = _dose(1, date(2025, 3, 1))
    d2 = _dose(2, date(2025, 4, 10))
    early = _enc("enc-early", date(2025, 3, 20))  # 19 days after dose 1 (< 28)
    later = _enc("enc-later", date(2025, 4, 30))  # 60 days after dose 1
    d1.encounter_id = "enc-bound"  # dose 1 already given at its own visit
    _align_to_encounters([d1, d2], [early, later], min_interval_by_cvx=_INTERVALS)
    assert d2.encounter_id == "enc-later"
    assert d2.occurrence_date == date(2025, 4, 30)


def test_a_dose_is_not_aligned_too_close_before_the_next_dose() -> None:
    d1 = _dose(1, date(2025, 3, 1))
    d2 = _dose(2, date(2025, 4, 10))
    d2.encounter_id = "enc-bound"
    _align_to_encounters([d1, d2], [_enc("enc-close", date(2025, 3, 25))], min_interval_by_cvx=_INTERVALS)
    assert d1.encounter_id == "" and d1.occurrence_date == date(2025, 3, 1)


def test_different_series_still_share_a_visit() -> None:
    dtap, hib = _dose(1, date(2025, 3, 1)), _dose(1, date(2025, 3, 3), cvx="17")
    _align_to_encounters([dtap, hib], [_enc("enc-v", date(2025, 3, 2))], min_interval_by_cvx=_INTERVALS)
    assert dtap.encounter_id == hib.encounter_id == "enc-v"


@pytest.mark.parametrize("country", ["US", "JP"])
def test_every_later_dose_of_a_pediatric_series_has_a_minimum_interval(country: str) -> None:
    schedule = load_schedule(country)
    intervals = min_interval_days_by_cvx(schedule)
    for name, vaccine in schedule.items():
        if vaccine.get("frequency") != "pediatric_series":
            continue
        for dose in vaccine["doses"][1:]:
            assert int(dose["min_interval_days"]) > 0, (name, dose["dose_number"])
            number = int(dose["dose_number"])
            ref = int(dose.get("min_interval_after_dose", number - 1))
            assert 1 <= ref < number, (name, number)
            assert intervals[str(vaccine["cvx"])][number] == (ref, int(dose["min_interval_days"]))


def test_jp_hepatitis_b_dose_3_counts_from_dose_1() -> None:
    assert min_interval_days_by_cvx(load_schedule("JP"))["08"][3] == (1, 139)


def test_a_series_clamped_to_the_vaccine_start_keeps_its_doses_apart() -> None:
    """HPV (available from 2015-01-01) for a child whose two dose windows
    both closed before then: the clamp to the availability date put both
    doses on 2015-01-01."""
    import numpy as np

    from clinosim.modules.immunization.engine import generate_immunizations

    schedule = {k: v for k, v in load_schedule("US").items() if k == "pediatric_hpv"}
    patient = SimpleNamespace(patient_id="P1", date_of_birth=date(2002, 9, 1), age=24, sex="F")
    for seed in range(40):
        doses = [
            d
            for d in generate_immunizations(patient, schedule, date(2026, 11, 1), np.random.default_rng(seed))
            if d.status == "completed"
        ]
        days = sorted(d.occurrence_date for d in doses)
        assert len(days) == len(set(days)), (seed, days)
        for a, b in zip(days, days[1:]):
            assert (b - a).days >= 150, (seed, days)
