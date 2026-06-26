"""Immunization history generation (AD-55 Base).

Pure functions deriving a patient's adult vaccine history from demographics and a
locale schedule (eligibility age, availability date, season, age/sex coverage).
Codes (CVX) live in clinosim.codes; schedules in clinosim/locale/<country>/.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml

_HERE = Path(__file__).resolve().parent
_LOCALE = _HERE.parents[1] / "locale"


@lru_cache(maxsize=4)
def load_schedule(country: str) -> dict:
    key = "jp" if str(country).upper() == "JP" else "us"
    with open(_LOCALE / key / "immunization_schedule.yaml") as f:
        return (yaml.safe_load(f) or {}).get("vaccines", {})


def _age_on(dob: date | None, on: date, fallback_age: int) -> int:
    if dob is None:
        return fallback_age
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def _coverage(cov: dict, age: int, sex: str) -> float:
    for band, ms in cov.items():
        lo, hi = (int(x) for x in band.split("-"))
        if lo <= age <= hi:
            return float(ms.get(sex, next(iter(ms.values()))))
    return 0.0


def _parse(d: str) -> date:
    y, m, day = (int(x) for x in d.split("-"))
    return date(y, m, day)


def _safe_date(year: int, month: int, day: int) -> date:
    """Construct a date, clamping Feb 29 to Feb 28 in non-leap years."""
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, day - 1)


def generate_immunizations(patient, schedule: dict, as_of: date,
                           rng: np.random.Generator) -> list:
    from clinosim.types.encounter import ImmunizationRecord

    dob = getattr(patient, "date_of_birth", None)
    base_age = int(getattr(patient, "age", 0) or 0)
    sex = getattr(patient, "sex", "M") or "M"
    out: list = []

    for _name, v in schedule.items():
        cvx = str(v["cvx"])
        min_age = int(v["min_age"])
        avail = _parse(v["available_from"])
        freq = v["frequency"]
        cov = v["coverage_by_age_sex"]

        # earliest eligible date = max(availability, date patient reached min_age)
        if dob is not None:
            reached = _safe_date(dob.year + min_age, dob.month, dob.day)
        else:
            reached = date(as_of.year - (base_age - min_age), 1, 1) if base_age >= min_age else None
        if reached is None:
            continue
        start = max(avail, reached)
        # Optional EHR data-retention window: only keep the last `history_years`
        # of history (real EHRs don't carry decades of e.g. annual flu shots).
        history_years = v.get("history_years")
        if history_years is not None:
            lookback = _safe_date(
                as_of.year - int(history_years), as_of.month, as_of.day
            )
            start = max(start, lookback)
        if start > as_of:
            continue

        if freq == "annual":
            month = int(v.get("season_month", 10))
            for yr in range(start.year, as_of.year + 1):
                occ = date(yr, month, 1)
                if occ < start or occ > as_of:
                    continue
                age_at = _age_on(dob, occ, base_age)
                if rng.random() < _coverage(cov, age_at, sex):
                    out.append(ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=occ))
        elif freq == "every_n_years":
            interval = int(v.get("interval_years", 10))
            yr = start.year
            while _safe_date(yr, start.month, start.day) <= as_of:
                occ = _safe_date(yr, start.month, start.day)
                age_at = _age_on(dob, occ, base_age)
                if rng.random() < _coverage(cov, age_at, sex):
                    out.append(ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=occ))
                yr += interval
        else:  # once
            age_at = _age_on(dob, as_of, base_age)
            if rng.random() < _coverage(cov, age_at, sex):
                # place once at a deterministic point within [start, as_of]
                span = (as_of - start).days
                offset = int(rng.integers(0, span + 1)) if span > 0 else 0
                occ = date.fromordinal(start.toordinal() + offset)
                out.append(ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=occ))

    out.sort(key=lambda r: r.occurrence_date)
    return out
