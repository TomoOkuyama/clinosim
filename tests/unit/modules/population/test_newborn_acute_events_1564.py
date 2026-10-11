"""Newborn acute-event activation via `person_filter` — Issue #1564 Phase 1 completion.

The engine's secondary pass uses `generate_monthly_events(..., person_filter=...)`
to generate acute monthly events for mid-sim-added newborns without
disturbing the initial cohort. These tests exercise the filter kwarg
directly on `generate_monthly_events`.
"""

from __future__ import annotations

from datetime import date

import numpy as np

from clinosim.modules.population.engine import (
    Household,
    PopulationRegistry,
    generate_monthly_events,
)
from clinosim.types.population import PersonRecord


def _adult(pid: str, age: int = 50) -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-A",
        age=age,
        sex="M",
        date_of_birth=date(2026 - age, 1, 1),
        care_seeking_threshold=0.9,  # tight, keeps event count small+stable
    )


def _registry_with(persons: list[PersonRecord]) -> PopulationRegistry:
    reg = PopulationRegistry()
    for p in persons:
        reg.persons[p.person_id] = p
    reg.households.append(Household(household_id="HH-A", members=list(persons)))
    reg.initial_person_ids = set(reg.persons.keys())
    return reg


def test_person_filter_processes_only_matching_persons() -> None:
    """A filter returning True for one id and False for another must
    produce events only for the matched person."""
    p1 = _adult("P-1", age=70)
    p2 = _adult("P-2", age=70)
    reg = _registry_with([p1, p2])

    rng = np.random.default_rng(42)
    events = generate_monthly_events(
        reg,
        2026,
        6,
        rng,
        country="US",
        person_filter=lambda p: p.person_id == "P-1",
    )
    for e in events:
        assert e.person_id == "P-1", f"event leaked for {e.person_id}"


def test_person_filter_none_is_default_behaviour() -> None:
    """Default (no filter) still iterates every person — regression gate
    for the kwarg addition."""
    p1 = _adult("P-1", age=70)
    p2 = _adult("P-2", age=70)
    reg = _registry_with([p1, p2])

    rng = np.random.default_rng(42)
    baseline = generate_monthly_events(reg, 2026, 6, rng, country="US")

    rng = np.random.default_rng(42)
    with_none = generate_monthly_events(
        reg,
        2026,
        6,
        rng,
        country="US",
        person_filter=None,
    )

    # Byte-identical event sequences
    assert [(e.person_id, e.timestamp, e.disease_id) for e in baseline] == [
        (e.person_id, e.timestamp, e.disease_id) for e in with_none
    ]


def test_person_filter_does_not_shift_initial_cohort_stream() -> None:
    """When a newborn-only filter runs AFTER initial-cohort generation
    (sharing the same rng key), the initial cohort's events for the
    same month are identical to the no-newborn-exists case.

    Rationale: the engine's secondary pass uses a DIFFERENT phase_rng
    key (``newborn|YYYY-MM`` vs ``YYYY-MM``), so initial and newborn
    passes are stream-independent by construction. This test documents
    the invariant that `person_filter` itself has no RNG side-effect
    beyond skipping the body for a filtered-out person.
    """
    p1 = _adult("P-1", age=70)
    p2 = _adult("P-2", age=70)

    # Case A: only initial cohort.
    reg_a = _registry_with([p1, p2])
    rng_a = np.random.default_rng(42)
    events_a = generate_monthly_events(reg_a, 2026, 6, rng_a, country="US")

    # Case B: initial cohort + a "newborn" extra, but filter restricts
    # processing to initial pids only.
    extra = _adult("P-NB", age=0)
    reg_b = _registry_with([p1, p2])
    reg_b.persons[extra.person_id] = extra
    rng_b = np.random.default_rng(42)
    events_b = generate_monthly_events(
        reg_b,
        2026,
        6,
        rng_b,
        country="US",
        person_filter=lambda p: p.person_id in {"P-1", "P-2"},
    )

    assert [(e.person_id, e.timestamp, e.disease_id) for e in events_a] == [
        (e.person_id, e.timestamp, e.disease_id) for e in events_b
    ]
