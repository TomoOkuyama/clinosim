"""Historical flu doses fall on varied clinic days of the month (Issue #3683)."""

from __future__ import annotations

from collections import Counter
from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.locale.clinic_calendar import is_clinic_day
from clinosim.modules.immunization.engine import flu_season_of, generate_immunizations_for_country, load_schedule

pytestmark = pytest.mark.unit

_AS_OF = date(2026, 11, 22)


def _patient(i: int) -> SimpleNamespace:
    return SimpleNamespace(patient_id=f"POP-{i:06d}", date_of_birth=date(1950, 3, 1), age=76, sex="F" if i % 2 else "M")


def _flu_doses(country: str, spread: bool, n: int = 200) -> list[tuple[int, date]]:
    schedule = load_schedule(country)
    flu_cvx = {str(v["cvx"]) for v in schedule.values() if v.get("frequency") == "annual"} | {
        str(p["cvx"]) for v in schedule.values() if v.get("frequency") == "annual" for p in v.get("products") or []
    }
    out = []
    for i in range(n):
        recs = generate_immunizations_for_country(
            country if spread else None, _patient(i), schedule, _AS_OF, np.random.default_rng(1000 + i)
        )
        out += [(i, r.occurrence_date) for r in recs if r.vaccine_cvx in flu_cvx and r.status == "completed"]
    return out


@pytest.mark.parametrize("country", ["US", "JP"])
def test_day_of_month_is_spread_and_on_clinic_days(country: str) -> None:
    doses = _flu_doses(country, spread=True)
    assert len(doses) > 300
    first = sum(1 for _, d in doses if d.day == 1) / len(doses)
    assert first < 0.10, first
    assert len({d.day for _, d in doses}) >= 15
    assert all(is_clinic_day(d, country) for _, d in doses)
    assert all(d <= _AS_OF for _, d in doses)


@pytest.mark.parametrize("country", ["US", "JP"])
def test_month_distribution_is_unchanged(country: str) -> None:
    old = _flu_doses(country, spread=False)
    new = _flu_doses(country, spread=True)
    key = lambda doses: Counter((i, d.year, d.month) for i, d in doses)  # noqa: E731
    # the month draw is untouched; only a dose whose spread day would leave the month moves, and none does
    assert key(old) == key(new)


def test_same_patient_and_season_give_the_same_day() -> None:
    assert _flu_doses("US", True, 30) == _flu_doses("US", True, 30)


def test_a_season_keeps_one_day_per_patient_year() -> None:
    doses = _flu_doses("US", True, 60)
    per_season = Counter((i, flu_season_of(d)) for i, d in doses)
    assert max(per_season.values()) == 1
