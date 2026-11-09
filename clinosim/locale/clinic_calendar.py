"""Clinic days — when scheduled outpatient care is held (Issue #3018).

A scheduled outpatient visit (chronic follow-up, screening, vaccination,
pediatric, chemotherapy, post-discharge) is held on a clinic day of the
country's clinic calendar (``locale/<country>/clinic_calendar.yaml``): not on
a closed weekday (Sunday), a public holiday (JP 国民の祝日・休日, US federal
holidays) or a closed period (JP 年末年始). The ED is open every day and is not
affected. Pure date arithmetic: no RNG.
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from functools import cache

from clinosim.locale.loaders.fhir_identity import load_clinic_calendar

# A clinic calendar never closes this many days in a row; the search stops
# there rather than loop on a misconfigured calendar.
_MAX_CLOSED_RUN_DAYS = 31


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th ``weekday`` (Monday = 0) of the month; ``n = -1`` is the last."""
    days = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if date(year, month, d).weekday() == weekday]
    return date(year, month, days[n if n < 0 else n - 1])


def _observed(day: date) -> date:
    """A federal holiday on a Saturday is observed on Friday, on a Sunday on Monday."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@cache
def _holidays(country: str, year: int) -> frozenset[date]:
    """Closed public holidays of ``year`` in the country's clinic calendar."""
    cal = load_clinic_calendar(country)
    out: set[date] = set()
    for md in (cal.get("holidays") or {}).get(year, []):
        month, day = (int(x) for x in str(md).split("-"))
        out.add(date(year, month, day))
    federal = cal.get("federal_holidays") or {}
    # A fixed holiday of the next year can be observed in this one (1 Jan on a Saturday).
    for y in (year, year + 1):
        for rule in federal.get("fixed") or []:
            if y < int(rule.get("from_year", 0)):
                continue
            actual = date(y, int(rule["month"]), int(rule["day"]))
            out.update(d for d in (actual, _observed(actual)) if d.year == year)
    for rule in federal.get("nth_weekday") or []:
        out.add(_nth_weekday(year, int(rule["month"]), int(rule["weekday"]), int(rule["n"])))
    return frozenset(out)


def _in_period(day: date, start: str, end: str) -> bool:
    """``day`` within the inclusive month-day range ``start``..``end`` (may wrap the year end)."""
    md = (day.month, day.day)
    s = tuple(int(x) for x in start.split("-"))
    e = tuple(int(x) for x in end.split("-"))
    return s <= md <= e if s <= e else (md >= s or md <= e)


def is_clinic_day(day: date, country: str) -> bool:
    """True when outpatient clinics are open on ``day`` in ``country``."""
    cal = load_clinic_calendar(country)
    if day.weekday() in (cal.get("closed_weekdays") or []):
        return False
    if any(_in_period(day, str(p["start"]), str(p["end"])) for p in cal.get("closed_periods") or []):
        return False
    return day not in _holidays(country, day.year)


def clinic_visit_day(day: date, country: str, *, keep_year: bool = True) -> date:
    """The clinic day a visit planned on ``day`` is held on: ``day`` itself when
    clinics are open, else the next clinic day. With ``keep_year`` a visit the
    shift would carry into the next calendar year (JP 年末年始) is held on the
    previous clinic day instead, since each year's calendar plans its own
    visits."""
    later = day
    for _ in range(_MAX_CLOSED_RUN_DAYS):
        if is_clinic_day(later, country):
            break
        later += timedelta(days=1)
    if not keep_year or later.year == day.year:
        return later
    earlier = day
    for _ in range(_MAX_CLOSED_RUN_DAYS):
        if is_clinic_day(earlier, country):
            return earlier
        earlier -= timedelta(days=1)
    return later
