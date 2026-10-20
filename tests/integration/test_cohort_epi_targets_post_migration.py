"""Phase 4b.2.β Task 4 + Final-review C2 — cohort epi preserved post-migration.

The 30-ICD migration is semantic-only — byte-identity for every adult
patient breaks per spec §2.3 (acceptable).

Two assertion shapes:
1. **Loose end-of-sim band** — each ICD's final adult prevalence lands
   within a loose [lo, hi] bracket around the demographics.yaml target.
   Catches gross regressions (yaml deletion, zero-cohort generation).
2. **Baseline-vs-advanced delta** — for ICDs whose demographics.yaml
   declares a multi-band prevalence (non-zero per-year onset), the
   end-of-sim prevalence must strictly exceed the pre-advance initial
   cohort by at least a small positive delta. This is the dormancy
   detector: a loader regression that drops `base_rate_by_age_band`
   (Final-review C1) produces delta ≤ 0 and fails here.
"""

from __future__ import annotations


import numpy as np
import pytest

from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population

pytestmark = pytest.mark.integration


EPI_TARGETS = {
    # (ICD, min_prev_adult, max_prev_adult) — loose bracket around the
    # observed post-fix cohort prevalence (±30 % for p=500 stochasticity).
    "I10": (0.22, 0.45),
    "F32": (0.06, 0.14),
    "F00": (0.04, 0.11),
    "I25": (0.025, 0.07),
    "M17": (0.075, 0.16),
    "C61": (0.012, 0.04),
}

# ICDs that MUST see positive baseline → final-advance delta. If an ICD's
# yaml has multi-band prevalence (i.e. non-zero per-year onset from
# `_derive_annual_incidence_from_prevalence`), the engine must emit at
# least one new onset over 5 sim years at p=500.
EXPECT_POSITIVE_DELTA = ["I10", "F32", "F00", "I25", "M17"]


def test_adult_cohort_prevalence_in_target_bands_post_migration():
    """Loose epi-band regression: every ICD's end-of-sim adult prevalence
    stays inside its [lo, hi] bracket."""
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
            oor.append((icd, round(prev, 4), lo, hi))
    assert not oor, f"epi band violations: {oor}"


def test_longitudinal_engine_actually_increments_cohort_mid_sim():
    """Final-review C2: dormancy detector. For ICDs with non-zero
    per-year onset in demographics.yaml, 5 years of advance_population
    MUST produce a strictly positive delta in cohort prevalence over the
    pre-advance baseline. A loader regression that drops
    `base_rate_by_age_band` produces delta=0 and fails this assertion.
    """
    rng = np.random.default_rng(42)
    population = generate_population(size=500, country="US", rng=rng, base_year=2024)

    # Snapshot the Layer-1 initial chronic_conditions BEFORE advancing.
    baseline = {p.person_id: list(p.chronic_conditions) for p in population.persons.values()}

    for year in range(2024, 2029):
        advance_population(population, year=year, locale="us")

    adults = [p for p in population.persons.values() if (2028 - p.date_of_birth.year) >= 18]
    deltas = {}
    for icd in EXPECT_POSITIVE_DELTA:
        pre_hits = sum(1 for p in adults if icd in baseline.get(p.person_id, []))
        post_hits = sum(1 for p in adults if icd in p.chronic_conditions)
        deltas[icd] = (pre_hits, post_hits, post_hits - pre_hits)

    stagnant = [(icd, d) for icd, d in deltas.items() if d[2] <= 0]
    assert not stagnant, f"chronic-onset dormancy detected (loader regression?): {stagnant}; all deltas: {deltas}"
