"""US Layer-1 chronic prevalence lands on published US point-prevalence benchmarks.

The demographics.yaml chronic_prevalence values are the per-age target point
prevalence (the longitudinal onset engine keeps the cohort near them), so they
are checked at population generation against national surveys.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.population.engine import generate_population

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def us_population():
    return list(generate_population(10000, "US", np.random.default_rng(342)).persons.values())


def _prevalence(persons, prefixes: tuple[str, ...], lo: int, hi: int) -> float:
    pop = [p for p in persons if lo <= p.age <= hi]
    hit = sum(any(str(c).startswith(prefixes) for c in p.chronic_conditions) for p in pop)
    return hit / len(pop)


# CDC BRFSS (MMWR 2012 / 2013 national tables): 45-54 6.7%, 55-64 ~8.6-9%,
# 65+ 11.6-12.3%, adults ~6.0-6.5% (stable 2011-2021).
@pytest.mark.parametrize(
    ("lo", "hi", "low", "high"),
    [(18, 200, 0.045, 0.075), (45, 54, 0.05, 0.085), (55, 64, 0.065, 0.11), (65, 200, 0.095, 0.14)],
)
def test_copd_prevalence_matches_brfss(us_population, lo: int, hi: int, low: float, high: float) -> None:
    assert low <= _prevalence(us_population, ("J44",), lo, hi) <= high
