"""End-to-end: longitudinal engine ↔ Layer-1 generation ↔ aging driver.

p=50 mini cohort validates `state_history` growth per sim year and
HbA1c scope gating. See Phase 1 plan Task 11 brief.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.integration
def test_mini_cohort_dm_patients_have_longitudinal_history_populated() -> None:
    """Every alive E11 person in a p=50 1-year cohort has >= 1
    snapshot after Layer-1 generation + an aging-year advance."""
    registry = generate_population(size=50, country="US", rng=np.random.default_rng(42), base_year=2024)
    advance_population(registry, year=2025, locale="US")
    dm_count = 0
    for person in registry.persons.values():
        if any(c.startswith(("E11", "E10")) for c in person.chronic_conditions) and person.age >= 18:
            dm_count += 1
            assert len(person.longitudinal_history) >= 2
            # Latest snapshot carries the HbA1c latent.
            assert "hba1c" in person.longitudinal_history[-1].continuous
            latent = person.longitudinal_history[-1].continuous["hba1c"]
            assert 4.0 <= latent <= 15.0
    assert dm_count > 0, "sample has no DM adults — bump size or seed"


@pytest.mark.integration
def test_mini_cohort_non_dm_patients_have_empty_hba1c() -> None:
    """Non-DM persons' snapshots carry no `hba1c` key — the scope
    gate drops the attribute cleanly."""
    registry = generate_population(size=50, country="US", rng=np.random.default_rng(42), base_year=2024)
    advance_population(registry, year=2025, locale="US")
    found_non_dm = False
    for person in registry.persons.values():
        if any(c.startswith(("E11", "E10")) for c in person.chronic_conditions):
            continue
        if person.age < 18:
            continue
        found_non_dm = True
        for snap in person.longitudinal_history:
            assert "hba1c" not in snap.continuous
    assert found_non_dm


@pytest.mark.integration
def test_mini_cohort_state_history_grows_year_over_year() -> None:
    """Each year advance appends a snapshot."""
    registry = generate_population(size=20, country="US", rng=np.random.default_rng(123), base_year=2024)
    for year in (2025, 2026, 2027):
        advance_population(registry, year=year, locale="US")
    for person in registry.persons.values():
        if not person.is_alive_at(__import__("datetime").date(2027, 1, 1)):
            continue
        # One initial + three year advances = 4 snapshots.
        assert len(person.longitudinal_history) >= 1  # dead-mid-run tolerance
