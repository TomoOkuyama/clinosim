"""BMI drift physiologic clamp (Phase 3 Task 5, Review Focus #4).

A 50-year AR(1) run from BMI 22 must never escape [13.0, 70.0]
regardless of seed — the yaml's clamp enforces physiologic bounds.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.engine import advance_one_year, initial_snapshot
from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.aging import aging_sub_seed
from clinosim.types.population import PersonRecord


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.integration
def test_bmi_drift_stays_in_physiologic_range_over_50_years():
    """Across 50 one-year advances, BMI must stay in [13.0, 70.0].
    Uses the real BMI yaml so the clamp bound is exercised end-to-end."""
    person = PersonRecord(
        person_id="PT-BMI-50Y",
        household_id="HH",
        age=35,
        sex="F",
        date_of_birth=date(1990, 1, 1),
        chronic_conditions=[],
        bmi=22.0,
    )
    rng = np.random.default_rng(aging_sub_seed(person.person_id, 2024, "longitudinal:init"))
    initial_snapshot(person, year=2024, init_rng=rng)
    # Seed Layer-1 continuity same way as population/engine.py would
    person.longitudinal_history[-1].continuous["bmi"] = float(person.bmi)
    for yr in range(2025, 2075):
        step_rng = np.random.default_rng(aging_sub_seed(person.person_id, yr, "longitudinal"))
        advance_one_year(person, year=yr, year_rng=step_rng)
    bmi_series = [snap.continuous.get("bmi") for snap in person.longitudinal_history]
    for i, bmi in enumerate(bmi_series):
        assert bmi is not None, f"year {i}: bmi missing from snapshot"
        assert 13.0 <= bmi <= 70.0, f"year {i} bmi {bmi} escaped physiologic clamp"
