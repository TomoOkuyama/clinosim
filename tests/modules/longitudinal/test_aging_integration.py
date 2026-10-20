"""`advance_population` ↔ longitudinal engine integration.

Each sim year, `advance_population` must call `advance_one_year` on
every alive person whose longitudinal_history is behind the year.
See Phase 1 plan Task 7 brief.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population import aging as aging_mod
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.types.population import PersonRecord


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


def _registry_with_persons(*records: PersonRecord) -> PopulationRegistry:
    reg = PopulationRegistry()
    for r in records:
        reg.persons[r.person_id] = r
    reg.initial_person_ids = {r.person_id for r in records}
    return reg


@pytest.mark.unit
def test_advance_population_appends_snapshot_per_alive_dm_person() -> None:
    """DM E11 → longitudinal_history grows; non-DM → longitudinal
    stays at the initial snapshot (empty continuous for non-DM, but
    still gets a new empty snapshot each year); dead → unchanged."""
    from clinosim.modules.longitudinal.engine import initial_snapshot

    dm = PersonRecord(
        person_id="dm",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 6, 1),
        chronic_conditions=["E11.9"],
    )
    non_dm = PersonRecord(
        person_id="htn",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 6, 1),
        chronic_conditions=["I10"],
    )
    dead = PersonRecord(
        person_id="dead",
        household_id="HH",
        age=55,
        sex="M",
        date_of_birth=date(1970, 6, 1),
        chronic_conditions=["E11.9"],
        date_of_death=date(2020, 1, 1),
    )
    for p in (dm, non_dm, dead):
        initial_snapshot(p, year=2021, init_rng=np.random.default_rng(0))

    reg = _registry_with_persons(dm, non_dm, dead)
    advance_population(reg, year=2022, locale="US")

    assert len(dm.longitudinal_history) == 2
    assert "hba1c" in dm.longitudinal_history[-1].continuous
    assert len(non_dm.longitudinal_history) == 2
    assert "hba1c" not in non_dm.longitudinal_history[-1].continuous
    assert len(dead.longitudinal_history) == 1  # dead before year_start, aging skipped


@pytest.mark.unit
def test_advance_glycemic_trajectory_is_gone() -> None:
    """The retired helper + its glycemic ICD constant must be absent
    so a future caller re-introduction fails fast (AttributeError)."""
    assert not hasattr(aging_mod, "_advance_glycemic_trajectory")
    assert not hasattr(aging_mod, "_GLYCEMIC_ICDS")
    assert not hasattr(aging_mod, "_load_glycemic_trajectory_config")
