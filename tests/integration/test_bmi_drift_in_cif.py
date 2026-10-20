"""BMI drift cohort integration (Phase 3 Task 7).

patient.bmi CIF emit stays at Layer-1 anchor in Phase 3 — the
year-varying BMI lives in longitudinal_history. The CIF schema does
not yet serialize longitudinal_history (deferred from Phase 1 I1), so
this test exercises the engine side directly: generate a p=100 adult
cohort, advance 5 years, and assert the cohort shows non-trivial
year-over-year BMI variance.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import advance_one_year
from clinosim.modules.population.aging import aging_sub_seed
from clinosim.modules.population.engine import generate_population


@pytest.mark.integration
def test_bmi_drift_produces_cohort_variance_over_5_years() -> None:
    """Generate p=100 US cohort, advance 5 years, extract per-year BMI
    series for each adult, confirm the aggregate variance exceeds the
    pure-noise floor (SD across 5-year series > 0.3 BMI units)."""
    registry = generate_population(
        size=100,
        country="US",
        rng=np.random.default_rng(42),
        base_year=2024,
    )
    adults = [p for p in registry.persons.values() if p.age >= 18]
    assert len(adults) >= 20, f"too few adults ({len(adults)}) to assess BMI drift"

    for yr in range(2025, 2030):
        for person in adults:
            if not person.longitudinal_history:
                continue
            if person.longitudinal_history[-1].year >= yr:
                continue
            step_rng = np.random.default_rng(aging_sub_seed(person.person_id, yr, "longitudinal"))
            advance_one_year(person, year=yr, year_rng=step_rng)

    # Compute per-person BMI SD across the 5-year series.
    series_sds: list[float] = []
    for person in adults:
        vals = [snap.continuous.get("bmi") for snap in person.longitudinal_history]
        vals = [v for v in vals if v is not None]
        if len(vals) < 2:
            continue
        sd = float(np.std(vals, ddof=1))
        series_sds.append(sd)

    assert len(series_sds) >= 20, f"collected only {len(series_sds)} series with ≥2 points"
    cohort_mean_sd = float(np.mean(series_sds))
    assert cohort_mean_sd > 0.3, (
        f"BMI drift mean per-person SD {cohort_mean_sd:.3f} ≤ 0.3 — AR(1) drift signal below pure-persistence floor"
    )
