"""Expected G47.30 prevalence matches moderate-to-severe OSA (AHI >= 15) from Peppard 2013."""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.metabolic.engine import _osa_probability
from clinosim.modules.population.engine import generate_population

pytestmark = pytest.mark.unit


@pytest.fixture(scope="module")
def us_population():
    return list(generate_population(10000, "US", np.random.default_rng(342)).persons.values())


# Peppard et al., Am J Epidemiol 2013 (PMID 23589584), AHI >= 15:
# men 30-49 10% (CI 7-12), men 50-70 17% (15-21), women 30-49 3% (2-4), women 50-70 9% (7-11).
@pytest.mark.parametrize(
    ("sex", "lo", "hi", "low", "high"),
    [("M", 30, 49, 0.07, 0.13), ("M", 50, 70, 0.14, 0.21), ("F", 30, 49, 0.02, 0.045), ("F", 50, 70, 0.065, 0.115)],
)
def test_expected_osa_prevalence_matches_peppard(us_population, sex, lo, hi, low, high) -> None:
    group = [p for p in us_population if p.sex.upper().startswith(sex) and lo <= p.age <= hi]
    expected = float(np.mean([_osa_probability(p.bmi, p.sex, p.age) for p in group]))
    assert low <= expected <= high
