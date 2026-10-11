"""Phase 2 scaffold: `advance_population` aging hook — Issue #1564.

Covers the scaffold contract (no behaviour change, isolated per-person
per-pass sub-RNGs, calls every alive person). Behavioural pass tests
land in the follow-up PRs that fill in the pass bodies.
"""

from __future__ import annotations

from datetime import date

from clinosim.modules.population.aging import (
    _allergy_drift,
    _annual_chronic_onset,
    _condition_reactive_mortality,
    _disease_progression,
    advance_population,
    aging_sub_seed,
)
from clinosim.modules.population.engine import PopulationRegistry
from clinosim.types.population import PersonRecord


def _alive(pid: str, age: int = 50) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=age,
        sex="M",
        date_of_birth=date(2026 - age, 1, 1),
    )


def _registry(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    reg.initial_person_ids = set(reg.persons.keys())
    return reg


def test_aging_sub_seed_deterministic_and_pass_isolated() -> None:
    """Same (person, year, pass) → same seed; different pass names →
    different seeds (so one pass's draws can't shift another's)."""
    s1 = aging_sub_seed("PT-1", 2026, "chronic_onset")
    s2 = aging_sub_seed("PT-1", 2026, "chronic_onset")
    assert s1 == s2
    assert s1 != aging_sub_seed("PT-1", 2026, "disease_progression")
    assert s1 != aging_sub_seed("PT-1", 2027, "chronic_onset")
    assert s1 != aging_sub_seed("PT-2", 2026, "chronic_onset")


def test_advance_population_is_noop_on_scaffold() -> None:
    """Scaffold invocation must not mutate any PersonRecord state —
    byte-identity guarantee for cohorts in the pre-Phase-2 world."""
    p = _alive("PT-1", age=40)
    before = (
        tuple(p.chronic_conditions),
        p.is_alive,
        p.date_of_death,
        tuple(p.allergies or ()),
    )
    reg = _registry([p])
    advance_population(reg, 2026)
    after = (
        tuple(p.chronic_conditions),
        p.is_alive,
        p.date_of_death,
        tuple(p.allergies or ()),
    )
    assert before == after


def test_advance_population_skips_dead_persons() -> None:
    """Dead persons must not get an aging pass — they are terminal."""
    p_dead = _alive("PT-DEAD", age=90)
    p_dead.is_alive = False
    p_alive = _alive("PT-ALIVE", age=50)
    reg = _registry([p_dead, p_alive])
    # Smoke: no exception, both passes run without side-effect
    advance_population(reg, 2026)
    assert p_dead.is_alive is False
    assert p_alive.is_alive is True


def test_pass_stubs_are_callable_no_op() -> None:
    """Each stub pass accepts (person, year, prng) and returns None
    without touching state — contract gate for the stub signatures."""
    import numpy as np

    p = _alive("PT-X", age=65)
    before = (tuple(p.chronic_conditions), p.is_alive, p.date_of_death)
    for fn in (
        _annual_chronic_onset,
        _disease_progression,
        _allergy_drift,
        _condition_reactive_mortality,
    ):
        rv = fn(p, 2026, np.random.default_rng(42))
        assert rv is None
    after = (tuple(p.chronic_conditions), p.is_alive, p.date_of_death)
    assert before == after
