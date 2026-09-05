"""Natural-death sampling enricher (Issue #1114 C11g-2).

Runs at POST_POPULATION. For each person, iterates the sim-window years
they would be alive, rolls a Bernoulli against the age-conditional
annual qx from ``locale/shared/actuarial_life_table.yaml``, and if any
year fires, sets ``PersonRecord.date_of_death`` to a random day in
that year.

Byte-shape impact: adds a per-person sub-RNG (independent of the main
simulation stream). Does NOT wire the filter into event generators
yet — those still use the naive ``is_alive`` boolean, so encounters
for patients with a natural death date will still emit at their
original cadence. C11g-3 wires the actual filter.

Determinism: per-(person_id) sub-RNG derived from
``master_seed + ENRICHER_SEED_OFFSETS["natural_death"]``.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import numpy as np

from clinosim.locale.loader import load_actuarial_life_table
from clinosim.modules._shared import is_jp
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.simulator import log as sim_log

# 5-year band lower bounds used in the actuarial YAML (0, 5, 10, ..., 95).
_AGE_BAND_LOWER_BOUNDS = tuple(range(0, 100, 5))


def _qx_for(life_table: dict, country: str, sex: str, age: int) -> float:
    """Look up the age × sex annual mortality qx for a person.

    Falls back to the highest band (95+) for ages ≥ 100.
    Returns 0 (no death) when the table is empty or the sex key
    is unrecognized — safe fallback that keeps the enricher a no-op
    rather than raising in tests / partial-config paths.
    """
    country_key = "jp" if is_jp(country) else "us"
    country_block = ((life_table.get("annual_mortality_qx") or {}).get(country_key)) or {}
    sex_key = "male" if sex == "M" else "female" if sex == "F" else None
    if sex_key is None:
        return 0.0
    band_data = country_block.get(sex_key) or {}
    if not band_data:
        return 0.0
    # Bands are integer keys in the YAML; find the largest lower bound ≤ age.
    band = max((b for b in _AGE_BAND_LOWER_BOUNDS if b <= age), default=_AGE_BAND_LOWER_BOUNDS[-1])
    if band not in band_data:
        return 0.0
    return float(band_data[band])


def _sim_window(config: Any) -> tuple[date, date] | None:
    """Return the (start, end) sim window from config, or None if unresolved."""
    time_range = getattr(config, "time_range", None) or ()
    if len(time_range) < 2:
        return None
    try:
        start = date.fromisoformat(str(time_range[0])[:10])
        end = date.fromisoformat(str(time_range[1])[:10])
    except ValueError:
        return None
    return (start, end)


def sample_natural_deaths(ctx: Any) -> None:
    """POST_POPULATION enricher: sample per-person natural death dates.

    Adds a per-year Bernoulli against age-conditional qx over each
    person's sim-window years. First year that fires becomes the
    death year; the date is a uniform-day-in-year within that year
    (clamped to the sim window end).
    """
    life_table = load_actuarial_life_table()
    if not life_table:
        return
    country = getattr(getattr(ctx, "config", None), "country", "US") or "US"
    window = _sim_window(ctx.config)
    if window is None:
        return
    start, end = window
    n_dead = 0
    n_total = 0

    for person in ctx.population.persons.values():
        n_total += 1
        # Skip already-dead persons (e.g. an activator that pre-flipped
        # is_alive) — do not overwrite.
        if not getattr(person, "is_alive", True):
            continue
        pid = getattr(person, "person_id", "")
        sub_seed = derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["natural_death"], pid)
        rng = np.random.default_rng(sub_seed)
        age_at_start = int(getattr(person, "age", 0) or 0)
        sex = getattr(person, "sex", "M")

        death_date: date | None = None
        # Walk each calendar year in the window; year N contributes qx at
        # (age_at_start + years_elapsed).
        for year in range(start.year, end.year + 1):
            year_offset = year - start.year
            age_this_year = age_at_start + year_offset
            qx = _qx_for(life_table, country, sex, age_this_year)
            if qx <= 0.0:
                continue
            if float(rng.random()) < qx:
                # Death fires in this year. Pick a random day in year,
                # clamped to the sim window bounds if year is boundary.
                year_start = date(year, 1, 1)
                year_end = date(year, 12, 31)
                lo = max(year_start, start)
                hi = min(year_end, end)
                if lo > hi:
                    break
                span_days = (hi - lo).days + 1
                offset = int(rng.integers(0, span_days))
                death_date = lo + timedelta(days=offset)
                break

        if death_date is not None:
            person.date_of_death = death_date
            n_dead += 1

    if n_total > 0:
        sim_years = max(1, (end.year - start.year + 1))
        per_kyr = n_dead / n_total * 1000 / sim_years
        sim_log.info(
            "natural_death",
            "cohort_mortality_sampled",
            country=country,
            n_total=n_total,
            n_dead=n_dead,
            sim_years=sim_years,
            per_kyr=round(per_kyr, 2),
        )
