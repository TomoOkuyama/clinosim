"""An AKI complication is dated at the first creatinine that meets the KDIGO
definition, and is not recorded when no creatinine does (Issue #3642)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.simulator.aki_response import date_aki_complications
from clinosim.simulator.complications import build_complication
from clinosim.types.encounter import OrderResult

pytestmark = pytest.mark.unit

ADMIT = datetime(2026, 6, 14, 10, 0)


def _cr(hours: float, value: float) -> OrderResult:
    return OrderResult(result_datetime=ADMIT + timedelta(hours=hours), lab_name="Creatinine", value=value)


def _aki(day: int) -> dict:
    onset = (ADMIT + timedelta(days=day)).replace(hour=12, minute=0, second=0, microsecond=0)
    return build_complication("acute_kidney_injury", day, onset.isoformat(), "daily_loop")


def test_onset_moves_to_the_first_qualifying_creatinine() -> None:
    # day 6 noon onset; the creatinine of day 6 07:53 is 1.37, day 7 06:37 is 2.15
    results = [_cr(0, 1.2), _cr(20, 1.25), _cr(6 * 24 - 2, 1.37), _cr(7 * 24 - 3, 2.15)]
    out = date_aki_complications([_aki(6)], results, ADMIT)
    assert len(out) == 1
    assert out[0]["onset_datetime"] == (ADMIT + timedelta(hours=7 * 24 - 3)).isoformat()
    assert out[0]["onset_day"] == 7


def test_onset_is_never_earlier_than_the_recorded_one() -> None:
    results = [_cr(0, 1.0), _cr(20, 1.5), _cr(3 * 24 - 2, 1.6)]
    original = _aki(4)
    out = date_aki_complications([original], results, ADMIT)
    assert out[0]["onset_datetime"] == original["onset_datetime"]
    assert out[0]["onset_day"] == 4


def test_no_qualifying_creatinine_drops_the_complication() -> None:
    results = [_cr(0, 1.2), _cr(24, 1.3), _cr(48, 1.25)]
    assert date_aki_complications([_aki(2)], results, ADMIT) == []


def test_other_complications_and_stays_without_aki_are_unchanged() -> None:
    other = build_complication("delirium", 3, "2026-06-17T12:00:00", "daily_loop")
    assert date_aki_complications([other], [_cr(0, 1.0)], ADMIT) == [other]
    assert date_aki_complications([], [], ADMIT) == []
