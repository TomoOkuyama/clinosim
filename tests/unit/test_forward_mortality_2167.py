"""Forward annual community mortality (Issue #2167)."""

from __future__ import annotations

from collections import Counter
from datetime import date

import numpy as np
import pytest

from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.modules.population.mortality import (
    annual_death_probability,
    community_death_share,
    draw_community_death,
    qx_for,
    smr_normalizers,
)
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit


def _person(pid: str, age: int, sex: str = "M", conditions: list[str] | None = None, year: int = 2025) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id=f"H-{pid}",
        age=age,
        sex=sex,
        date_of_birth=date(year - age, 6, 1),
        chronic_conditions=list(conditions or []),
    )


def _registry(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    reg.initial_person_ids = set(reg.persons)
    return reg


def test_life_table_lookup_uses_five_year_bands() -> None:
    assert qx_for("US", "M", 82) == qx_for("US", "M", 80) > qx_for("US", "M", 40) > 0
    assert qx_for("US", "X", 80) == 0.0


def test_community_share_is_calibrated_per_locale() -> None:
    for country in ("US", "JP"):
        assert 0.0 < community_death_share(country) < 1.0


def test_normalizer_keeps_the_band_mean_at_the_life_table_level() -> None:
    # Half the band carries heart failure (high SMR), half nothing.
    persons = [_person(f"P{i}", 82, conditions=["I50"] if i % 2 else []) for i in range(200)]
    norms = smr_normalizers(persons, 2025)
    norm = norms[(80, "M")]
    mean_q = np.mean([annual_death_probability(p, 2025, "US", norm) for p in persons])
    assert mean_q == pytest.approx(qx_for("US", "M", 82) * community_death_share("US"), rel=1e-9)
    sick = annual_death_probability(persons[1], 2025, "US", norm)
    well = annual_death_probability(persons[0], 2025, "US", norm)
    assert sick > well


def test_partial_exposure_never_dates_death_outside_it() -> None:
    nb = _person("NB", 0, year=2025)
    nb.date_of_birth = date(2025, 10, 20)
    hits = 0
    for seed in range(400):
        nb.date_of_death = nb.death_place = None
        q = draw_community_death(
            nb, 2025, "US", np.random.default_rng(seed), exposure=(date(2025, 10, 23), date(2025, 12, 31))
        )
        if q is not None:
            hits += 1
            assert date(2025, 10, 23) <= q <= date(2025, 12, 31)
            assert nb.death_place == "community"
    assert hits < 20  # infant hazard over ~2 months is small


def test_advance_population_draws_deaths_forward_without_a_fixed_day() -> None:
    persons = [_person(f"P{i:05d}", 88, sex="F") for i in range(3000)]
    reg = _registry(persons)
    advance_population(reg, 2025, "US", window=(date(2024, 1, 1), date(2026, 12, 31)))
    deaths = [p.date_of_death for p in persons if p.date_of_death]
    expected = len(persons) * qx_for("US", "F", 88) * community_death_share("US")
    assert abs(len(deaths) - expected) < 4 * expected**0.5
    assert all(d.year == 2025 for d in deaths)
    assert max(Counter(deaths).values()) < 10  # no single fixed death day


def test_draws_are_isolated_per_person() -> None:
    a = [_person(f"P{i:05d}", 88) for i in range(500)]
    b = [_person(f"P{i:05d}", 88) for i in range(500)] + [_person("EXTRA", 90)]
    advance_population(_registry(a), 2025, "US", window=(date(2025, 1, 1), date(2025, 12, 31)))
    advance_population(_registry(b), 2025, "US", window=(date(2025, 1, 1), date(2025, 12, 31)))
    assert [p.date_of_death for p in a] == [p.date_of_death for p in b[:500]]


def test_window_start_mid_year_limits_exposure() -> None:
    persons = [_person(f"P{i:05d}", 92) for i in range(2000)]
    advance_population(_registry(persons), 2025, "US", window=(date(2025, 10, 1), date(2026, 3, 31)))
    deaths = [p.date_of_death for p in persons if p.date_of_death]
    assert deaths and all(d >= date(2025, 10, 1) for d in deaths)


def test_newborn_birth_year_death_is_never_before_birth() -> None:
    from types import SimpleNamespace

    from clinosim.modules.population.person_init import initialize_newborn_biology

    config = SimpleNamespace(random_seed=11, country="US", time_range=("2024-01-01", "2026-12-31"))
    for i in range(300):
        nb = PersonRecord(person_id=f"NB-{i}", household_id="H", age=0, sex="F", date_of_birth=date(2026, 11, 3))
        initialize_newborn_biology(nb, config)
        if nb.date_of_death is not None:
            assert date(2026, 11, 3) <= nb.date_of_death <= date(2026, 12, 31)
            assert nb.death_place == "community"


def test_natural_death_pre_sampling_enricher_is_retired() -> None:
    from clinosim.simulator import enrichers

    enrichers.register_builtin_enrichers()
    assert "natural_death" not in enrichers._ENRICHERS


def test_elderly_die_far_more_often_than_the_young() -> None:
    young = [_person(f"Y{i:05d}", 15) for i in range(4000)]
    old = [_person(f"O{i:05d}", 85) for i in range(4000)]
    advance_population(_registry(young + old), 2025, "US", window=(date(2025, 1, 1), date(2025, 12, 31)))
    young_rate = sum(p.date_of_death is not None for p in young) / len(young)
    old_rate = sum(p.date_of_death is not None for p in old) / len(old)
    assert old_rate > 5 * max(young_rate, 1 / len(young))
