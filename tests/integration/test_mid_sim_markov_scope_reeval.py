"""Phase 4b.2.γ — mid-sim markov scope re-evaluation after event dispatch.

Phase 4b.2.β left a carve-out in test_cancer_stage_in_cif.py: a person
who ACQUIRES a cancer mid-sim via onset-event dispatch wasn't required
to have `chronic_stages[icd_base]` on the same-year snapshot, because
`_attribute_in_scope` was computed once at year top (before event
dispatch) and the newly in-scope Markov attribute wasn't dispatched
until the following year.

This test pins the fixed behavior: at p=200 seed=42 the integration
cohort has >=1 mid-sim cancer acquisition; every such person must have
the icd_base stage populated on the SAME year the onset event fires.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population

CANCER_ICD_BASES = ["C16", "C18", "C22", "C34", "C50", "C61"]


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.integration
def test_mid_sim_acquired_cancer_populates_stage_same_year() -> None:
    """At p=200 seed=42 the 5y advance produces >=1 mid-sim cancer onset.
    Every such person's `longitudinal_history[k].chronic_stages[icd_base]`
    must be populated on the snapshot where `new_complications`
    contains the icd — same-year, not one year late."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    initial_c = {
        pid: {b for b in CANCER_ICD_BASES if any(c.startswith(b) for c in p.chronic_conditions)}
        for pid, p in registry.persons.items()
    }
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    mid_sim_cases = []
    for pid, person in registry.persons.items():
        for b in CANCER_ICD_BASES:
            if any(c.startswith(b) for c in person.chronic_conditions) and b not in initial_c[pid]:
                mid_sim_cases.append((person, b))

    assert mid_sim_cases, "no mid-sim cancer acquisition in p=200 seed=42 sample — bump size or seed"

    for person, b in mid_sim_cases:
        onset_snap = None
        for snap in person.longitudinal_history:
            if any(c.startswith(b) for c in snap.new_complications):
                onset_snap = snap
                break
        assert onset_snap is not None, f"{person.person_id}: chronic has {b} but no new_complications entry"
        assert b in onset_snap.chronic_stages, (
            f"{person.person_id}: {b} acquired year {onset_snap.year} but stage missing from same-year snapshot"
        )
