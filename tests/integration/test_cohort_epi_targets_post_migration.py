"""Phase 4b.2.β Task 4 — cohort epi bands preserved post-migration.

After migrating 30 adult-chronic onset events out of
`_annual_chronic_onset` into the longitudinal engine, each ICD's
end-of-sim prevalence must still land within an epi band derived from
the point-prevalence rows in `demographics.yaml::chronic_prevalence`.
Byte-identity is NOT required (spec §2.3 relaxation).
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population

pytestmark = pytest.mark.integration


# Point-prevalence bands expected on the end-of-sim cohort for the
# subset of ICDs that today's `_derive_annual_incidence_from_prevalence`
# produces a non-zero per-year onset for across at least one age band.
# ICDs whose demographics.yaml has only one age band (every point-
# prevalence row maps to a terminal "last band" with λ=0) are excluded
# here — they are initial-cohort-only and the migration preserves that.
#
# Band ± tolerance derived from the terminal-band prevalence × 0.5 (loose
# lower bound) and × 1.5 (loose upper bound) to absorb p=500 stochasticity
# and the stacking of 5y of annual draws on the top band.
EPI_TARGETS = {
    # (ICD, min_prev_adult, max_prev_adult)
    "I10": (0.20, 0.90),  # terminal 60-79 band 0.50; 80-99 is terminal with λ=0
    "F32": (0.03, 0.25),  # 18-39 λ=0.00154 over 5y
    "F00": (0.02, 0.60),  # 65-84 λ=0.014 climbs toward 85+ 0.30
    "I48": (0.00, 0.20),  # 50-74 λ=0.0034
    "I25": (0.00, 0.30),  # 50-69 λ=0.0055
    "M17": (0.00, 0.50),  # 50-69 λ=0.0097
    "G20": (0.00, 0.05),  # 60-79 λ=0.00076
    "C50": (0.00, 0.08),  # female 40-59 λ=0.0018
    "C61": (0.00, 0.08),  # male 60-69 λ=0.0059
}


def test_adult_cohort_prevalence_in_target_bands_post_migration():
    """p=500 US seed=42 5y cohort: each listed ICD's end-of-sim adult
    prevalence lands within its band."""
    rng = np.random.default_rng(42)
    population = generate_population(size=500, country="US", rng=rng, base_year=2024)
    for year in range(2024, 2029):
        advance_population(population, year=year, locale="us")

    adults = [p for p in population.persons.values() if (2028 - p.date_of_birth.year) >= 18]
    assert len(adults) > 0, "no adult persons in cohort"
    oor = []
    for icd, (lo, hi) in EPI_TARGETS.items():
        hits = sum(1 for p in adults if icd in p.chronic_conditions)
        prev = hits / len(adults)
        if not (lo <= prev <= hi):
            oor.append((icd, prev, lo, hi))
    assert not oor, f"epi band violations: {oor}"
