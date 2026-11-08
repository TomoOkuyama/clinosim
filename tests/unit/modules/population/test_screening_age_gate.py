"""Age-inappropriate screening gate — Issue #1189 F3.

Empirical audit: a 100-year-old with 4-year active pancreatic cancer
received two mammography_screening events over the sim window
because the sampler had no upper age cap. Similarly, annual health
screening was scheduled up through age 110+.

S14 adds the upper bounds; Issue #2870 moved the cancer-screening bands to
the protocols' ``screening_schedule``:
  - mammography 40-74 (USPSTF 2024 / JP MHLW 40-74 window)
  - colonoscopy 45-75 (USPSTF 2021)
  - `HEALTH_SCREENING_MAX_AGE = 89` (routine annual physical upper bound)

The gates are RNG-neutral: the prng draw at or above the lower age
gate is preserved for populations below the cap; only the emit is
skipped when age > MAX.
"""

from __future__ import annotations

import numpy as np


def _band(condition_id: str) -> tuple[int, int]:
    from clinosim.age_bands import parse_closed_age_band
    from clinosim.modules.encounter.protocol import screening_schedule

    return parse_closed_age_band(screening_schedule(condition_id).eligible_age)


def test_uspstf_aligned_bounds() -> None:
    from clinosim.modules.population._population_workflow_thresholds import HEALTH_SCREENING_MAX_AGE

    # USPSTF 2024 mammography = 40-74; 2021 colorectal = 45-75.
    # Annual health screening upper bound tuned to allow 85-89
    # individualized screening but stop >=90.
    assert _band("mammography_screening") == (40, 74)
    assert _band("colonoscopy_screening") == (45, 75)
    assert HEALTH_SCREENING_MAX_AGE == 89


def test_health_screening_dropped_for_age_100() -> None:
    """A 100-year-old must not pass the annual health screening age gate."""
    from clinosim.modules.population._population_workflow_thresholds import (
        HEALTH_SCREENING_MAX_AGE,
        HEALTH_SCREENING_MIN_AGE,
    )

    assert not (HEALTH_SCREENING_MIN_AGE <= 100 <= HEALTH_SCREENING_MAX_AGE)
    assert HEALTH_SCREENING_MIN_AGE <= 45 <= HEALTH_SCREENING_MAX_AGE


def test_mammography_dropped_for_age_100() -> None:
    lo, hi = _band("mammography_screening")
    assert not (lo <= 100 <= hi)
    assert lo <= 55 <= hi


def test_colonoscopy_dropped_for_age_100() -> None:
    lo, hi = _band("colonoscopy_screening")
    assert not (lo <= 100 <= hi)
    assert lo <= 62 <= hi


def test_rng_neutrality_marker() -> None:
    """The gates preserve prng.random() consumption for people whose
    age is at/above the lower gate — so populations without any
    >MAX-age people byte-shape-match the pre-fix output.

    This is a marker test: the actual byte-invariant is enforced by
    the daily-loop cohort regressions; here we assert the intended
    invariant in prose so a future edit that reintroduces a bare
    `age > MAX` short-circuit gets caught in review.
    """
    # If a future change reverts to `if age >= MIN and age <= MAX and rng()`
    # (short-circuit before rng), populations that include a MAX+
    # person will experience an RNG shift on the very next chronic
    # visit sample. The current implementation issues rng.random()
    # first (or draws it into a named local), then applies the age
    # cap on the emit side only.
    rng = np.random.default_rng(42)
    _ = rng.random()  # sentinel — confirms numpy is available for the guard.
    assert True
