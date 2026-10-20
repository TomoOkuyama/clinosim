"""Layer-1 initial_snapshot seeding at generate_population.

Every alive person must land with a non-empty `longitudinal_history`
containing one entry at the sim-start year, scoped by chronic codes
and age band.

See Phase 1 plan Task 6 brief.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.engine import generate_population


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.unit
def test_generate_population_seeds_longitudinal_history_for_every_person() -> None:
    """Every generated person has exactly one YearSnapshot after
    Layer-1 generation."""
    registry = generate_population(size=50, country="US", rng=np.random.default_rng(42))
    for person in registry.persons.values():
        assert len(person.longitudinal_history) == 1
        assert person.longitudinal_history[0].year > 0


@pytest.mark.unit
def test_generate_population_populates_hba1c_for_dm_adults_only() -> None:
    """DM adults → `hba1c` key present; everyone else → absent."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(7))
    dm_adults = []
    others = []
    for person in registry.persons.values():
        snap = person.longitudinal_history[0]
        has_hba1c = "hba1c" in snap.continuous
        is_dm_adult = (
            any(c.startswith(("E11", "E10")) for c in person.chronic_conditions)
            and person.age >= 18
        )
        if is_dm_adult:
            dm_adults.append(has_hba1c)
        else:
            others.append(has_hba1c)
    assert dm_adults, "no DM adults in sample — bump the size"
    assert all(dm_adults), "every DM adult should have hba1c latent"
    assert not any(others), "non-DM / pediatric should have no hba1c latent"
