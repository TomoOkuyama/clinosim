"""Forward annual mortality — community deaths (Issue #2167).

Deaths outside this hospital's inpatient stays ("community" deaths) are drawn
year by year, as the simulation reaches each year, instead of being
pre-sampled for the whole window at t0. In-hospital deaths come from the
inpatient simulator; both are recorded through ``PersonRecord.record_death``.

Hazard for person *i* in year *y*::

    q_i = qx(age_y, sex) × SMR_i / mean(SMR | alive, age band, sex) × community_share

* ``qx`` — all-cause annual mortality from
  ``locale/shared/actuarial_life_table.yaml``.
* ``SMR_i`` — combined standardised mortality ratio of the person's chronic
  conditions (``locale/shared/condition_mortality_smr.yaml``). Dividing by
  the cohort mean in the same band keeps the cohort at the life-table level
  while sicker persons die earlier (marginal-preserving).
* ``community_share`` — the fraction of all-cause deaths that happen outside
  this hospital's simulated inpatient stays, calibrated per locale so that
  community plus in-hospital deaths match the life table.

The draw for a partial year of exposure (window start, birth) uses
``1 − (1 − q)^fraction``, and the death day is uniform over the exposure.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from functools import lru_cache
from typing import Any

import numpy as np

from clinosim.locale.loader import load_actuarial_life_table, load_condition_mortality_smr
from clinosim.modules._shared import is_jp
from clinosim.types.population import PersonRecord

__all__ = [
    "age_in_year",
    "annual_death_probability",
    "band_of",
    "combined_smr",
    "community_death_share",
    "draw_community_death",
    "qx_for",
    "sim_window",
    "smr_normalizers",
]

# 5-year band lower bounds used by the actuarial yaml (0, 5, …, 95).
_BAND_LOWER_BOUNDS = tuple(range(0, 100, 5))
# A single year's hazard never reaches certainty.
_MAX_ANNUAL_Q = 0.95


def _locale_key(country: str) -> str:
    return "jp" if is_jp(country) else "us"


def band_of(age: int) -> int:
    return max((b for b in _BAND_LOWER_BOUNDS if b <= age), default=0)


def age_in_year(person: PersonRecord, year: int) -> int:
    """Age reached during ``year`` (``year − birth year``)."""
    return year - person.date_of_birth.year


@lru_cache(maxsize=1)
def _life_table() -> dict:
    return load_actuarial_life_table() or {}


def qx_for(country: str, sex: str, age: int) -> float:
    """All-cause annual death probability for (country, sex, age)."""
    block = (_life_table().get("annual_mortality_qx") or {}).get(_locale_key(country)) or {}
    sex_key = "male" if sex == "M" else "female" if sex == "F" else None
    if sex_key is None:
        return 0.0
    bands = block.get(sex_key) or {}
    return float(bands.get(band_of(max(0, age)), 0.0))


def community_death_share(country: str) -> float:
    """Fraction of all-cause deaths drawn as community deaths (default 1.0)."""
    shares = _life_table().get("community_death_share") or {}
    return float(shares.get(_locale_key(country), 1.0))


@lru_cache(maxsize=1)
def _smr_config() -> tuple[dict[str, float], str]:
    data = load_condition_mortality_smr() or {}
    table = {str(k): float(v) for k, v in (data.get("smr_table") or {}).items()}
    return table, str(data.get("combine_method") or "geometric_mean")


def combined_smr(conditions: Iterable[str]) -> float:
    """Combine per-ICD SMRs (exact code, else longest listed prefix) into one.

    Codes without an entry contribute nothing; no contribution gives 1.0.
    """
    table, method = _smr_config()
    contributions: list[float] = []
    seen: set[str] = set()
    for code in conditions:
        key = (
            code if code in table else next((code[:i] for i in range(len(code) - 1, 0, -1) if code[:i] in table), None)
        )
        if key is None or key in seen:
            continue
        seen.add(key)
        contributions.append(table[key])
    if not contributions:
        return 1.0
    if method == "geometric_mean":
        return math.exp(sum(math.log(v) for v in contributions) / len(contributions))
    return sum(contributions) / len(contributions)


def smr_normalizers(persons: Iterable[PersonRecord], year: int) -> dict[tuple[int, str], float]:
    """Mean combined SMR of persons alive on 1 January, by (age band, sex).

    Deterministic (no RNG). Bands with no living person are absent; callers
    fall back to 1.0.
    """
    sums: dict[tuple[int, str], float] = defaultdict(float)
    counts: dict[tuple[int, str], int] = defaultdict(int)
    jan1 = date(year, 1, 1)
    for person in persons:
        if not person.is_alive_at(jan1):
            continue
        key = (band_of(age_in_year(person, year)), person.sex)
        sums[key] += combined_smr(person.chronic_conditions)
        counts[key] += 1
    return {k: sums[k] / counts[k] for k in sums}


def annual_death_probability(person: PersonRecord, year: int, country: str, normalizer: float = 1.0) -> float:
    """Community death probability for a full year of exposure."""
    qx = qx_for(country, person.sex, age_in_year(person, year))
    if qx <= 0.0:
        return 0.0
    relative = combined_smr(person.chronic_conditions) / (normalizer if normalizer > 0 else 1.0)
    return min(_MAX_ANNUAL_Q, qx * relative * community_death_share(country))


def draw_community_death(
    person: PersonRecord,
    year: int,
    country: str,
    prng: np.random.Generator,
    *,
    exposure: tuple[date, date],
    normalizer: float = 1.0,
) -> date | None:
    """Draw whether ``person`` dies in the community during ``exposure``.

    ``exposure`` is the part of ``year`` the person is simulated and alive
    (inclusive). On a hit the death is recorded on the person and returned.
    Always consumes exactly one ``random()`` and, on a hit, one ``integers``.
    """
    lo, hi = exposure
    if lo > hi:
        return None
    q = annual_death_probability(person, year, country, normalizer)
    year_days = (date(year, 12, 31) - date(year, 1, 1)).days + 1
    span = (hi - lo).days + 1
    p = 1.0 - (1.0 - q) ** (span / year_days)
    if float(prng.random()) >= p:
        return None
    when = lo + timedelta(days=int(prng.integers(0, span)))
    person.record_death(when, "community")
    return when


def sim_window(config: Any) -> tuple[date, date] | None:
    """Return the (start, end) sim window from config, or None if unresolved.

    Public helper so other callers (newborn biology init) can derive the
    sim-window bounds without duplicating the time_range parsing. Returns
    None instead of raising so test paths that omit ``config.time_range``
    stay on a no-op branch.
    """
    raw = getattr(config, "time_range", None)
    if raw is None:
        return None
    try:
        time_range = tuple(raw)
    except TypeError:
        return None
    if len(time_range) < 2:
        return None
    # Unpack so mypy narrows to concrete elements (indexing `time_range[0]`
    # on a heterogeneous tuple[Any, ...] read from getattr triggers
    # `Tuple index out of range` under the shipped mypy config).
    raw_start, raw_end = time_range[0], time_range[1]
    try:
        start = date.fromisoformat(str(raw_start)[:10])
        end = date.fromisoformat(str(raw_end)[:10])
    except ValueError:
        return None
    return (start, end)
